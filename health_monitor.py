"""
Health monitoring interface for MCP server shutdown verification.

Provides external monitoring capabilities for process managers and monitoring
systems to verify server status and shutdown progress.
"""

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import psutil


class ServerStatus(Enum):
    """Server status states."""

    STARTING = "starting"
    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"
    ERROR = "error"


class ShutdownPhase(Enum):
    """Shutdown phase tracking."""

    NOT_STARTED = "not_started"
    WORKERS_STOPPING = "workers_stopping"
    CLIENTS_DISCONNECTING = "clients_disconnecting"
    RESOURCES_CLEANING = "resources_cleaning"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class WorkerStatus:
    """Status of a worker process."""

    worker_id: str
    pid: int | None
    port: int
    status: str  # "running", "stopping", "stopped", "error"
    last_seen: datetime
    shutdown_requested: bool = False
    shutdown_completed: bool = False


@dataclass
class ClientStatus:
    """Status of a client connection."""

    client_id: str
    worker_id: str
    connected_at: datetime
    last_activity: datetime
    disconnect_requested: bool = False
    disconnected: bool = False


@dataclass
class ResourceStatus:
    """Status of system resources."""

    open_files: int
    open_connections: int
    database_connections: int
    memory_usage_mb: float
    cleanup_requested: bool = False
    cleanup_completed: bool = False


@dataclass
class HealthReport:
    """Complete health report of the server."""

    timestamp: datetime
    server_status: ServerStatus
    shutdown_phase: ShutdownPhase
    pid: int
    uptime_seconds: float
    workers: list[WorkerStatus]
    clients: list[ClientStatus]
    resources: ResourceStatus
    shutdown_progress: dict[str, Any]
    errors: list[str]
    warnings: list[str]


class HealthMonitor:
    """External health monitoring interface for the MCP server."""

    def __init__(self, logger, health_file_path: str = "/tmp/mcp_server_health.json"):
        self.logger = logger
        self.health_file_path = Path(health_file_path)
        self._status = ServerStatus.STARTING
        self._shutdown_phase = ShutdownPhase.NOT_STARTED
        self._start_time = datetime.now()
        self._workers: dict[str, WorkerStatus] = {}
        self._clients: dict[str, ClientStatus] = {}
        self._resources = ResourceStatus(0, 0, 0, 0.0)
        self._errors: list[str] = []
        self._warnings: list[str] = []
        self._shutdown_progress: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._monitoring_thread: threading.Thread | None = None
        self._should_monitor = True

        # Create health file directory
        self.health_file_path.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            f"Health monitor initialized, writing to {self.health_file_path}"
        )

    def start_monitoring(self):
        """Start the health monitoring thread."""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            self.logger.warning("Health monitoring already running")
            return

        self._should_monitor = True
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_loop, name="HealthMonitor", daemon=True
        )
        self._monitoring_thread.start()
        self.logger.info("Health monitoring thread started")

    def _monitoring_loop(self):
        """Main monitoring loop that runs in the background thread."""
        import time

        while self._should_monitor:
            try:
                # Update health status periodically
                self._update_health_file()
                time.sleep(1.0)  # Update every second
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(1.0)

    def stop_monitoring(self):
        """Stop the health monitoring thread."""
        self._should_monitor = False
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            self._monitoring_thread.join(timeout=2.0)
            if self._monitoring_thread.is_alive():
                self.logger.warning("Health monitoring thread did not stop gracefully")
            else:
                self.logger.info("Health monitoring thread stopped")

    def _update_health_file(self):
        """Update the health status file."""
        try:
            report = self._generate_health_report()

            # Write atomically by writing to temp file then moving
            temp_file = self.health_file_path.with_suffix(".tmp")

            try:
                # Ensure parent directory exists
                temp_file.parent.mkdir(parents=True, exist_ok=True)

                with open(temp_file, "w") as f:
                    json.dump(asdict(report), f, indent=2, default=str)

                # Verify temp file exists before moving
                if not temp_file.exists():
                    raise FileNotFoundError(
                        f"Temporary file was not created: {temp_file}"
                    )

                temp_file.replace(self.health_file_path)

            except Exception as write_error:
                # Clean up temp file if it exists
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to remove temp file {temp_file}: {e}"
                        )
                raise write_error

        except Exception as e:
            self.logger.error(f"Failed to update health file: {e}")
            # Fallback: try direct write without atomic operation
            try:
                self.logger.info("Attempting direct health file write as fallback")
                report = self._generate_health_report()
                with open(self.health_file_path, "w") as f:
                    json.dump(asdict(report), f, indent=2, default=str)
                self.logger.info("Direct health file write succeeded")
            except Exception as fallback_error:
                self.logger.error(
                    f"Fallback health file write also failed: {fallback_error}"
                )

    def _generate_health_report(self) -> HealthReport:
        """Generate a complete health report."""
        with self._lock:
            try:
                # Update resource status from system
                self._update_resource_status()

                return HealthReport(
                    timestamp=datetime.now(),
                    server_status=self._status,
                    shutdown_phase=self._shutdown_phase,
                    pid=os.getpid(),
                    uptime_seconds=(datetime.now() - self._start_time).total_seconds(),
                    workers=list(self._workers.values()),
                    clients=list(self._clients.values()),
                    resources=self._resources,
                    shutdown_progress=self._shutdown_progress.copy(),
                    errors=self._errors.copy(),
                    warnings=self._warnings.copy(),
                )
            except Exception as e:
                self.logger.error(f"Error generating health report: {e}")
                return HealthReport(
                    timestamp=datetime.now(),
                    server_status=ServerStatus.ERROR,
                    shutdown_phase=self._shutdown_phase,
                    pid=os.getpid(),
                    uptime_seconds=0,
                    workers=[],
                    clients=[],
                    resources=ResourceStatus(0, 0, 0, 0.0),
                    shutdown_progress={},
                    errors=[f"Health report generation failed: {e}"],
                    warnings=[],
                )

    def _update_resource_status(self):
        """Update resource status from system information."""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()

            self._resources.open_files = len(process.open_files())
            self._resources.open_connections = len(process.net_connections())
            self._resources.memory_usage_mb = memory_info.rss / 1024 / 1024

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Could not update resource status: {e}")

    # Status update methods
    def set_server_status(self, status: ServerStatus):
        """Update server status."""
        with self._lock:
            old_status = self._status
            self._status = status
            self.logger.info(
                f"Server status changed: {old_status.value} -> {status.value}"
            )

    def set_shutdown_phase(self, phase: ShutdownPhase):
        """Update shutdown phase."""
        with self._lock:
            old_phase = self._shutdown_phase
            self._shutdown_phase = phase
            self.logger.info(
                f"Shutdown phase changed: {old_phase.value} -> {phase.value}"
            )

    def update_worker_status(
        self, worker_id: str, pid: int | None, port: int, status: str
    ):
        """Update worker process status."""
        with self._lock:
            if worker_id not in self._workers:
                self._workers[worker_id] = WorkerStatus(
                    worker_id=worker_id,
                    pid=pid,
                    port=port,
                    status=status,
                    last_seen=datetime.now(),
                )
            else:
                worker = self._workers[worker_id]
                worker.pid = pid
                worker.status = status
                worker.last_seen = datetime.now()

            self.logger.debug(f"Worker {worker_id} status updated: {status}")

    def set_worker_shutdown_requested(self, worker_id: str):
        """Mark that shutdown was requested for a worker."""
        with self._lock:
            if worker_id in self._workers:
                self._workers[worker_id].shutdown_requested = True
                self.logger.debug(f"Worker {worker_id} shutdown requested")

    def set_worker_shutdown_completed(self, worker_id: str):
        """Mark that shutdown completed for a worker."""
        with self._lock:
            if worker_id in self._workers:
                self._workers[worker_id].shutdown_completed = True
                self._workers[worker_id].status = "stopped"
                self.logger.debug(f"Worker {worker_id} shutdown completed")

    def add_client(self, client_id: str, worker_id: str):
        """Add a client connection."""
        with self._lock:
            self._clients[client_id] = ClientStatus(
                client_id=client_id,
                worker_id=worker_id,
                connected_at=datetime.now(),
                last_activity=datetime.now(),
            )
            self.logger.debug(f"Client {client_id} connected to worker {worker_id}")

    def update_client_activity(self, client_id: str):
        """Update client last activity time."""
        with self._lock:
            if client_id in self._clients:
                self._clients[client_id].last_activity = datetime.now()

    def set_client_disconnect_requested(self, client_id: str):
        """Mark that disconnect was requested for a client."""
        with self._lock:
            if client_id in self._clients:
                self._clients[client_id].disconnect_requested = True
                self.logger.debug(f"Client {client_id} disconnect requested")

    def set_client_disconnected(self, client_id: str):
        """Mark that a client disconnected."""
        with self._lock:
            if client_id in self._clients:
                self._clients[client_id].disconnected = True
                self.logger.debug(f"Client {client_id} disconnected")

    def remove_client(self, client_id: str):
        """Remove a client from tracking."""
        with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
                self.logger.debug(f"Client {client_id} removed from tracking")

    def set_resource_cleanup_requested(self):
        """Mark that resource cleanup was requested."""
        with self._lock:
            self._resources.cleanup_requested = True
            self.logger.debug("Resource cleanup requested")

    def set_resource_cleanup_completed(self):
        """Mark that resource cleanup completed."""
        with self._lock:
            self._resources.cleanup_completed = True
            self.logger.debug("Resource cleanup completed")

    def update_shutdown_progress(self, phase: str, progress: dict[str, Any]):
        """Update shutdown progress information."""
        with self._lock:
            self._shutdown_progress[phase] = {**progress, "timestamp": datetime.now()}
            self.logger.debug(f"Shutdown progress updated for {phase}: {progress}")

    def add_error(self, error: str):
        """Add an error to the health report."""
        with self._lock:
            timestamp = datetime.now().isoformat()
            self._errors.append(f"[{timestamp}] {error}")
            # Keep only last 20 errors
            self._errors = self._errors[-20:]
            self.logger.error(f"Health monitor recorded error: {error}")

    def add_warning(self, warning: str):
        """Add a warning to the health report."""
        with self._lock:
            timestamp = datetime.now().isoformat()
            self._warnings.append(f"[{timestamp}] {warning}")
            # Keep only last 20 warnings
            self._warnings = self._warnings[-20:]
            self.logger.warning(f"Health monitor recorded warning: {warning}")

    def get_current_status(self) -> dict[str, Any]:
        """Get current status for immediate use."""
        with self._lock:
            return {
                "server_status": self._status.value,
                "shutdown_phase": self._shutdown_phase.value,
                "workers_count": len(self._workers),
                "clients_count": len(self._clients),
                "errors_count": len(self._errors),
                "warnings_count": len(self._warnings),
                "uptime_seconds": (datetime.now() - self._start_time).total_seconds(),
            }

    def is_shutdown_complete(self) -> bool:
        """Check if shutdown is complete."""
        with self._lock:
            return self._shutdown_phase in [
                ShutdownPhase.COMPLETED,
                ShutdownPhase.FAILED,
            ]

    def get_stuck_workers(self, timeout_seconds: float = 30.0) -> list[str]:
        """Get list of workers that appear to be stuck during shutdown."""
        with self._lock:
            stuck_workers = []
            cutoff_time = datetime.now() - timedelta(seconds=timeout_seconds)

            for worker_id, worker in self._workers.items():
                if (
                    worker.shutdown_requested
                    and not worker.shutdown_completed
                    and worker.last_seen < cutoff_time
                ):
                    stuck_workers.append(worker_id)

            return stuck_workers

    def cleanup_health_file(self):
        """Remove the health file (call during final cleanup)."""
        try:
            if self.health_file_path.exists():
                self.health_file_path.unlink()
                self.logger.info("Health file cleaned up")
        except Exception as e:
            self.logger.error(f"Failed to cleanup health file: {e}")


def read_health_status(
    health_file_path: str = "/tmp/mcp_server_health.json",
) -> dict[str, Any] | None:
    """Read health status from file (for external monitoring)."""
    try:
        with open(health_file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return {"error": "Invalid health file format"}
    except Exception as e:
        return {"error": f"Failed to read health file: {e}"}


def isServerHealthy(
    health_file_path: str = "/tmp/mcp_server_health.json", max_age_seconds: float = 10.0
) -> bool:
    """Check if server is healthy based on health file."""
    health = read_health_status(health_file_path)
    if not health:
        return False

    try:
        # Check if health report is recent
        timestamp = datetime.fromisoformat(health["timestamp"])
        age = (datetime.now() - timestamp).total_seconds()
        if age > max_age_seconds:
            return False

        # Check server status
        status = health.get("server_status")
        return status in ["running", "starting"]

    except Exception:
        return False
