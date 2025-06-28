"""
Enhanced Worker Process Management

This module provides enhanced worker process management with process groups,
graceful shutdown protocols, and comprehensive verification.
"""

import asyncio
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime

import aiohttp
import psutil

from shutdown_core import IProcessSpawner, RealProcessSpawner
from system_utils import log_system_state


@dataclass
class WorkerProcess:
    """Enhanced information about a worker process"""

    repo_name: str
    port: int
    path: str
    description: str
    process: subprocess.Popen | None = None
    start_time: float | None = None
    restart_count: int = 0
    max_restarts: int = 5
    shutdown_timeout: float = 30.0
    graceful_timeout: float = 10.0


class WorkerManager:
    """Enhanced worker process manager with process groups and comprehensive shutdown"""

    def __init__(self, logger, process_spawner: IProcessSpawner | None = None):
        self.workers: dict[str, WorkerProcess] = {}
        self.logger = logger  # Central logger passed in
        self.process_spawner = process_spawner or RealProcessSpawner()

        # Support timeout override via environment variables
        self.default_worker_timeout = float(
            os.getenv("MCP_SHUTDOWN_WORKER_TIMEOUT", "30")
        )
        self.default_graceful_timeout = float(
            os.getenv("MCP_WORKER_GRACEFUL_TIMEOUT", "10")
        )
        self.logger.debug(
            f"Worker timeouts - graceful: {self.default_graceful_timeout}s, total: {self.default_worker_timeout}s"
        )

    def add_worker(self, worker: WorkerProcess) -> None:
        """Add a worker to the manager"""
        # Apply default timeouts if not set
        if worker.shutdown_timeout == 30.0:  # Default value
            worker.shutdown_timeout = self.default_worker_timeout
        if worker.graceful_timeout == 10.0:  # Default value
            worker.graceful_timeout = self.default_graceful_timeout

        self.workers[worker.repo_name] = worker
        self.logger.info(
            f"Added worker {worker.repo_name} to manager (port: {worker.port})"
        )

    def remove_worker(self, repo_name: str) -> WorkerProcess | None:
        """Remove a worker from the manager"""
        worker = self.workers.pop(repo_name, None)
        if worker:
            self.logger.info(f"Removed worker {repo_name} from manager")
        return worker

    def get_worker(self, repo_name: str) -> WorkerProcess | None:
        """Get a worker by name"""
        return self.workers.get(repo_name)

    def start_worker(
        self, worker: WorkerProcess, command: list[str], env: dict | None = None
    ) -> bool:
        """Start worker with process group for better process management (macOS/Linux compatible)"""
        start_time = datetime.now()
        self.logger.info(
            f"Starting worker on port {worker.port} for {worker.repo_name}"
        )

        try:
            # Check if port is available before starting
            if not self._is_port_available(worker.port):
                self.logger.error(
                    f"Port {worker.port} is not available for {worker.repo_name}"
                )
                return False

            # On Unix-like systems (macOS, Linux), os.setsid creates a new session and process group.
            # This ensures that killing the parent process group (MCP server) will also kill the worker
            # and any children it spawns, preventing orphaned processes.
            process = self.process_spawner.spawn_process(
                command,
                preexec_fn=os.setsid,  # Create new process group
            )

            worker.process = process
            worker.start_time = time.time()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            self.logger.info(
                f"Worker started for {worker.repo_name} on port {worker.port} with PID {process.pid} in {duration:.2f}ms"
            )

            # Log system state after worker start
            log_system_state(self.logger, f"WORKER_{worker.repo_name.upper()}_STARTED")

            return True

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds() * 1000
            self.logger.error(
                f"Failed to start worker for {worker.repo_name} on port {worker.port} after {duration:.2f}ms: {e}"
            )
            return False

    async def shutdown_all_workers(self) -> bool:
        """Shutdown all workers with escalating force"""
        shutdown_start = datetime.now()
        worker_count = len(self.workers)

        if worker_count == 0:
            self.logger.info("No workers to shutdown")
            return True

        self.logger.info(f"Starting shutdown of {worker_count} workers")
        self.logger.debug(f"Worker ports: {list(self.workers.keys())}")

        # Log system state before shutdown
        log_system_state(self.logger, "WORKERS_SHUTDOWN_STARTING")

        successful_shutdowns = 0
        failed_workers = []

        # Create shutdown tasks for all workers
        shutdown_tasks = []
        for i, (repo_name, worker) in enumerate(list(self.workers.items())):
            task = self._shutdown_single_worker_async(
                repo_name, worker, i + 1, worker_count
            )
            shutdown_tasks.append(task)

        # Execute all shutdowns concurrently with individual timeout handling
        results = await asyncio.gather(*shutdown_tasks, return_exceptions=True)

        # Process results
        for _i, (repo_name, result) in enumerate(
            zip(self.workers.keys(), results, strict=False)
        ):
            if isinstance(result, Exception):
                self.logger.error(
                    f"Exception during worker {repo_name} shutdown: {result}"
                )
                failed_workers.append(repo_name)
            elif result:
                successful_shutdowns += 1
            else:
                failed_workers.append(repo_name)

        total_duration = (datetime.now() - shutdown_start).total_seconds()
        self.logger.info(
            f"Worker shutdown completed: {successful_shutdowns}/{worker_count} successful in {total_duration:.3f}s"
        )

        if failed_workers:
            self.logger.warning(f"Failed worker shutdowns: {failed_workers}")

        # Clear worker registry
        self.workers.clear()
        self.logger.debug("Worker registry cleared")

        # Log final system state
        log_system_state(self.logger, "WORKERS_SHUTDOWN_COMPLETED")

        return len(failed_workers) == 0

    async def _shutdown_single_worker_async(
        self, repo_name: str, worker: WorkerProcess, worker_num: int, total_workers: int
    ) -> bool:
        """Enhanced worker shutdown with graceful protocol and process group handling"""
        start_time = datetime.now()
        self.logger.info(
            f"Starting enhanced shutdown sequence for worker {worker_num}/{total_workers}: {repo_name} (PID: {worker.process.pid if worker.process else 'None'})"
        )

        try:
            if (
                not worker.process
                or self.process_spawner.get_process_poll_status(worker.process)
                is not None
            ):
                self.logger.info(f"Worker {repo_name} already stopped")
                return True

            # Pre-shutdown state logging
            self.logger.debug(
                f"Worker process state - PID: {worker.process.pid}, Poll: {self.process_spawner.get_process_poll_status(worker.process)}"
            )

            # Phase 1: Attempt graceful shutdown via HTTP/IPC
            graceful_start = datetime.now()
            self.logger.debug(
                f"Phase 1: Requesting graceful shutdown for worker {repo_name} on port {worker.port}"
            )

            try:
                await self._send_worker_shutdown_request(worker.port)
                self.logger.debug(
                    f"Shutdown request sent to worker {repo_name} on port {worker.port}"
                )

                # Wait for graceful shutdown
                try:
                    await asyncio.wait_for(
                        self._wait_for_process_exit_async(worker.process),
                        timeout=worker.graceful_timeout,
                    )
                    graceful_duration = (
                        datetime.now() - graceful_start
                    ).total_seconds()
                    self.logger.info(
                        f"Worker {repo_name} shut down gracefully in {graceful_duration:.3f}s"
                    )
                    await self._comprehensive_worker_verification(worker)
                    return True
                except TimeoutError:
                    graceful_duration = (
                        datetime.now() - graceful_start
                    ).total_seconds()
                    self.logger.info(
                        f"Worker {repo_name} didn't respond to graceful shutdown after {graceful_duration:.3f}s"
                    )

            except Exception as e:
                graceful_duration = (datetime.now() - graceful_start).total_seconds()
                self.logger.debug(
                    f"Graceful shutdown request failed for {repo_name} port {worker.port} after {graceful_duration:.3f}s: {e}"
                )

            # Phase 2: SIGTERM if still running
            if self.process_spawner.get_process_poll_status(worker.process) is None:
                sigterm_start = datetime.now()
                self.logger.debug(
                    f"Phase 2: Sending SIGTERM to worker {worker.process.pid}"
                )
                self.process_spawner.terminate_process(worker.process)

                # Wait with timeout
                remaining_timeout = worker.shutdown_timeout - worker.graceful_timeout
                try:
                    await asyncio.wait_for(
                        self._wait_for_process_exit_async(worker.process),
                        timeout=remaining_timeout,
                    )
                    elapsed = (datetime.now() - sigterm_start).total_seconds()
                    self.logger.info(
                        f"Worker {repo_name} terminated gracefully after {elapsed:.3f}s"
                    )
                except TimeoutError:
                    elapsed = (datetime.now() - sigterm_start).total_seconds()
                    self.logger.warning(
                        f"Worker {repo_name} didn't respond to SIGTERM after {elapsed:.3f}s"
                    )

            # Phase 3: SIGKILL if still running
            if self.process_spawner.get_process_poll_status(worker.process) is None:
                sigkill_start = datetime.now()
                self.logger.warning(
                    f"Phase 3: Escalating to SIGKILL for worker {repo_name}"
                )

                # Try to kill the entire process group first
                try:
                    self.process_spawner.kill_process_group(worker.process.pid)
                    self.logger.debug(
                        f"Sent SIGKILL to process group for worker {worker.process.pid}"
                    )
                except (ProcessLookupError, PermissionError) as e:
                    self.logger.debug(
                        f"Process group kill failed for worker {worker.process.pid}: {e}"
                    )
                    # Fall back to single process kill
                    worker.process.kill()

                # Wait for final termination
                await asyncio.wait_for(
                    self._wait_for_process_exit_async(worker.process),
                    timeout=5.0,  # Hard timeout for SIGKILL
                )
                kill_duration = (datetime.now() - sigkill_start).total_seconds()
                self.logger.info(
                    f"Worker {repo_name} force-killed successfully in {kill_duration:.3f}s"
                )

        except Exception as e:
            error_duration = (datetime.now() - start_time).total_seconds()
            self.logger.error(
                f"Exception during worker {repo_name} shutdown after {error_duration:.3f}s: {e}",
                exc_info=True,
            )
            return False

        # Post-shutdown verification
        verification_start = datetime.now()
        await self._comprehensive_worker_verification(worker)
        verification_duration = (datetime.now() - verification_start).total_seconds()

        total_duration = (datetime.now() - start_time).total_seconds()
        self.logger.debug(
            f"Worker {repo_name} total shutdown time: {total_duration:.3f}s (verification: {verification_duration:.3f}s)"
        )

        return True

    async def _send_worker_shutdown_request(self, port: int):
        """Send HTTP shutdown request to worker"""
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                shutdown_url = f"http://localhost:{port}/shutdown"
                async with session.post(shutdown_url) as response:
                    self.logger.debug(
                        f"Shutdown request successful for port {port}: {response.status}"
                    )
        except Exception as e:
            # Expected if worker doesn't support HTTP shutdown or is already down
            self.logger.debug(f"HTTP shutdown request failed for port {port}: {e}")
            raise

    async def _wait_for_process_exit_async(self, process: subprocess.Popen):
        """Async wrapper for waiting for process exit"""
        while self.process_spawner.get_process_poll_status(process) is None:
            await asyncio.sleep(0.1)

    async def _comprehensive_worker_verification(self, worker: WorkerProcess):
        """Enhanced post-shutdown verification"""
        verification_start = datetime.now()
        self.logger.debug(f"Starting comprehensive verification for {worker.repo_name}")

        # 1. Process state verification
        if worker.process:
            final_poll = self.process_spawner.get_process_poll_status(worker.process)
            if final_poll is None:
                self.logger.error(
                    f"CRITICAL: Worker process {worker.process.pid} still running after shutdown!"
                )
            else:
                self.logger.debug(
                    f"✓ Process verification passed: worker exited with code {final_poll}"
                )

        # 2. Enhanced port release verification
        port_start = datetime.now()
        port_released = await self._verify_port_release_async(worker.port)
        port_duration = (datetime.now() - port_start).total_seconds()

        # 3. Process cleanup verification (check for zombies)
        if worker.process:
            zombie_start = datetime.now()
            await self._verify_no_zombie_processes_async(worker.process.pid)
            zombie_duration = (datetime.now() - zombie_start).total_seconds()
        else:
            zombie_duration = 0

        verification_status = "PASSED" if port_released else "FAILED"
        total_verification = (datetime.now() - verification_start).total_seconds()

        self.logger.info(
            f"Worker {worker.repo_name} verification: {verification_status} "
            f"(total: {total_verification:.3f}s, port: {port_duration:.3f}s, "
            f"zombie: {zombie_duration:.3f}s)"
        )

    async def _verify_port_release_async(
        self, port: int, timeout: float = 15.0
    ) -> bool:
        """Enhanced port verification using binding test"""
        start_time = datetime.now()
        self.logger.debug(f"Verifying port {port} release...")

        while (datetime.now() - start_time).total_seconds() < timeout:
            check_start = datetime.now()
            port_available = self._is_port_available(port)
            check_duration = (datetime.now() - check_start).total_seconds() * 1000

            if port_available:
                elapsed = (datetime.now() - start_time).total_seconds()
                self.logger.info(
                    f"✓ Port {port} successfully released after {elapsed:.3f}s"
                )
                return True

            elapsed = (datetime.now() - start_time).total_seconds()
            self.logger.debug(
                f"Port {port} still in use after {elapsed:.3f}s (check took {check_duration:.2f}ms), continuing..."
            )
            await asyncio.sleep(0.5)

        elapsed = (datetime.now() - start_time).total_seconds()
        self.logger.error(f"✗ CRITICAL: Port {port} still in use after {elapsed:.3f}s")
        await self._diagnose_port_issue_async(port)
        return False

    def _is_port_available(self, port: int) -> bool:
        """Test if port is available by attempting to bind to it"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("", port))
                return True
        except OSError as e:
            if "Address already in use" in str(e):
                return False
            else:
                self.logger.error(f"Error checking port {port} availability: {e}")
                return False
        except Exception as e:
            self.logger.error(
                f"Unexpected error in _is_port_available for port {port}: {e}"
            )
            return False

    async def _diagnose_port_issue_async(self, port: int):
        """Attempt to diagnose why a port is still in use"""
        self.logger.warning(f"Attempting to diagnose port {port} issue:")
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr and conn.laddr.port == port:
                    self.logger.warning(
                        f"  Port {port} is held by PID {conn.pid}, status: {conn.status}, family: {conn.family.name}, type: {conn.type.name}"
                    )
                    try:
                        proc = psutil.Process(conn.pid)
                        self.logger.warning(
                            f"    Process details: Name={proc.name()}, Cmdline={' '.join(proc.cmdline())}"
                        )
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        self.logger.warning(
                            f"    Cannot access process {conn.pid} details: {e}"
                        )
        except Exception as e:
            self.logger.error(f"Error diagnosing port {port}: {e}")

    async def _verify_no_zombie_processes_async(self, initial_pid: int):
        """Verify that no zombie processes remain for the given PID's children"""
        try:
            parent = psutil.Process(initial_pid)
            children = parent.children(recursive=True)
            zombies = [
                child for child in children if child.status() == psutil.STATUS_ZOMBIE
            ]
            if zombies:
                self.logger.error(
                    f"CRITICAL: Found zombie processes related to PID {initial_pid}: {zombies}"
                )
                # Attempt to wait on them to clear them
                for zombie in zombies:
                    try:
                        os.waitpid(zombie.pid, os.WNOHANG)
                        self.logger.debug(f"Attempted to reap zombie {zombie.pid}")
                    except ChildProcessError:
                        self.logger.debug(
                            f"Zombie {zombie.pid} already reaped or not a direct child."
                        )
            else:
                self.logger.debug(
                    f"✓ No zombie processes found for PID {initial_pid} and its descendants."
                )
        except psutil.NoSuchProcess:
            self.logger.debug(
                f"Parent process {initial_pid} already gone, cannot check for zombies."
            )
        except Exception as e:
            self.logger.error(
                f"Error verifying zombie processes for PID {initial_pid}: {e}"
            )

    def is_worker_healthy(self, worker: WorkerProcess) -> bool:
        """Check if a worker is healthy (process running and port responsive)"""
        if not worker.process:
            return False

        # Check if process is still running
        if self.process_spawner.get_process_poll_status(worker.process) is not None:
            return False

        # Optionally check if port is responsive (basic check)
        return not self._is_port_available(
            worker.port
        )  # Port should NOT be available if worker is running

    def get_worker_count(self) -> int:
        """Get the number of managed workers"""
        return len(self.workers)

    def get_healthy_worker_count(self) -> int:
        """Get the number of healthy workers"""
        return sum(
            1 for worker in self.workers.values() if self.is_worker_healthy(worker)
        )

    def get_worker_status(self) -> dict[str, dict]:
        """Get status information for all workers"""
        status = {}
        for repo_name, worker in self.workers.items():
            status[repo_name] = {
                "port": worker.port,
                "healthy": self.is_worker_healthy(worker),
                "pid": worker.process.pid if worker.process else None,
                "start_time": worker.start_time,
                "restart_count": worker.restart_count,
            }
        return status
