"""
Test edge cases and error conditions for the simplified shutdown architecture.
"""

import logging
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from exit_codes import ExitCodeManager, ShutdownExitCode
from shutdown_simple import SimpleHealthMonitor


class TestHealthMonitoringEdgeCases:
    """Test edge cases for health monitoring."""

    @pytest.fixture
    def logger(self):
        """Create a real logger for testing."""
        logger = logging.getLogger(f"test_health_{id(self)}")
        logger.setLevel(logging.DEBUG)
        
        # Add console handler if not already present
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            ))
            logger.addHandler(handler)
        
        return logger

    @pytest.fixture
    def temp_health_file(self, tmp_path):
        """Create a temporary health file."""
        return str(tmp_path / "health.json")

    @pytest.fixture(autouse=True)
    def cleanup_health_file(self, temp_health_file):
        """Clean up health file after test."""
        yield
        # Clean up after test
        Path(temp_health_file).unlink(missing_ok=True)

    @pytest.fixture
    def monitor(self, logger):
        """Create a SimpleHealthMonitor."""
        return SimpleHealthMonitor(logger)

    def test_simple_health_monitor_basic_ops(self, monitor, logger):
        """Test basic operations of SimpleHealthMonitor."""
        logger.info("Testing basic health monitor operations")
        
        # Test start monitoring
        monitor.start_monitoring()
        assert monitor.is_running()

        # Test stop monitoring
        monitor.stop_monitoring()
        assert not monitor.is_running()
        
        logger.info("Basic health monitor operations test completed")

    def test_simple_health_monitor_double_start(self, monitor, logger):
        """Test starting monitoring twice."""
        logger.info("Testing double start of health monitor")
        
        monitor.start_monitoring()
        monitor.start_monitoring()  # Should handle gracefully
        assert monitor.is_running()

        monitor.stop_monitoring()
        assert not monitor.is_running()
        
        logger.info("Double start test completed")


class TestExitCodeEdgeCases:
    """Test edge cases for exit code management."""

    @pytest.fixture
    def logger(self):
        """Create a real logger for testing."""
        logger = logging.getLogger(f"test_exit_codes_{id(self)}")
        logger.setLevel(logging.DEBUG)
        
        # Add console handler if not already present
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            ))
            logger.addHandler(handler)
        
        return logger

    @pytest.fixture
    def manager(self, logger):
        """Create an ExitCodeManager."""
        return ExitCodeManager(logger)

    def test_exit_code_manager_creation(self, manager, logger):
        """Test basic exit code manager functionality."""
        logger.info("Testing exit code manager creation")
        
        # Should start with clean state
        exit_code = manager.determine_exit_code()
        assert exit_code == ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN
        
        logger.info(f"Initial exit code: {exit_code}")

    def test_timeout_reporting(self, manager, logger):
        """Test timeout reporting."""
        logger.info("Testing timeout reporting")
        
        manager.report_timeout("worker", 30.0)
        exit_code = manager.determine_exit_code()
        assert exit_code == ShutdownExitCode.TIMEOUT_WORKER_SHUTDOWN
        
        logger.info(f"Exit code after timeout: {exit_code}")

    def test_system_error_reporting(self, manager, logger):
        """Test system error reporting."""
        logger.info("Testing system error reporting")
        
        manager.report_system_error("signal", Exception("Test error"))
        exit_code = manager.determine_exit_code()
        assert exit_code == ShutdownExitCode.SIGNAL_HANDLER_ERROR
        
        logger.info(f"Exit code after system error: {exit_code}")
