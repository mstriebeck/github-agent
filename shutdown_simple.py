"""
Simplified Shutdown Coordination
Simple, clean shutdown coordination without unnecessary complexity.
"""

import signal
import threading
from typing import Any


class ExitCodes:
    """Exit codes for monitoring and debugging"""

    SUCCESS = 0  # Clean shutdown
    GRACEFUL_TIMEOUT = 1  # Graceful shutdown timeout
    WORKER_FORCE_KILL = 2  # Workers required SIGKILL
    INTERNAL_ERROR = 3  # Unhandled exception during shutdown


class SimpleShutdownCoordinator:
    """Simple shutdown coordinator without complex tracking"""

    def __init__(self, logger):
        self.logger = logger
        self._shutdown_event = threading.Event()
        self._shutdown_reason: str | None = None
        self._shutdown_initiated = False
        self._exit_code = ExitCodes.SUCCESS

    def initiate_shutdown(self, reason: str = "manual") -> None:
        """Initiate shutdown sequence"""
        if self._shutdown_initiated:
            self.logger.warning(f"Shutdown already initiated, ignoring new request: {reason}")
            return

        self._shutdown_initiated = True
        self._shutdown_reason = reason
        self.logger.info(f"Shutdown initiated: {reason}")
        self._shutdown_event.set()

    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress"""
        return self._shutdown_event.is_set()

    def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """Wait for shutdown to be initiated"""
        return self._shutdown_event.wait(timeout)

    def get_shutdown_reason(self) -> str | None:
        """Get the reason for shutdown"""
        return self._shutdown_reason

    def set_exit_code(self, exit_code: int) -> None:
        """Set the exit code for this process"""
        self._exit_code = exit_code

    def get_exit_code(self) -> int:
        """Get the exit code for this process"""
        return self._exit_code


def setup_simple_signal_handlers(shutdown_coordinator: SimpleShutdownCoordinator) -> None:
    """Set up simple signal handlers"""

    def signal_handler(signum: int, frame: Any) -> None:
        if shutdown_coordinator._shutdown_initiated:
            shutdown_coordinator.logger.warning(f"Already shutting down, ignoring signal {signum}")
            return

        signal_name = signal.Signals(signum).name
        shutdown_coordinator.logger.info(f"Received signal {signum} ({signal_name})")
        shutdown_coordinator.initiate_shutdown(f"signal_{signal_name}")

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    shutdown_coordinator.logger.info("Signal handlers registered for SIGTERM and SIGINT")


class SimpleHealthMonitor:
    """Simple health monitoring without complex tracking"""

    def __init__(self, logger):
        self.logger = logger
        self._running = False

    def start_monitoring(self) -> None:
        """Start health monitoring"""
        self._running = True
        self.logger.info("Simple health monitoring started")

    def stop_monitoring(self) -> None:
        """Stop health monitoring"""
        self._running = False
        self.logger.info("Simple health monitoring stopped")

    def is_running(self) -> bool:
        """Check if health monitoring is running"""
        return self._running
