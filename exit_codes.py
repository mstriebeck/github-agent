"""
Exit code definitions for MCP server shutdown scenarios.

Provides standardized exit codes that process managers and monitoring systems
can interpret to understand how the server shutdown occurred.
"""

import enum


class ShutdownExitCode(enum.IntEnum):
    """Exit codes for different shutdown scenarios.

    These codes allow process managers (systemctl, launchctl) and monitoring
    systems to understand why the server exited and take appropriate action.
    """

    # Success codes (0-9)
    SUCCESS_CLEAN_SHUTDOWN = 0  # Normal graceful shutdown
    SUCCESS_SIGNAL_SHUTDOWN = 1  # Clean shutdown via signal (SIGTERM/SIGINT)

    # Graceful shutdown failures (10-19)
    TIMEOUT_WORKER_SHUTDOWN = 10  # Workers didn't shutdown within timeout
    TIMEOUT_CLIENT_DISCONNECT = 11  # Clients didn't disconnect within timeout
    TIMEOUT_RESOURCE_CLEANUP = 12  # Resources didn't cleanup within timeout
    TIMEOUT_PORT_RELEASE = 13  # Ports still in use after timeout

    # Force shutdown scenarios (20-29)
    FORCE_WORKER_TERMINATION = 20  # Had to forcefully kill workers
    FORCE_CLIENT_DISCONNECT = 21  # Had to forcefully disconnect clients
    FORCE_RESOURCE_CLEANUP = 22  # Had to forcefully cleanup resources

    # Critical failures (30-39)
    ZOMBIE_PROCESSES_DETECTED = 30  # Zombie processes found after shutdown
    PORT_STILL_IN_USE = 31  # Ports still occupied after cleanup
    RESOURCE_LEAK_DETECTED = 32  # Resource leaks detected
    VERIFICATION_FAILED = 33  # Post-shutdown verification failed

    # System errors (40-49)
    SIGNAL_HANDLER_ERROR = 40  # Error in signal handling
    SHUTDOWN_COORDINATOR_ERROR = 41  # Error in shutdown coordination
    WORKER_MANAGER_ERROR = 42  # Error in worker management
    CLIENT_MANAGER_ERROR = 43  # Error in client management
    RESOURCE_MANAGER_ERROR = 44  # Error in resource management

    # Configuration/setup errors (50-59)
    INVALID_CONFIGURATION = 50  # Invalid server configuration
    DEPENDENCY_ERROR = 51  # Missing required dependencies
    PERMISSION_ERROR = 52  # Insufficient permissions

    # Unknown/unexpected errors (60-69)
    UNEXPECTED_ERROR = 60  # Unexpected exception during shutdown
    CORRUPTION_DETECTED = 61  # Data corruption detected
    INCONSISTENT_STATE = 62  # Server in inconsistent state


class ExitCodeManager:
    """Manages exit code determination and reporting during shutdown."""

    def __init__(self, logger):
        self.logger = logger
        self._issues = []
        self._forced_actions = []
        self._verification_failures = []

    def report_timeout(self, component: str, timeout_duration: float):
        """Report a timeout during shutdown."""
        self.logger.error(f"Timeout in {component} after {timeout_duration}s")
        if "worker" in component.lower():
            self._issues.append(ShutdownExitCode.TIMEOUT_WORKER_SHUTDOWN)
        elif "client" in component.lower():
            self._issues.append(ShutdownExitCode.TIMEOUT_CLIENT_DISCONNECT)
        elif "resource" in component.lower():
            self._issues.append(ShutdownExitCode.TIMEOUT_RESOURCE_CLEANUP)
        elif "port" in component.lower():
            self._issues.append(ShutdownExitCode.TIMEOUT_PORT_RELEASE)

    def report_force_action(self, action: str, target: str):
        """Report a forced action during shutdown."""
        self.logger.warning(f"Forced {action} on {target}")
        if "worker" in target.lower() or "process" in target.lower():
            self._forced_actions.append(ShutdownExitCode.FORCE_WORKER_TERMINATION)
        elif "client" in target.lower():
            self._forced_actions.append(ShutdownExitCode.FORCE_CLIENT_DISCONNECT)
        elif "resource" in target.lower():
            self._forced_actions.append(ShutdownExitCode.FORCE_RESOURCE_CLEANUP)

    def report_verification_failure(self, check: str, details: str):
        """Report a verification failure after shutdown."""
        self.logger.error(f"Verification failed: {check} - {details}")
        if "zombie" in check.lower():
            self._verification_failures.append(
                ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED
            )
        elif "port" in check.lower():
            self._verification_failures.append(ShutdownExitCode.PORT_STILL_IN_USE)
        elif "resource" in check.lower() or "leak" in check.lower():
            self._verification_failures.append(ShutdownExitCode.RESOURCE_LEAK_DETECTED)
        else:
            self._verification_failures.append(ShutdownExitCode.VERIFICATION_FAILED)

    def report_system_error(self, component: str, error: Exception):
        """Report a system error during shutdown."""
        self.logger.error(f"System error in {component}: {error}")
        if "signal" in component.lower():
            self._issues.append(ShutdownExitCode.SIGNAL_HANDLER_ERROR)
        elif "coordinator" in component.lower():
            self._issues.append(ShutdownExitCode.SHUTDOWN_COORDINATOR_ERROR)
        elif "worker" in component.lower():
            self._issues.append(ShutdownExitCode.WORKER_MANAGER_ERROR)
        elif "client" in component.lower():
            self._issues.append(ShutdownExitCode.CLIENT_MANAGER_ERROR)
        elif "resource" in component.lower():
            self._issues.append(ShutdownExitCode.RESOURCE_MANAGER_ERROR)
        else:
            self._issues.append(ShutdownExitCode.UNEXPECTED_ERROR)

    def determine_exit_code(self, shutdown_reason: str = "manual") -> ShutdownExitCode:
        """Determine the appropriate exit code based on shutdown events."""

        # Critical failures take precedence
        if self._verification_failures:
            critical_code = max(self._verification_failures)
            self.logger.critical(
                f"Exiting with critical failure code: {critical_code.name} ({critical_code})"
            )
            return critical_code

        # System errors next
        if self._issues:
            error_code = max(self._issues)
            self.logger.error(
                f"Exiting with error code: {error_code.name} ({error_code})"
            )
            return error_code

        # Force actions indicate degraded shutdown
        if self._forced_actions:
            force_code = max(self._forced_actions)
            self.logger.warning(
                f"Exiting with force action code: {force_code.name} ({force_code})"
            )
            return force_code

        # Clean shutdown
        if shutdown_reason in ["SIGTERM", "SIGINT", "signal"]:
            self.logger.info(
                f"Exiting with clean signal shutdown: {ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN}"
            )
            return ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN
        else:
            self.logger.info(
                f"Exiting with clean manual shutdown: {ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN}"
            )
            return ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN

    def get_exit_summary(self) -> dict:
        """Get a summary of all shutdown events for logging."""
        return {
            "issues": [code.name for code in self._issues],
            "forced_actions": [code.name for code in self._forced_actions],
            "verification_failures": [
                code.name for code in self._verification_failures
            ],
            "total_problems": len(self._issues)
            + len(self._forced_actions)
            + len(self._verification_failures),
        }


def get_exit_code_description(code: ShutdownExitCode) -> str:
    """Get human-readable description of exit code."""
    descriptions = {
        ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN: "Server shutdown cleanly without issues",
        ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN: "Server shutdown cleanly via signal",
        ShutdownExitCode.TIMEOUT_WORKER_SHUTDOWN: "Worker processes did not shutdown within timeout",
        ShutdownExitCode.TIMEOUT_CLIENT_DISCONNECT: "Client connections did not close within timeout",
        ShutdownExitCode.TIMEOUT_RESOURCE_CLEANUP: "Resource cleanup did not complete within timeout",
        ShutdownExitCode.TIMEOUT_PORT_RELEASE: "Ports were not released within timeout",
        ShutdownExitCode.FORCE_WORKER_TERMINATION: "Worker processes were forcefully terminated",
        ShutdownExitCode.FORCE_CLIENT_DISCONNECT: "Client connections were forcefully closed",
        ShutdownExitCode.FORCE_RESOURCE_CLEANUP: "Resources were forcefully cleaned up",
        ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED: "Zombie processes detected after shutdown",
        ShutdownExitCode.PORT_STILL_IN_USE: "Ports still in use after shutdown",
        ShutdownExitCode.RESOURCE_LEAK_DETECTED: "Resource leaks detected after shutdown",
        ShutdownExitCode.VERIFICATION_FAILED: "Post-shutdown verification failed",
        ShutdownExitCode.SIGNAL_HANDLER_ERROR: "Error in signal handling system",
        ShutdownExitCode.SHUTDOWN_COORDINATOR_ERROR: "Error in shutdown coordination",
        ShutdownExitCode.WORKER_MANAGER_ERROR: "Error in worker process management",
        ShutdownExitCode.CLIENT_MANAGER_ERROR: "Error in client connection management",
        ShutdownExitCode.RESOURCE_MANAGER_ERROR: "Error in resource management",
        ShutdownExitCode.INVALID_CONFIGURATION: "Invalid server configuration detected",
        ShutdownExitCode.DEPENDENCY_ERROR: "Required dependencies missing or invalid",
        ShutdownExitCode.PERMISSION_ERROR: "Insufficient permissions for shutdown operations",
        ShutdownExitCode.UNEXPECTED_ERROR: "Unexpected error during shutdown",
        ShutdownExitCode.CORRUPTION_DETECTED: "Data corruption detected during shutdown",
        ShutdownExitCode.INCONSISTENT_STATE: "Server found in inconsistent state",
    }
    return descriptions.get(code, f"Unknown exit code: {code}")
