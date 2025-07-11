#!/usr/bin/env python3

"""
MCP Master Process - Multi-Port Architecture
Master process that spawns and monitors unified worker processes for each repository.

This master process:
- Reads repository configuration with port assignments
- Spawns unified worker processes (GitHub + codebase tools) for each repository on dedicated ports
- Monitors worker health and restarts failed processes
- Handles graceful shutdown and cleanup
"""

import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from constants import LOGS_DIR, Language
from python_symbol_extractor import PythonSymbolExtractor
from repository_indexer import PythonRepositoryIndexer
from repository_manager import RepositoryConfig, RepositoryManager

# Import shutdown coordination components
from shutdown_simple import (
    SimpleHealthMonitor,
    SimpleShutdownCoordinator,
)
from startup_orchestrator import CodebaseStartupOrchestrator
from symbol_storage import ProductionSymbolStorage, SQLiteSymbolStorage
from system_utils import MicrosecondFormatter, log_system_state
from validation_registry import initialize_validation_registry

# Configure logging with enhanced microsecond precision


LOGS_DIR.mkdir(parents=True, exist_ok=True)

GLOBAL_LOG_LEVEL = logging.DEBUG


def setup_enhanced_logging(
    logger: logging.Logger, log_file_path: Path | None = None
) -> logging.Logger:
    """Enhance an existing logger with microsecond precision formatting

    This is called from the master process to enhance the main logger
    that will be passed to all components throughout the system.
    """
    # Prevent duplicate handlers
    if logger.handlers:
        logger.handlers.clear()

    # Detailed formatter with microseconds
    detailed_formatter = MicrosecondFormatter(
        "%(asctime)s [%(levelname)8s] %(name)s.%(funcName)s:%(lineno)d - %(message)s"
    )

    # Console formatter with microseconds
    console_formatter = MicrosecondFormatter("%(asctime)s [%(levelname)s] %(message)s")

    # File handler for detailed debug logs (use provided path or default)
    if log_file_path is None:
        log_file_path = LOGS_DIR / "master.log"

    file_handler = logging.FileHandler(log_file_path, mode="a")
    file_handler.setLevel(GLOBAL_LOG_LEVEL)
    file_handler.setFormatter(detailed_formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(GLOBAL_LOG_LEVEL)
    console_handler.setFormatter(console_formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("Enhanced logging initialized with microsecond precision")
    logger.debug(f"Log file: {log_file_path}")
    logger.debug(f"Log level set to: {logging.getLevelName(logger.level)}")

    return logger


# Create and setup the master logger
logger = logging.getLogger(__name__)
logger.setLevel(GLOBAL_LOG_LEVEL)
logger = setup_enhanced_logging(logger)


@dataclass
class WorkerProcess:
    """Information about a worker process"""

    repository_config: RepositoryConfig
    process: subprocess.Popen[bytes] | None = None
    start_time: float | None = None
    restart_count: int = 0
    max_restarts: int = 5

    @property
    def repo_name(self) -> str:
        return self.repository_config.name

    @property
    def port(self) -> int:
        return self.repository_config.port

    @property
    def path(self) -> str:
        return self.repository_config.path

    @property
    def description(self) -> str:
        return self.repository_config.description

    @property
    def language(self) -> Language:
        return self.repository_config.language

    @property
    def python_path(self) -> str:
        return self.repository_config.python_path


def is_port_free(port: int) -> bool:
    """Check if a port is available for binding"""
    logger.debug(f"is_port_free: Checking port {port}")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            logger.debug(f"is_port_free: Created socket for port {port}")
            s.bind(("0.0.0.0", port))
            logger.debug(
                f"is_port_free: Successfully bound to port {port} - PORT IS FREE"
            )
            return True
    except OSError as e:
        logger.debug(f"is_port_free: Port {port} is in use: {e}")
        return False


async def wait_for_port_free(port: int, timeout: int = 30) -> bool:
    """Wait for a port to become available, with timeout"""
    logger.debug(
        f"wait_for_port_free: Starting to wait for port {port} with timeout {timeout}s"
    )
    start_time = time.time()

    check_count = 0
    while time.time() - start_time < timeout:
        check_count += 1
        elapsed = time.time() - start_time
        logger.debug(
            f"wait_for_port_free: Check #{check_count} for port {port} after {elapsed:.1f}s"
        )

        if is_port_free(port):
            logger.debug(
                f"wait_for_port_free: Port {port} is now available after {elapsed:.1f}s and {check_count} checks"
            )
            return True

        logger.debug(f"wait_for_port_free: Port {port} still not free, sleeping 1s...")
        await asyncio.sleep(1.0)  # Check every 1 second
        logger.debug(f"wait_for_port_free: Woke up from sleep for port {port}")

    final_elapsed = time.time() - start_time
    logger.error(
        f"wait_for_port_free: Timeout waiting for port {port} after {final_elapsed:.1f}s and {check_count} checks"
    )
    return False


class MCPMaster:
    """Master process for managing multiple MCP worker processes"""

    def __init__(
        self,
        repository_manager: RepositoryManager,
        workers: dict[str, WorkerProcess],
        startup_orchestrator: CodebaseStartupOrchestrator,
        symbol_storage: SQLiteSymbolStorage,
        shutdown_coordinator: SimpleShutdownCoordinator,
        health_monitor: SimpleHealthMonitor,
    ):
        self.repository_manager = repository_manager
        self.workers = workers
        self.startup_orchestrator = startup_orchestrator
        self.symbol_storage = symbol_storage
        self.shutdown_coordinator = shutdown_coordinator
        self.health_monitor = health_monitor
        self.running = False

        # Use system-appropriate log location
        self.log_dir = LOGS_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

    async def initialize_repository_indexes(self) -> None:
        """Initialize repository indexes using the startup orchestrator."""

        try:
            logger.info("Initializing repository indexes...")

            # Get list of repository configurations
            repositories = list(self.repository_manager.repositories.values())

            # Run startup orchestration
            result = await self.startup_orchestrator.initialize_repositories(
                repositories
            )

            # Log detailed results
            logger.info("Repository indexing completed:")
            logger.info(f"  - Total repositories: {result.total_repositories}")
            logger.info(f"  - Successfully indexed: {result.indexed_repositories}")
            logger.info(f"  - Failed to index: {result.failed_repositories}")
            logger.info(f"  - Skipped (non-Python): {result.skipped_repositories}")
            logger.info(f"  - Success rate: {result.success_rate:.1%}")
            logger.info(f"  - Total time: {result.startup_duration:.2f}s")

            # Log detailed status for each repository
            for status in result.indexing_statuses:
                if status.status == "completed" and status.result:
                    logger.info(
                        f"  - {status.repository_id}: {status.result.total_symbols} symbols, "
                        f"{len(status.result.processed_files)} files, "
                        f"{status.duration:.2f}s"
                    )
                elif status.status == "failed":
                    logger.warning(
                        f"  - {status.repository_id}: FAILED - {status.error_message}"
                    )

        except Exception as e:
            logger.error(f"Failed to initialize repository indexes: {e}")
            # Don't fail the entire startup - continue without indexing

    def start_worker(self, worker: WorkerProcess) -> bool:
        """Start a worker process for a repository"""
        try:
            if worker.process and worker.process.poll() is None:
                logger.warning(f"Worker for {worker.repo_name} is already running")
                return True

            # Command to start worker process
            # Use the virtual environment Python explicitly
            venv_python = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python"
            )
            python_executable = (
                venv_python if os.path.exists(venv_python) else sys.executable
            )

            # Use repository config to generate command arguments
            cmd = [
                python_executable,
                "mcp_worker.py",
                *worker.repository_config.to_args(),
            ]

            # Set up environment
            env = os.environ.copy()
            env["PYTHONPATH"] = os.getcwd()

            # Check if port is available before starting
            if not is_port_free(worker.port):
                logger.error(
                    f"Port {worker.port} is not available for {worker.repo_name}"
                )
                return False

            # Start the process
            worker.process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
            )

            worker.start_time = time.time()
            logger.info(
                f"Started worker for {worker.repo_name} on port {worker.port} (PID: {worker.process.pid})"
            )

            # Worker process is already stored in self.workers dict
            # No duplicate tracking needed with simplified architecture

            return True

        except Exception as e:
            logger.error(f"Failed to start worker for {worker.repo_name}: {e}")
            return False

    async def stop_worker(self, worker: WorkerProcess, timeout: int = 5) -> bool:
        """Stop a worker process with timeout (simplified for individual worker shutdown)"""
        try:
            if not worker.process or worker.process.poll() is not None:
                logger.info(f"Worker for {worker.repo_name} is already stopped")
                worker.process = None
                return True

            pid = worker.process.pid
            logger.info(f"Stopping worker {worker.repo_name} (PID: {pid})")

            # Send SIGTERM for graceful shutdown
            worker.process.terminate()

            # Wait for graceful shutdown with timeout
            try:
                await asyncio.wait_for(
                    asyncio.create_task(self._wait_for_process_exit(worker.process)),
                    timeout=timeout,
                )
                logger.info(f"Worker for {worker.repo_name} stopped gracefully")
                worker.process = None
                return True
            except TimeoutError:
                # Force kill if doesn't respond
                logger.warning(
                    f"Worker for {worker.repo_name} didn't respond to SIGTERM within {timeout}s, force killing"
                )
                try:
                    if worker.process is not None:
                        worker.process.kill()
                        await asyncio.wait_for(
                            asyncio.create_task(
                                self._wait_for_process_exit(worker.process)
                            ),
                            timeout=2,
                        )
                    logger.info(
                        f"Worker for {worker.repo_name} force killed successfully"
                    )
                    worker.process = None
                    return True
                except TimeoutError:
                    logger.error(
                        f"Worker for {worker.repo_name} couldn't be killed even with SIGKILL"
                    )
                    return False

        except Exception as e:
            logger.error(f"Exception stopping worker {worker.repo_name}: {e}")
            # Emergency cleanup
            if worker.process:
                try:
                    worker.process.kill()
                    worker.process = None
                except Exception:
                    pass
            return False

    def is_worker_healthy(self, worker: WorkerProcess) -> bool:
        """Check if a worker process is healthy"""
        if not worker.process:
            logger.debug(f"Worker for {worker.repo_name} has no process")
            return False

        # Check if process is still alive
        poll_result = worker.process.poll()
        if poll_result is not None:
            logger.warning(
                f"Worker for {worker.repo_name} is not running (exit code: {poll_result})"
            )
            # Log any output from the failed process
            try:
                stdout, stderr = worker.process.communicate(timeout=1)
                if stdout:
                    logger.error(f"Worker {worker.repo_name} STDOUT: {stdout.decode()}")
                if stderr:
                    logger.error(f"Worker {worker.repo_name} STDERR: {stderr.decode()}")
            except Exception as e:
                logger.debug(f"Failed to read worker output: {e}")
            return False

        # TODO: Add health check HTTP endpoint call
        # For now, just check if process is running
        return True

    async def monitor_workers(self) -> None:
        """Monitor worker processes and restart if needed"""
        logger.debug("Worker monitoring task started")
        try:
            while self.running:
                try:
                    for repo_name, worker in self.workers.items():
                        if not self.is_worker_healthy(worker):
                            if worker.restart_count < worker.max_restarts:
                                logger.warning(
                                    f"Worker for {repo_name} is unhealthy, restarting..."
                                )
                                await self.stop_worker(worker)

                                # Wait for port to be properly released before restarting
                                logger.debug(
                                    f"Waiting for port {worker.port} to be released..."
                                )
                                port_available = await wait_for_port_free(
                                    worker.port, timeout=15
                                )
                                if not port_available:
                                    logger.error(
                                        f"Port {worker.port} still not available after 15s, skipping restart for {repo_name}"
                                    )
                                    continue

                                if self.start_worker(worker):
                                    worker.restart_count += 1
                                    logger.info(
                                        f"Restarted worker for {repo_name} (restart count: {worker.restart_count})"
                                    )
                                else:
                                    logger.error(
                                        f"Failed to restart worker for {repo_name}"
                                    )
                            else:
                                logger.error(
                                    f"Worker for {repo_name} exceeded max restarts ({worker.max_restarts})"
                                )

                    # Sleep in smaller chunks to allow for faster cancellation
                    sleep_remaining = 30  # 30 seconds total, 1 second chunks
                    while sleep_remaining > 0 and self.running:
                        await asyncio.sleep(1)
                        sleep_remaining -= 1

                except Exception as e:
                    logger.error(f"Error in worker monitoring: {e}")
                    await asyncio.sleep(5)
        finally:
            logger.debug("Worker monitoring task ending")

    def signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals"""
        signal_name = signal.Signals(signum).name
        logger.info(
            f"🚨 Received signal {signum} ({signal_name}), initiating graceful shutdown..."
        )

        # Set running to False and initiate shutdown
        self.running = False
        self.shutdown_coordinator.initiate_shutdown(f"signal_{signal_name}")

        # Wake up the main loop if it's waiting
        if hasattr(self, "loop") and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(lambda: None)  # Just wake up the loop
            except Exception as e:
                logger.debug(f"Could not wake up main loop: {e}")

    async def start(self) -> bool:
        """Start the master process"""
        logger.info("Starting MCP Master Process")

        # Store loop reference for signal handler
        self.loop = asyncio.get_running_loop()

        # Initialize validation registry
        initialize_validation_registry(logger)

        # Initialize repository indexes
        await self.initialize_repository_indexes()

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        # Start all workers
        self.running = True
        failed_workers = []

        for repo_name, worker in self.workers.items():
            if not self.start_worker(worker):
                failed_workers.append(repo_name)

        if failed_workers:
            logger.error(f"Failed to start workers for: {failed_workers}")

        # Start monitoring task
        monitor_task = asyncio.create_task(self.monitor_workers())

        # Log startup summary
        running_workers = [
            name
            for name, worker in self.workers.items()
            if self.is_worker_healthy(worker)
        ]
        logger.info(f"Master process started with {len(running_workers)} workers:")
        for repo_name, worker in self.workers.items():
            if repo_name in running_workers:
                logger.info(f"  - {repo_name}: http://localhost:{worker.port}/mcp/")

        # Wait for shutdown signal using shutdown manager
        logger.debug("About to wait for shutdown signal...")

        # Log system state before waiting
        log_system_state(logger, "MASTER_WAITING_FOR_SHUTDOWN")

        try:
            logger.debug("Waiting for shutdown signal...")

            # Wait for shutdown signal
            while self.running and not self.shutdown_coordinator.is_shutting_down():
                await asyncio.sleep(0.1)

            logger.info(
                "🛑 Shutdown signal received, beginning coordinated shutdown..."
            )
            logger.debug(
                f"Shutdown reason: {self.shutdown_coordinator.get_shutdown_reason()}"
            )
        except Exception as e:
            logger.error(f"Exception waiting for shutdown: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

        logger.info("Shutdown signal received, beginning graceful shutdown...")

        # Stop health monitoring FIRST to prevent worker restarts during shutdown
        logger.info("Step 1: Stopping health monitoring to prevent worker restarts...")
        try:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                logger.info("Health monitoring stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping health monitoring: {e}")
        except Exception as e:
            logger.error(f"Critical error stopping health monitoring: {e}")

        # Step 2: Stop all workers using new worker-controlled approach
        logger.info(
            "Step 2: Stopping all worker processes using worker-controlled shutdown..."
        )
        return await self.shutdown_all_workers()

    async def shutdown_all_workers(self) -> bool:
        """Shutdown all workers using new worker-controlled approach"""
        logger.info("Starting worker-controlled shutdown for all workers")

        if not self.workers:
            logger.info("No workers to shut down")
            return True

        # Shutdown all workers concurrently
        tasks = [self.shutdown_worker(worker) for worker in self.workers.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for result in results if result is True)
        total_count = len(self.workers)

        logger.info(
            f"Worker shutdown complete: {success_count}/{total_count} successful"
        )

        # Clean up symbol storage after all workers are shutdown
        try:
            logger.info("Closing master symbol storage...")
            self.symbol_storage.close()
            logger.info("✓ Symbol storage closed successfully")
        except Exception as e:
            logger.error(f"Error closing symbol storage: {e}")

        return success_count == total_count

    async def shutdown_worker(self, worker: WorkerProcess) -> bool:
        """Shutdown single worker using worker-controlled approach"""
        logger.info(f"Starting worker-controlled shutdown for {worker.repo_name}")

        if not worker.process or worker.process.poll() is not None:
            logger.info(f"Worker {worker.repo_name} already stopped")
            return True

        # Phase 1: Request graceful shutdown via HTTP
        shutdown_request_sent = False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://localhost:{worker.port}/shutdown",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if response.status == 200:
                        logger.info(f"Sent shutdown request to {worker.repo_name}")
                        shutdown_request_sent = True
                    else:
                        logger.warning(
                            f"Shutdown request failed for {worker.repo_name}: {response.status}"
                        )
        except Exception as e:
            logger.warning(
                f"Failed to send shutdown request to {worker.repo_name}: {e}"
            )

        # Skip graceful wait if shutdown request couldn't be sent
        if not shutdown_request_sent:
            logger.info(
                f"Skipping graceful wait for {worker.repo_name} since shutdown request failed"
            )
        else:
            # Phase 2: Wait for graceful exit (2 minutes)
            logger.info(f"Waiting for {worker.repo_name} to shut down gracefully...")
            start_time = time.time()
            timeout = 120  # 2 minutes

            while time.time() - start_time < timeout:
                # Check if process has exited
                if worker.process.poll() is not None:
                    # Verify port is released
                    if is_port_free(worker.port):
                        logger.info(f"✓ Worker {worker.repo_name} shut down gracefully")
                        worker.process = None
                        return True
                await asyncio.sleep(1)

        # Phase 3: SIGTERM escalation (only after timeout)
        logger.warning(
            f"Worker {worker.repo_name} didn't shutdown in {timeout}s, sending SIGTERM"
        )
        worker.process.terminate()

        try:
            await asyncio.wait_for(
                self._wait_for_process_exit(worker.process), timeout=30
            )
            logger.info(f"✓ Worker {worker.repo_name} terminated after SIGTERM")
            worker.process = None
            return True
        except TimeoutError:
            pass

        # Phase 4: SIGKILL (last resort)
        logger.error(f"Force killing worker {worker.repo_name}")
        if worker.process:
            worker.process.kill()
            await self._wait_for_process_exit(worker.process)
        worker.process = None
        return True

    async def _wait_for_process_exit(self, process: subprocess.Popen[bytes]) -> int:
        """Async wrapper for process.wait() with polling"""
        while True:
            if process.poll() is not None:
                return process.returncode
            await asyncio.sleep(0.1)  # Poll every 100ms

    async def _wait_for_port_release(self, port: int, timeout: float = 5.0) -> bool:
        """Wait for a port to be released after process termination"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if is_port_free(port):
                return True
            await asyncio.sleep(0.2)  # Check every 200ms
        return False

    def status(self) -> dict:
        """Get status of all workers"""
        status = {
            "master": {
                "running": self.running,
                "workers_count": len(self.workers),
                "config_path": "repositories.json",  # Default config path
            },
            "workers": {},
        }

        for repo_name, worker in self.workers.items():
            is_healthy = self.is_worker_healthy(worker)
            status["workers"][repo_name] = {
                "port": worker.repository_config.port,
                "path": worker.repository_config.path,
                "description": worker.repository_config.description,
                "running": is_healthy,
                "pid": worker.process.pid if worker.process else None,
                "start_time": worker.start_time,
                "restart_count": worker.restart_count,
                "endpoint": f"http://localhost:{worker.repository_config.port}/mcp/",
            }

        return status


async def main() -> None:
    """Main entry point"""
    config_path = "repositories.json"

    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "status":
            # Show status and exit
            try:
                # Create all components for status check
                repository_manager = RepositoryManager.create_from_config(config_path)

                workers = {}
                for repo_name, repo_config in repository_manager.repositories.items():
                    worker = WorkerProcess(repository_config=repo_config)
                    workers[repo_name] = worker

                symbol_storage = ProductionSymbolStorage.create_with_schema()
                symbol_extractor = PythonSymbolExtractor()
                indexer = PythonRepositoryIndexer(symbol_extractor, symbol_storage)
                startup_orchestrator = CodebaseStartupOrchestrator(
                    symbol_storage=symbol_storage,
                    symbol_extractor=symbol_extractor,
                    indexer=indexer,
                )

                # Create shutdown and health monitoring components
                shutdown_coordinator = SimpleShutdownCoordinator(logger)
                health_monitor = SimpleHealthMonitor(logger)
                health_monitor.start_monitoring()

                master = MCPMaster(
                    repository_manager=repository_manager,
                    workers=workers,
                    startup_orchestrator=startup_orchestrator,
                    symbol_storage=symbol_storage,
                    shutdown_coordinator=shutdown_coordinator,
                    health_monitor=health_monitor,
                )

                status = master.status()
                print(json.dumps(status, indent=2))
            except Exception as e:
                logger.error(f"Failed to create master: {e}")
                print("Failed to load configuration")
            return
        elif sys.argv[1] == "stop":
            # Stop all workers (TODO: implement proper shutdown)
            logger.info("Stop command not implemented yet")
            return

    # Create all MCP Master components
    try:
        logger.info("Creating MCP Master components...")

        # Create and configure repository manager
        repository_manager = RepositoryManager.create_from_config(config_path)

        logger.info(f"✅ Loaded {len(repository_manager.repositories)} repositories")

        # Create worker processes from repository configs
        workers = {}
        for repo_name, repo_config in repository_manager.repositories.items():
            worker = WorkerProcess(repository_config=repo_config)
            workers[repo_name] = worker
            logger.debug(f"✅ Created worker for repository: {repo_name}")

        # Create startup orchestrator components
        logger.info("Creating startup orchestrator components...")
        symbol_storage = ProductionSymbolStorage.create_with_schema()
        symbol_extractor = PythonSymbolExtractor()
        indexer = PythonRepositoryIndexer(symbol_extractor, symbol_storage)

        startup_orchestrator = CodebaseStartupOrchestrator(
            symbol_storage=symbol_storage,
            symbol_extractor=symbol_extractor,
            indexer=indexer,
        )

        # Create shutdown and health monitoring components
        shutdown_coordinator = SimpleShutdownCoordinator(logger)
        health_monitor = SimpleHealthMonitor(logger)
        health_monitor.start_monitoring()

        logger.info("✅ All components created successfully")

        master = MCPMaster(
            repository_manager=repository_manager,
            workers=workers,
            startup_orchestrator=startup_orchestrator,
            symbol_storage=symbol_storage,
            shutdown_coordinator=shutdown_coordinator,
            health_monitor=health_monitor,
        )

    except Exception as e:
        logger.error(f"Failed to create MCP Master: {e}")
        sys.exit(1)

    # Start master process
    try:
        await master.start()

        # Get final exit code from simplified shutdown coordinator
        exit_code = master.shutdown_coordinator.get_exit_code()
        logger.info(f"Master process exiting with code: {exit_code}")
        sys.exit(exit_code)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)  # Clean shutdown via signal
    except Exception as e:
        logger.error(f"Master process failed: {e}")
        sys.exit(1)  # Error exit code


if __name__ == "__main__":
    asyncio.run(main())
