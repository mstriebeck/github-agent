#!/usr/bin/env python3

"""
GitHub MCP Master Process - Multi-Port Architecture
Master process that spawns and monitors worker processes for each repository.

This master process:
- Reads repository configuration with port assignments
- Spawns worker processes for each repository on dedicated ports
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

# Import shutdown coordination components
from shutdown_manager import ShutdownManager
from system_utils import MicrosecondFormatter, log_system_state

# Configure logging with enhanced microsecond precision


log_dir = Path.home() / ".local" / "share" / "github-agent" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

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
        log_file_path = log_dir / "master.log"

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

    repo_name: str
    port: int
    path: str
    description: str
    process: subprocess.Popen[bytes] | None = None
    start_time: float | None = None
    restart_count: int = 0
    max_restarts: int = 5


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


class GitHubMCPMaster:
    """Master process for managing multiple MCP worker processes"""

    def __init__(self, config_path: str = "repositories.json"):
        self.config_path = config_path
        self.workers: dict[str, WorkerProcess] = {}
        self.running = False

        # Initialize shutdown coordination with our logger
        self.shutdown_manager = ShutdownManager(logger, mode="master")

        # Start health monitoring
        self.shutdown_manager._health_monitor.start_monitoring()

        # Use system-appropriate log location
        self.log_dir = Path.home() / ".local" / "share" / "github-agent" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def load_configuration(self) -> bool:
        """Load repository configuration from JSON file"""
        try:
            if not os.path.exists(self.config_path):
                logger.error(f"Configuration file {self.config_path} not found")
                return False

            with open(self.config_path) as f:
                config = json.load(f)

            repositories = config.get("repositories", {})
            if not repositories:
                logger.error("No repositories found in configuration")
                return False

            # Auto-assign ports if not specified
            next_port = 8081
            for repo_name, repo_config in repositories.items():
                if "port" not in repo_config:
                    repo_config["port"] = next_port
                    next_port += 1

                # Validate required fields
                if "path" not in repo_config:
                    logger.error(
                        f"Repository {repo_name} missing required 'path' field"
                    )
                    return False

                if not os.path.exists(repo_config["path"]):
                    logger.warning(
                        f"Repository path {repo_config['path']} does not exist"
                    )

                # Create worker process info
                worker = WorkerProcess(
                    repo_name=repo_name,
                    port=repo_config["port"],
                    path=repo_config["path"],
                    description=repo_config.get("description", repo_name),
                )
                self.workers[repo_name] = worker

            logger.info(f"Loaded configuration for {len(self.workers)} repositories")

            # Check for port conflicts
            ports_used = [w.port for w in self.workers.values()]
            if len(ports_used) != len(set(ports_used)):
                logger.error("Port conflicts detected in configuration")
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return False

    def save_configuration(self) -> None:
        """Save current configuration back to file (with auto-assigned ports)"""
        try:
            config: dict[str, Any] = {"repositories": {}}
            for repo_name, worker in self.workers.items():
                config["repositories"][repo_name] = {
                    "path": worker.path,
                    "port": worker.port,
                    "description": worker.description,
                }

            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=2)

            logger.info(f"Updated configuration saved to {self.config_path}")

        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")

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

            cmd = [
                python_executable,
                "github_mcp_worker.py",
                "--repo-name",
                worker.repo_name,
                "--repo-path",
                worker.path,
                "--port",
                str(worker.port),
                "--description",
                worker.description,
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
        """Handle shutdown signals using the shutdown manager"""
        signal_name = signal.Signals(signum).name
        logger.info(
            f"🚨 Received signal {signum} ({signal_name}), initiating graceful shutdown..."
        )

        # Set running to False and initiate shutdown
        self.running = False
        self.shutdown_manager.initiate_shutdown(f"signal_{signal_name}")

        # Wake up the main loop if it's waiting
        if hasattr(self, "loop") and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(lambda: None)  # Just wake up the loop
            except Exception as e:
                logger.debug(f"Could not wake up main loop: {e}")

    async def start(self) -> bool:
        """Start the master process"""
        logger.info("Starting GitHub MCP Master Process")

        # Store loop reference for signal handler
        self.loop = asyncio.get_running_loop()

        # Load configuration
        if not self.load_configuration():
            logger.error("Failed to load configuration, exiting")
            return False

        # Save configuration with auto-assigned ports
        self.save_configuration()

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
            while self.running and not self.shutdown_manager._shutdown_initiated:
                await asyncio.sleep(0.1)

            logger.info(
                "🛑 Shutdown signal received, beginning coordinated shutdown..."
            )
            logger.debug(
                f"Shutdown reason: {getattr(self.shutdown_manager, '_shutdown_reason', 'unknown')}"
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

        # Step 2: Stop all workers with our existing logic but enhanced with shutdown manager tracking
        logger.info(
            "Step 2: Stopping all worker processes with enhanced shutdown tracking..."
        )
        return await self._shutdown_workers_enhanced()

    async def _shutdown_workers_enhanced(self) -> bool:
        """Enhanced shutdown using shutdown manager for tracking and exit codes"""
        try:
            # Register ports with shutdown manager for verification
            ports_to_verify = []
            for worker in self.workers.values():
                if worker.process and self.is_worker_healthy(worker):
                    ports_to_verify.append(worker.port)

            async def stop_worker_gracefully(
                repo_name: str, worker: WorkerProcess
            ) -> bool:
                """Stop a single worker with shutdown manager tracking"""
                logger.info(f"Stopping worker {repo_name} with enhanced tracking")
                try:
                    if not worker.process or worker.process.poll() is not None:
                        logger.info(f"Worker {repo_name} already stopped")
                        return True

                    pid = worker.process.pid
                    logger.info(
                        f"Stopping worker {repo_name} (PID: {pid}) on port {worker.port}"
                    )

                    # Send SIGTERM for graceful shutdown
                    logger.info(f"Sending SIGTERM to worker {repo_name} (PID: {pid})")
                    worker.process.terminate()

                    # Wait for worker to shutdown gracefully
                    logger.info(
                        f"Waiting up to 3s for worker {repo_name} to stop gracefully..."
                    )
                    try:
                        await asyncio.wait_for(
                            self._wait_for_process_exit(worker.process), timeout=3
                        )
                        logger.info(f"Worker {repo_name} process exited gracefully")

                        # Wait for port to be actually free before considering worker stopped
                        logger.info(
                            f"Worker {repo_name} stopped gracefully, waiting for port {worker.port} to be released..."
                        )
                        port_free = await wait_for_port_free(worker.port, timeout=30)
                        if port_free:
                            logger.info(
                                f"Worker {repo_name} stopped gracefully - port {worker.port} is now available"
                            )
                        else:
                            logger.warning(
                                f"Worker {repo_name} stopped gracefully but port {worker.port} still not available after 30s"
                            )

                        worker.process = None
                        return True
                    except TimeoutError:
                        logger.warning(
                            f"Worker {repo_name} didn't stop gracefully within 3s, force killing"
                        )
                        self.shutdown_manager._exit_code_manager.report_timeout(
                            "worker_shutdown", 3.0
                        )

                        # Force kill
                        try:
                            logger.info(
                                f"Sending SIGKILL to worker {repo_name} (PID: {pid})"
                            )
                            if worker.process is not None:
                                worker.process.kill()
                                await asyncio.wait_for(
                                    self._wait_for_process_exit(worker.process),
                                    timeout=5,  # Increased timeout for SIGKILL
                                )
                            logger.info(f"Worker {repo_name} process terminated")

                            # Wait for port to be actually free before considering worker stopped
                            logger.info(
                                f"Worker {repo_name} force killed, waiting for port {worker.port} to be released..."
                            )
                            port_free = await wait_for_port_free(
                                worker.port, timeout=60
                            )
                            if port_free:
                                logger.info(
                                    f"Worker {repo_name} force killed successfully - port {worker.port} is now available"
                                )
                            else:
                                logger.warning(
                                    f"Worker {repo_name} force killed but port {worker.port} still not available after 60s"
                                )

                            self.shutdown_manager._exit_code_manager.report_force_action(
                                "kill", f"worker {repo_name}"
                            )
                            worker.process = None
                            return True
                        except TimeoutError:
                            logger.error(
                                f"Worker {repo_name} couldn't be killed even with SIGKILL"
                            )
                            self.shutdown_manager._exit_code_manager.report_verification_failure(
                                "zombie_check",
                                f"Worker {repo_name} (PID: {pid}) may be zombie",
                            )
                            worker.process = None
                            return False
                        except Exception as e:
                            logger.error(f"Error force killing worker {repo_name}: {e}")
                            self.shutdown_manager._exit_code_manager.report_system_error(
                                "worker_manager", e
                            )
                            worker.process = None
                            return False

                except Exception as e:
                    logger.error(f"Exception stopping worker {repo_name}: {e}")
                    self.shutdown_manager._exit_code_manager.report_system_error(
                        "worker_manager", e
                    )
                    if worker.process:
                        try:
                            worker.process.kill()
                            worker.process = None
                        except Exception:
                            pass
                    return False

            # Stop all workers concurrently
            if not self.workers:
                logger.info("No workers to stop")
            else:
                logger.info(f"Stopping {len(self.workers)} workers concurrently...")
                stop_tasks = [
                    stop_worker_gracefully(repo_name, worker)
                    for repo_name, worker in self.workers.items()
                ]

                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*stop_tasks, return_exceptions=True),
                        timeout=150,  # Increased to allow for port cleanup (60s per worker + buffer)
                    )

                    successful_stops = sum(1 for r in results if r is True)
                    failed_stops = len(self.workers) - successful_stops
                    logger.info(
                        f"Worker stop results: {successful_stops} successful, {failed_stops} failed"
                    )

                except TimeoutError:
                    logger.error("Overall worker shutdown timeout after 150s")
                    self.shutdown_manager._exit_code_manager.report_timeout(
                        "worker_shutdown", 150.0
                    )

                    # Emergency cleanup
                    for _repo_name, worker in self.workers.items():
                        if worker.process:
                            try:
                                worker.process.kill()
                                worker.process = None
                            except Exception as e:
                                logger.warning(
                                    f"Failed to kill worker process for {worker.repo_name}: {e}"
                                )

            # Ports will be verified by deployment script if needed
            logger.info("Workers shutdown process completed")

            # Get final exit code and determine success
            exit_code = self.shutdown_manager._exit_code_manager.determine_exit_code(
                "graceful"
            )
            logger.info(f"Final shutdown exit code: {exit_code} ({exit_code.name})")

            # Success if exit code indicates clean shutdown
            from exit_codes import ShutdownExitCode

            success = exit_code in [
                ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN,
                ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN,
            ]

            if success:
                logger.info("Enhanced worker shutdown completed successfully")
            else:
                logger.warning(
                    f"Enhanced worker shutdown completed with issues: {exit_code.name}"
                )

            # Stop health monitoring
            self.shutdown_manager._health_monitor.stop_monitoring()
            self.shutdown_manager._health_monitor.cleanup_health_file()

            return success

        except Exception as e:
            logger.error(f"Critical error in enhanced worker shutdown: {e}")
            self.shutdown_manager._exit_code_manager.report_system_error(
                "shutdown_coordinator", e
            )
            return False

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
                "config_path": self.config_path,
            },
            "workers": {},
        }

        for repo_name, worker in self.workers.items():
            is_healthy = self.is_worker_healthy(worker)
            status["workers"][repo_name] = {
                "port": worker.port,
                "path": worker.path,
                "description": worker.description,
                "running": is_healthy,
                "pid": worker.process.pid if worker.process else None,
                "start_time": worker.start_time,
                "restart_count": worker.restart_count,
                "endpoint": f"http://localhost:{worker.port}/mcp/",
            }

        return status


async def main() -> None:
    """Main entry point"""
    master = GitHubMCPMaster()

    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "status":
            # Show status and exit
            if master.load_configuration():
                status = master.status()
                print(json.dumps(status, indent=2))
            else:
                print("Failed to load configuration")
            return
        elif sys.argv[1] == "stop":
            # Stop all workers (TODO: implement proper shutdown)
            logger.info("Stop command not implemented yet")
            return

    # Start master process
    try:
        await master.start()

        # Get final exit code from shutdown manager
        exit_code = master.shutdown_manager._exit_code_manager.determine_exit_code(
            "main"
        )
        logger.info(f"Master process exiting with code: {exit_code} ({exit_code.name})")
        sys.exit(exit_code.value)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        exit_code = master.shutdown_manager._exit_code_manager.determine_exit_code(
            "SIGINT"
        )
        sys.exit(exit_code.value)
    except Exception as e:
        logger.error(f"Master process failed: {e}")
        master.shutdown_manager._exit_code_manager.report_system_error(
            "master_process", e
        )
        exit_code = master.shutdown_manager._exit_code_manager.determine_exit_code(
            "error"
        )
        sys.exit(exit_code.value)


if __name__ == "__main__":
    asyncio.run(main())
