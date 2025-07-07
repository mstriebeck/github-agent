"""
Tests for exit code system functionality.
"""

import logging
from unittest.mock import Mock

import pytest

from exit_codes import ExitCodeManager, ShutdownExitCode, get_exit_code_description


class TestShutdownExitCode:
    """Test the ShutdownExitCode enum."""

    def test_success_codes(self):
        """Test that success codes are in expected range."""
        assert 0 <= ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN <= 9
        assert 0 <= ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN <= 9

    def test_timeout_codes(self):
        """Test that timeout codes are in expected range."""
        assert 10 <= ShutdownExitCode.TIMEOUT_WORKER_SHUTDOWN <= 19
        assert 10 <= ShutdownExitCode.TIMEOUT_CLIENT_DISCONNECT <= 19
        assert 10 <= ShutdownExitCode.TIMEOUT_RESOURCE_CLEANUP <= 19
        assert 10 <= ShutdownExitCode.TIMEOUT_PORT_RELEASE <= 19

    def test_force_codes(self):
        """Test that force codes are in expected range."""
        assert 20 <= ShutdownExitCode.FORCE_WORKER_TERMINATION <= 29
        assert 20 <= ShutdownExitCode.FORCE_CLIENT_DISCONNECT <= 29
        assert 20 <= ShutdownExitCode.FORCE_RESOURCE_CLEANUP <= 29

    def test_critical_codes(self):
        """Test that critical codes are in expected range."""
        assert 30 <= ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED <= 39
        assert 30 <= ShutdownExitCode.PORT_STILL_IN_USE <= 39
        assert 30 <= ShutdownExitCode.RESOURCE_LEAK_DETECTED <= 39
        assert 30 <= ShutdownExitCode.VERIFICATION_FAILED <= 39

    def test_system_error_codes(self):
        """Test that system error codes are in expected range."""
        assert 40 <= ShutdownExitCode.SIGNAL_HANDLER_ERROR <= 49
        assert 40 <= ShutdownExitCode.SHUTDOWN_COORDINATOR_ERROR <= 49
        assert 40 <= ShutdownExitCode.WORKER_MANAGER_ERROR <= 49
        assert 40 <= ShutdownExitCode.CLIENT_MANAGER_ERROR <= 49
        assert 40 <= ShutdownExitCode.RESOURCE_MANAGER_ERROR <= 49


class TestExitCodeManager:
    """Test the ExitCodeManager class."""

    @pytest.fixture
    def manager(self, test_logger):
        """Create an ExitCodeManager instance."""
        return ExitCodeManager(test_logger)

    def test_initialization(self, manager, test_logger):
        """Test manager initialization."""
        assert manager.logger == test_logger
        assert manager._issues == []
        assert manager._forced_actions == []
        assert manager._verification_failures == []

    def test_report_timeout_worker(self, manager, mock_logger):
        """Test reporting worker timeout."""
        manager.report_timeout("worker_shutdown", 30.0)

        mock_logger.error.assert_called_once_with(
            "Timeout in worker_shutdown after 30.0s"
        )
        assert ShutdownExitCode.TIMEOUT_WORKER_SHUTDOWN in manager._issues

    def test_report_timeout_client(self, manager, mock_logger):
        """Test reporting client timeout."""
        manager.report_timeout("client_disconnect", 15.0)

        mock_logger.error.assert_called_once_with(
            "Timeout in client_disconnect after 15.0s"
        )
        assert ShutdownExitCode.TIMEOUT_CLIENT_DISCONNECT in manager._issues

    def test_report_timeout_resource(self, manager, mock_logger):
        """Test reporting resource timeout."""
        manager.report_timeout("resource_cleanup", 10.0)

        mock_logger.error.assert_called_once_with(
            "Timeout in resource_cleanup after 10.0s"
        )
        assert ShutdownExitCode.TIMEOUT_RESOURCE_CLEANUP in manager._issues

    def test_report_timeout_port(self, manager, mock_logger):
        """Test reporting port timeout."""
        manager.report_timeout("port_release", 5.0)

        mock_logger.error.assert_called_once_with("Timeout in port_release after 5.0s")
        assert ShutdownExitCode.TIMEOUT_PORT_RELEASE in manager._issues

    def test_report_force_action_worker(self, manager, mock_logger):
        """Test reporting forced worker termination."""
        manager.report_force_action("kill", "worker_process")

        mock_logger.warning.assert_called_once_with("Forced kill on worker_process")
        assert ShutdownExitCode.FORCE_WORKER_TERMINATION in manager._forced_actions

    def test_report_force_action_client(self, manager, mock_logger):
        """Test reporting forced client disconnect."""
        manager.report_force_action("disconnect", "client_connection")

        mock_logger.warning.assert_called_once_with(
            "Forced disconnect on client_connection"
        )
        assert ShutdownExitCode.FORCE_CLIENT_DISCONNECT in manager._forced_actions

    def test_report_force_action_resource(self, manager, mock_logger):
        """Test reporting forced resource cleanup."""
        manager.report_force_action("cleanup", "resource_handles")

        mock_logger.warning.assert_called_once_with(
            "Forced cleanup on resource_handles"
        )
        assert ShutdownExitCode.FORCE_RESOURCE_CLEANUP in manager._forced_actions

    def test_report_verification_failure_zombie(self, manager, mock_logger):
        """Test reporting zombie process verification failure."""
        manager.report_verification_failure("zombie_check", "Found 2 zombie processes")

        mock_logger.error.assert_called_once_with(
            "Verification failed: zombie_check - Found 2 zombie processes"
        )
        assert (
            ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED in manager._verification_failures
        )

    def test_report_verification_failure_port(self, manager, mock_logger):
        """Test reporting port verification failure."""
        manager.report_verification_failure("port_check", "Port 8080 still in use")

        mock_logger.error.assert_called_once_with(
            "Verification failed: port_check - Port 8080 still in use"
        )
        assert ShutdownExitCode.PORT_STILL_IN_USE in manager._verification_failures

    def test_report_verification_failure_resource(self, manager, mock_logger):
        """Test reporting resource leak verification failure."""
        manager.report_verification_failure(
            "resource_leak", "Database connections not closed"
        )

        mock_logger.error.assert_called_once_with(
            "Verification failed: resource_leak - Database connections not closed"
        )
        assert ShutdownExitCode.RESOURCE_LEAK_DETECTED in manager._verification_failures

    def test_report_verification_failure_generic(self, manager, mock_logger):
        """Test reporting generic verification failure."""
        manager.report_verification_failure("other_check", "Something went wrong")

        mock_logger.error.assert_called_once_with(
            "Verification failed: other_check - Something went wrong"
        )
        assert ShutdownExitCode.VERIFICATION_FAILED in manager._verification_failures

    def test_report_system_error_signal(self, manager, mock_logger):
        """Test reporting signal handler error."""
        error = Exception("Signal handler failed")
        manager.report_system_error("signal_handler", error)

        mock_logger.error.assert_called_once_with(
            "System error in signal_handler: Signal handler failed"
        )
        assert ShutdownExitCode.SIGNAL_HANDLER_ERROR in manager._issues

    def test_report_system_error_coordinator(self, manager, mock_logger):
        """Test reporting coordinator error."""
        error = Exception("Coordinator failed")
        manager.report_system_error("shutdown_coordinator", error)

        mock_logger.error.assert_called_once_with(
            "System error in shutdown_coordinator: Coordinator failed"
        )
        assert ShutdownExitCode.SHUTDOWN_COORDINATOR_ERROR in manager._issues

    def test_report_system_error_worker(self, manager, mock_logger):
        """Test reporting worker manager error."""
        error = Exception("Worker manager failed")
        manager.report_system_error("worker_manager", error)

        mock_logger.error.assert_called_once_with(
            "System error in worker_manager: Worker manager failed"
        )
        assert ShutdownExitCode.WORKER_MANAGER_ERROR in manager._issues

    def test_report_system_error_client(self, manager, mock_logger):
        """Test reporting client manager error."""
        error = Exception("Client manager failed")
        manager.report_system_error("client_manager", error)

        mock_logger.error.assert_called_once_with(
            "System error in client_manager: Client manager failed"
        )
        assert ShutdownExitCode.CLIENT_MANAGER_ERROR in manager._issues

    def test_report_system_error_resource(self, manager, mock_logger):
        """Test reporting resource manager error."""
        error = Exception("Resource manager failed")
        manager.report_system_error("resource_manager", error)

        mock_logger.error.assert_called_once_with(
            "System error in resource_manager: Resource manager failed"
        )
        assert ShutdownExitCode.RESOURCE_MANAGER_ERROR in manager._issues

    def test_report_system_error_generic(self, manager, mock_logger):
        """Test reporting generic system error."""
        error = Exception("Unknown error")
        manager.report_system_error("unknown_component", error)

        mock_logger.error.assert_called_once_with(
            "System error in unknown_component: Unknown error"
        )
        assert ShutdownExitCode.UNEXPECTED_ERROR in manager._issues

    def test_determine_exit_code_clean_manual(self, manager, mock_logger):
        """Test determining exit code for clean manual shutdown."""
        code = manager.determine_exit_code("manual")

        assert code == ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN
        mock_logger.info.assert_called_once_with(
            f"Exiting with clean manual shutdown: {ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN}"
        )

    def test_determine_exit_code_clean_signal(self, manager, mock_logger):
        """Test determining exit code for clean signal shutdown."""
        code = manager.determine_exit_code("SIGTERM")

        assert code == ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN
        mock_logger.info.assert_called_once_with(
            f"Exiting with clean signal shutdown: {ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN}"
        )

    def test_determine_exit_code_forced_actions(self, manager, mock_logger):
        """Test determining exit code with forced actions."""
        manager.report_force_action("kill", "worker")
        code = manager.determine_exit_code("manual")

        assert code == ShutdownExitCode.FORCE_WORKER_TERMINATION
        mock_logger.warning.assert_called_with(
            f"Exiting with force action code: {ShutdownExitCode.FORCE_WORKER_TERMINATION.name} ({ShutdownExitCode.FORCE_WORKER_TERMINATION})"
        )

    def test_determine_exit_code_system_errors(self, manager, mock_logger):
        """Test determining exit code with system errors."""
        manager.report_system_error("worker", Exception("error"))
        code = manager.determine_exit_code("manual")

        assert code == ShutdownExitCode.WORKER_MANAGER_ERROR
        mock_logger.error.assert_called_with(
            f"Exiting with error code: {ShutdownExitCode.WORKER_MANAGER_ERROR.name} ({ShutdownExitCode.WORKER_MANAGER_ERROR})"
        )

    def test_determine_exit_code_verification_failures(self, manager, mock_logger):
        """Test determining exit code with verification failures."""
        manager.report_verification_failure("zombie", "zombies found")
        code = manager.determine_exit_code("manual")

        assert code == ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED
        mock_logger.critical.assert_called_with(
            f"Exiting with critical failure code: {ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED.name} ({ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED})"
        )

    def test_determine_exit_code_precedence(self, manager, mock_logger):
        """Test that verification failures take precedence over other issues."""
        manager.report_force_action("kill", "worker")
        manager.report_system_error("worker", Exception("error"))
        manager.report_verification_failure("zombie", "zombies found")

        code = manager.determine_exit_code("manual")

        # Verification failures should take precedence
        assert code == ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED

    def test_determine_exit_code_max_precedence(self, manager, mock_logger):
        """Test that the highest severity code is returned when multiple exist."""
        manager.report_verification_failure("port", "port issue")  # 31
        manager.report_verification_failure("zombie", "zombie issue")  # 30

        code = manager.determine_exit_code("manual")

        # Should return the higher code
        assert code == ShutdownExitCode.PORT_STILL_IN_USE  # 31 > 30

    def test_get_exit_summary(self, manager):
        """Test getting exit summary."""
        manager.report_timeout("worker", 30.0)
        manager.report_force_action("kill", "worker")
        manager.report_verification_failure("zombie", "zombies found")

        summary = manager.get_exit_summary()

        assert summary["total_problems"] == 3
        assert "TIMEOUT_WORKER_SHUTDOWN" in summary["issues"]
        assert "FORCE_WORKER_TERMINATION" in summary["forced_actions"]
        assert "ZOMBIE_PROCESSES_DETECTED" in summary["verification_failures"]


class TestExitCodeDescriptions:
    """Test exit code descriptions."""

    def test_get_exit_code_description_success(self):
        """Test getting description for success codes."""
        desc = get_exit_code_description(ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN)
        assert "cleanly without issues" in desc

        desc = get_exit_code_description(ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN)
        assert "cleanly via signal" in desc

    def test_get_exit_code_description_timeout(self):
        """Test getting description for timeout codes."""
        desc = get_exit_code_description(ShutdownExitCode.TIMEOUT_WORKER_SHUTDOWN)
        assert "did not shutdown within timeout" in desc

    def test_get_exit_code_description_force(self):
        """Test getting description for force codes."""
        desc = get_exit_code_description(ShutdownExitCode.FORCE_WORKER_TERMINATION)
        assert "forcefully terminated" in desc

    def test_get_exit_code_description_critical(self):
        """Test getting description for critical codes."""
        desc = get_exit_code_description(ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED)
        assert "Zombie processes detected" in desc

    def test_get_exit_code_description_unknown(self):
        """Test getting description for unknown code."""

        # Test with a simple object that simulates an unknown enum value
        class FakeExitCode:
            def __init__(self, value):
                self.value = value

            def __str__(self):
                return str(self.value)

        fake_code = FakeExitCode(999)
        desc = get_exit_code_description(fake_code)  # type: ignore[arg-type]
        assert "Unknown exit code: 999" in desc
