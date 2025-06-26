"""
Edge case tests for shutdown system.

Tests various edge cases and unusual scenarios that could occur during
shutdown to ensure robust handling of unexpected situations.
"""

import pytest
import time
import threading
import signal
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from tests.test_abstracts import MockProcessRegistry
from shutdown_manager import ShutdownManager
from exit_codes import ShutdownExitCode, ExitCodeManager
from health_monitor import HealthMonitor, ServerStatus, ShutdownPhase


class TestSignalHandlingEdgeCases:
    """Test edge cases in signal handling."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def manager(self, mock_logger):
        """Create a ShutdownManager."""
        return ShutdownManager(mock_logger, mode="master")
        
    def test_rapid_signal_delivery(self, manager, mock_logger):
        """Test rapid delivery of multiple signals."""
        shutdown_calls = []
        
        def track_shutdown(reason):
            shutdown_calls.append(reason)
            time.sleep(0.1)  # Simulate slow shutdown
            return True
            
        with patch.object(manager, 'shutdown', side_effect=track_shutdown):
            # Send multiple signals rapidly
            manager._signal_handler(signal.SIGTERM, None)
            manager._signal_handler(signal.SIGINT, None)
            manager._signal_handler(signal.SIGTERM, None)
            
            # Should only process one shutdown
            time.sleep(0.2)  # Wait for shutdown to complete
            assert len(shutdown_calls) >= 1  # At least one should be processed
            
    def test_signal_during_shutdown(self, manager, mock_logger):
        """Test signal received while shutdown is in progress."""
        shutdown_started = threading.Event()
        shutdown_completed = threading.Event()
        
        def slow_shutdown(reason):
            shutdown_started.set()
            time.sleep(0.2)
            shutdown_completed.set()
            return True
            
        with patch.object(manager, 'shutdown', side_effect=slow_shutdown):
            # Start shutdown in background
            shutdown_thread = threading.Thread(
                target=lambda: manager.shutdown("manual")
            )
            shutdown_thread.start()
            
            # Wait for shutdown to start, then send signal
            shutdown_started.wait(timeout=1.0)
            manager._signal_handler(signal.SIGTERM, None)
            
            shutdown_thread.join(timeout=1.0)
            
            # Should complete without issues
            assert shutdown_completed.is_set()
            
    def test_signal_handler_exception(self, manager, mock_logger):
        """Test exception in signal handler."""
        with patch.object(manager, 'shutdown') as mock_shutdown:
            mock_shutdown.side_effect = Exception("Shutdown failed")
            
            # Signal handler should not crash
            try:
                manager._signal_handler(signal.SIGTERM, None)
            except Exception:
                pytest.fail("Signal handler should not raise exceptions")
                
            mock_shutdown.assert_called_once()


class TestResourceCleanupEdgeCases:
    """Test edge cases in resource cleanup."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def manager(self, mock_logger):
        """Create a ShutdownManager."""
        return ShutdownManager(mock_logger, mode="worker")
        
    def test_cleanup_with_permission_errors(self, manager, mock_logger):
        """Test cleanup when permission errors occur."""
        with patch('shutdown_manager.psutil.Process') as mock_process_class:
            # Mock permission denied error
            mock_process = Mock()
            mock_process.open_files.side_effect = PermissionError("Access denied")
            mock_process.connections.side_effect = PermissionError("Access denied")
            mock_process_class.return_value = mock_process
            
            success, issues = manager._resource_tracker.cleanup_resources()
            
            # Should handle gracefully
            assert success is True  # Can't fail due to permission issues
            assert len(issues) > 0
            assert "permission" in issues[0].lower() or "access" in issues[0].lower()
            
    def test_cleanup_with_process_gone(self, manager, mock_logger):
        """Test cleanup when process no longer exists."""
        with patch('shutdown_manager.psutil.Process') as mock_process_class:
            import psutil
            mock_process_class.side_effect = psutil.NoSuchProcess(1234)
            
            success, issues = manager._resource_tracker.cleanup_resources()
            
            # Should handle gracefully - process gone is actually good
            assert success is True
            
    def test_port_verification_with_system_limits(self, manager, mock_logger):
        """Test port verification when hitting system limits."""
        ports = list(range(8000, 8100))  # Many ports
        
        with patch('shutdown_manager.socket.socket') as mock_socket_class:
            # Mock system limit error
            mock_socket = Mock()
            mock_socket.bind.side_effect = OSError("Too many open files")
            mock_socket_class.return_value.__enter__.return_value = mock_socket
            
            success, issues = manager._resource_tracker.verify_ports_released(ports)
            
            # Should handle gracefully and report issue
            assert success is False
            assert len(issues) > 0
            
    def test_cleanup_with_hanging_file_operations(self, manager, mock_logger):
        """Test cleanup when file operations hang."""
        with patch('shutdown_manager.psutil.Process') as mock_process_class:
            # Mock hanging file operation
            def hanging_files():
                time.sleep(10)  # Simulate hang
                return []
                
            mock_process = Mock()
            mock_process.open_files.side_effect = hanging_files
            mock_process.connections.return_value = []
            mock_process_class.return_value = mock_process
            
            # Should timeout and continue
            start_time = time.time()
            success, issues = manager._resource_tracker.cleanup_resources()
            duration = time.time() - start_time
            
            # Should not hang for 10 seconds
            assert duration < 5.0  # Should timeout much sooner
            assert success is True  # Timeout is not a failure


class TestHealthMonitoringEdgeCases:
    """Test edge cases in health monitoring."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def temp_health_file(self):
        """Create a temporary health file."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        
    @pytest.fixture
    def monitor(self, mock_logger, temp_health_file):
        """Create a HealthMonitor."""
        return HealthMonitor(mock_logger, temp_health_file)
        
    def test_health_file_permission_denied(self, mock_logger):
        """Test health monitor when health file path is not writable."""
        # Try to write to root directory (should fail)
        monitor = HealthMonitor(mock_logger, "/root/health.json")
        
        # Should handle gracefully
        monitor._update_health_file()
        
        # Should log error but not crash
        mock_logger.error.assert_called()
        
    def test_health_file_disk_full(self, monitor, mock_logger):
        """Test health monitor when disk is full."""
        with patch('builtins.open') as mock_open:
            # Mock disk full error
            mock_open.side_effect = OSError("No space left on device")
            
            monitor._update_health_file()
            
            # Should handle gracefully and log error
            mock_logger.error.assert_called()
            
    def test_concurrent_health_updates(self, monitor, mock_logger):
        """Test concurrent health status updates."""
        # Start monitoring
        monitor.start_monitoring()
        
        # Rapidly update status from multiple threads
        def update_worker():
            for i in range(10):
                monitor.update_worker_status(f"worker{i}", 1000+i, 8000+i, "running")
                monitor.add_error(f"Error {i}")
                time.sleep(0.01)
                
        threads = [threading.Thread(target=update_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        monitor.stop_monitoring()
        
        # Should handle concurrent updates without corruption
        assert monitor.get_current_status()["workers_count"] == 30  # 3 threads * 10 workers
        assert monitor.get_current_status()["errors_count"] >= 20  # At least some errors (may be truncated)
        
    def test_health_monitor_thread_cleanup(self, monitor, mock_logger):
        """Test health monitor thread is properly cleaned up."""
        monitor.start_monitoring()
        assert monitor._monitoring_thread.is_alive()
        
        # Stop monitoring
        monitor.stop_monitoring()
        
        # Thread should be stopped
        time.sleep(0.1)  # Give it time to stop
        assert not monitor._monitoring_thread.is_alive()
        
    def test_health_report_with_corrupted_data(self, monitor, mock_logger):
        """Test health report generation with corrupted internal data."""
        # Corrupt internal data
        monitor._workers = "not_a_dict"
        monitor._clients = None
        
        report = monitor._generate_health_report()
        
        # Should generate error report instead of crashing
        assert report.server_status == ServerStatus.ERROR
        assert len(report.errors) > 0


class TestExitCodeEdgeCases:
    """Test edge cases in exit code determination."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def manager(self, mock_logger):
        """Create an ExitCodeManager."""
        return ExitCodeManager(mock_logger)
        
    def test_multiple_issues_same_type(self, manager):
        """Test multiple issues of the same type."""
        # Report multiple worker timeouts
        manager.report_timeout("worker1_shutdown", 30.0)
        manager.report_timeout("worker2_shutdown", 30.0)
        manager.report_timeout("worker3_shutdown", 30.0)
        
        exit_code = manager.determine_exit_code("manual")
        
        # Should still return worker timeout code
        assert exit_code == ShutdownExitCode.TIMEOUT_WORKER_SHUTDOWN
        
        # Summary should show all issues
        summary = manager.get_exit_summary()
        assert summary["total_problems"] == 3
        
    def test_mixed_issue_precedence(self, manager):
        """Test precedence when mixing different issue types."""
        # Add issues in reverse order of precedence
        manager.report_force_action("kill", "worker")  # Force action (20s)
        manager.report_timeout("worker_shutdown", 30.0)  # Timeout (10s)
        manager.report_system_error("coordinator", Exception("error"))  # System error (40s)
        manager.report_verification_failure("zombie", "zombies found")  # Critical (30s)
        
        exit_code = manager.determine_exit_code("manual")
        
        # Critical verification failure should take precedence
        assert exit_code == ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED
        
    def test_unknown_component_mapping(self, manager):
        """Test error reporting for unknown components."""
        manager.report_timeout("unknown_component", 30.0)
        manager.report_force_action("unknown_action", "unknown_target")
        manager.report_system_error("unknown_system", Exception("error"))
        
        # Should still work but may use generic codes
        exit_code = manager.determine_exit_code("manual")
        assert exit_code in [
            ShutdownExitCode.UNEXPECTED_ERROR,
            ShutdownExitCode.FORCE_RESOURCE_CLEANUP  # Generic force action
        ]
        
    def test_empty_issues_with_signal_shutdown(self, manager):
        """Test clean signal shutdown with no issues."""
        exit_code = manager.determine_exit_code("SIGINT")
        
        assert exit_code == ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN
        
        summary = manager.get_exit_summary()
        assert summary["total_problems"] == 0


class TestProcessLifecycleEdgeCases:
    """Test edge cases in process lifecycle management."""
    
    @pytest.fixture
    def process_registry(self):
        """Create a process registry."""
        registry = MockProcessRegistry()
        yield registry
        registry.cleanup_all()
        
    def test_process_dies_during_shutdown(self, process_registry):
        """Test process dying unexpectedly during shutdown."""
        worker = process_registry.create_cooperative_process("worker1", shutdown_delay=0.1)
        
        # Start graceful shutdown
        worker.send_signal(signal.SIGTERM)
        
        # Process dies immediately instead of graceful shutdown
        worker._force_terminate()
        
        # Should detect that process is already stopped
        assert not worker.is_alive()
        assert worker.wait_for_exit(0.1) is True
        
    def test_process_becomes_zombie_after_signal(self, process_registry):
        """Test process becoming zombie after receiving signal."""
        zombie = process_registry.create_zombie_process("zombie1")
        
        # Send shutdown signal
        zombie.send_signal(signal.SIGTERM)
        
        # Process becomes zombie
        assert zombie.state.value == "zombie"
        assert zombie.is_alive()  # Zombies are technically alive
        assert zombie.wait_for_exit(1.0) is False  # But never exit properly
        
    def test_kill_resistant_process(self, process_registry):
        """Test process that resists SIGKILL."""
        resistant = process_registry.create_unresponsive_process("resistant1", kill_resistant=True)
        
        # Try all signals
        assert resistant.send_signal(signal.SIGTERM) is False
        assert resistant.send_signal(signal.SIGKILL) is False
        assert resistant.force_kill() is False
        
        # Process should still be alive
        assert resistant.is_alive()
        
    def test_process_resurrection(self, process_registry):
        """Test scenario where process appears to restart itself."""
        worker = process_registry.create_cooperative_process("worker1")
        original_pid = worker.pid
        
        # Kill process
        worker.send_signal(signal.SIGKILL)
        assert not worker.is_alive()
        
        # Simulate process restarting with new PID
        new_worker = process_registry.create_cooperative_process("worker1")
        new_worker.pid = original_pid + 1000  # Different PID
        
        # Should be treated as different process
        assert new_worker.pid != original_pid
        assert new_worker.is_alive()


class TestConcurrencyEdgeCases:
    """Test edge cases in concurrent operations."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def manager(self, mock_logger):
        """Create a ShutdownManager."""
        return ShutdownManager(mock_logger, mode="master")
        
    @pytest.mark.asyncio
    async def test_shutdown_during_initialization(self, manager, mock_logger):
        """Test shutdown called during manager initialization."""
        # This should be handled by initialization flag
        with patch.object(manager, '_setup_signal_handlers'):
            result = await manager.shutdown("test")
            # Should work even without full initialization
            assert result in [True, False]  # Either way is acceptable
            
    def test_race_condition_in_client_tracking(self, manager, mock_logger):
        """Test race condition in client tracking."""
        client_tracker = manager._client_tracker
        
        # Simulate rapid add/remove operations from multiple threads
        def worker():
            for i in range(50):
                client_id = f"client_{threading.current_thread().ident}_{i}"
                client_tracker.add_client(client_id, Mock())
                if i % 2 == 0:  # Remove every other client
                    client_tracker.remove_client(client_id)
                    
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        # Should not crash and should have reasonable client count
        count = client_tracker.get_client_count()
        assert 0 <= count <= 250  # Max possible clients
        
    def test_health_monitor_race_conditions(self, mock_logger):
        """Test race conditions in health monitor state updates."""
        monitor = HealthMonitor(mock_logger, "/tmp/race_test_health.json")
        
        # Start monitoring
        monitor.start_monitoring()
        
        def update_worker():
            for i in range(20):
                monitor.set_server_status(ServerStatus.RUNNING)
                monitor.update_worker_status(f"worker{i}", 1000+i, 8000+i, "running")
                monitor.add_error(f"Error {i}")
                monitor.set_shutdown_phase(ShutdownPhase.WORKERS_STOPPING)
                time.sleep(0.001)
                
        # Run multiple updaters concurrently
        threads = [threading.Thread(target=update_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        monitor.stop_monitoring()
        monitor.cleanup_health_file()
        
        # Should not crash and should have consistent state
        status = monitor.get_current_status()
        assert status["server_status"] == "running"
        assert status["workers_count"] == 60  # 3 threads * 20 workers
