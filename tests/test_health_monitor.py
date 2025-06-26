"""
Tests for health monitoring functionality.
"""

import pytest
import json
import time
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from health_monitor import (
    HealthMonitor,
    ServerStatus,
    ShutdownPhase,
    HealthReport,
    read_health_status,
    is_server_healthy
)


class TestServerStatus:
    """Test ServerStatus enum."""
    
    def test_status_values(self):
        """Test that status values are correct."""
        assert ServerStatus.STARTING.value == "starting"
        assert ServerStatus.RUNNING.value == "running"
        assert ServerStatus.SHUTTING_DOWN.value == "shutting_down"
        assert ServerStatus.STOPPED.value == "stopped"
        assert ServerStatus.ERROR.value == "error"


class TestShutdownPhase:
    """Test ShutdownPhase enum."""
    
    def test_phase_values(self):
        """Test that phase values are correct."""
        assert ShutdownPhase.NOT_STARTED.value == "not_started"
        assert ShutdownPhase.WORKERS_STOPPING.value == "workers_stopping"
        assert ShutdownPhase.CLIENTS_DISCONNECTING.value == "clients_disconnecting"
        assert ShutdownPhase.RESOURCES_CLEANING.value == "resources_cleaning"
        assert ShutdownPhase.VERIFICATION.value == "verification"
        assert ShutdownPhase.COMPLETED.value == "completed"
        assert ShutdownPhase.FAILED.value == "failed"


class TestHealthMonitor:
    """Test HealthMonitor class."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def temp_health_file(self):
        """Create a temporary health file path."""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as f:
            path = f.name
        yield path
        Path(path).unlink(missing_ok=True)
        
    @pytest.fixture
    def monitor(self, mock_logger, temp_health_file):
        """Create a HealthMonitor instance."""
        return HealthMonitor(mock_logger, temp_health_file)
        
    def test_initialization(self, monitor, mock_logger, temp_health_file):
        """Test monitor initialization."""
        assert monitor.logger == mock_logger
        assert str(monitor.health_file_path) == temp_health_file
        assert monitor._status == ServerStatus.STARTING
        assert monitor._shutdown_phase == ShutdownPhase.NOT_STARTED
        assert monitor._workers == {}
        assert monitor._clients == {}
        assert monitor._errors == []
        assert monitor._warnings == []
        assert monitor._should_monitor is True
        
    def test_set_server_status(self, monitor, mock_logger):
        """Test setting server status."""
        monitor.set_server_status(ServerStatus.RUNNING)
        
        assert monitor._status == ServerStatus.RUNNING
        mock_logger.info.assert_called_with("Server status changed: starting -> running")
        
    def test_set_shutdown_phase(self, monitor, mock_logger):
        """Test setting shutdown phase."""
        monitor.set_shutdown_phase(ShutdownPhase.WORKERS_STOPPING)
        
        assert monitor._shutdown_phase == ShutdownPhase.WORKERS_STOPPING
        mock_logger.info.assert_called_with("Shutdown phase changed: not_started -> workers_stopping")
        
    def test_update_worker_status_new(self, monitor, mock_logger):
        """Test updating status for new worker."""
        monitor.update_worker_status("worker1", 1234, 8080, "running")
        
        assert "worker1" in monitor._workers
        worker = monitor._workers["worker1"]
        assert worker.worker_id == "worker1"
        assert worker.pid == 1234
        assert worker.port == 8080
        assert worker.status == "running"
        assert not worker.shutdown_requested
        assert not worker.shutdown_completed
        
        mock_logger.debug.assert_called_with("Worker worker1 status updated: running")
        
    def test_update_worker_status_existing(self, monitor, mock_logger):
        """Test updating status for existing worker."""
        # Add initial worker
        monitor.update_worker_status("worker1", 1234, 8080, "running")
        initial_time = monitor._workers["worker1"].last_seen
        
        # Update worker
        time.sleep(0.01)  # Ensure time difference
        monitor.update_worker_status("worker1", 1234, 8080, "stopping")
        
        worker = monitor._workers["worker1"]
        assert worker.status == "stopping"
        assert worker.last_seen > initial_time
        
    def test_set_worker_shutdown_requested(self, monitor, mock_logger):
        """Test setting worker shutdown requested."""
        monitor.update_worker_status("worker1", 1234, 8080, "running")
        monitor.set_worker_shutdown_requested("worker1")
        
        assert monitor._workers["worker1"].shutdown_requested is True
        mock_logger.debug.assert_called_with("Worker worker1 shutdown requested")
        
    def test_set_worker_shutdown_completed(self, monitor, mock_logger):
        """Test setting worker shutdown completed."""
        monitor.update_worker_status("worker1", 1234, 8080, "running")
        monitor.set_worker_shutdown_completed("worker1")
        
        worker = monitor._workers["worker1"]
        assert worker.shutdown_completed is True
        assert worker.status == "stopped"
        mock_logger.debug.assert_called_with("Worker worker1 shutdown completed")
        
    def test_add_client(self, monitor, mock_logger):
        """Test adding a client."""
        monitor.add_client("client1", "worker1")
        
        assert "client1" in monitor._clients
        client = monitor._clients["client1"]
        assert client.client_id == "client1"
        assert client.worker_id == "worker1"
        assert not client.disconnect_requested
        assert not client.disconnected
        
        mock_logger.debug.assert_called_with("Client client1 connected to worker worker1")
        
    def test_update_client_activity(self, monitor):
        """Test updating client activity."""
        monitor.add_client("client1", "worker1")
        initial_time = monitor._clients["client1"].last_activity
        
        time.sleep(0.01)  # Ensure time difference
        monitor.update_client_activity("client1")
        
        assert monitor._clients["client1"].last_activity > initial_time
        
    def test_set_client_disconnect_requested(self, monitor, mock_logger):
        """Test setting client disconnect requested."""
        monitor.add_client("client1", "worker1")
        monitor.set_client_disconnect_requested("client1")
        
        assert monitor._clients["client1"].disconnect_requested is True
        mock_logger.debug.assert_called_with("Client client1 disconnect requested")
        
    def test_set_client_disconnected(self, monitor, mock_logger):
        """Test setting client disconnected."""
        monitor.add_client("client1", "worker1")
        monitor.set_client_disconnected("client1")
        
        assert monitor._clients["client1"].disconnected is True
        mock_logger.debug.assert_called_with("Client client1 disconnected")
        
    def test_remove_client(self, monitor, mock_logger):
        """Test removing a client."""
        monitor.add_client("client1", "worker1")
        assert "client1" in monitor._clients
        
        monitor.remove_client("client1")
        assert "client1" not in monitor._clients
        mock_logger.debug.assert_called_with("Client client1 removed from tracking")
        
    def test_set_resource_cleanup_requested(self, monitor, mock_logger):
        """Test setting resource cleanup requested."""
        monitor.set_resource_cleanup_requested()
        
        assert monitor._resources.cleanup_requested is True
        mock_logger.debug.assert_called_with("Resource cleanup requested")
        
    def test_set_resource_cleanup_completed(self, monitor, mock_logger):
        """Test setting resource cleanup completed."""
        monitor.set_resource_cleanup_completed()
        
        assert monitor._resources.cleanup_completed is True
        mock_logger.debug.assert_called_with("Resource cleanup completed")
        
    def test_update_shutdown_progress(self, monitor, mock_logger):
        """Test updating shutdown progress."""
        progress = {"workers_stopped": 2, "total_workers": 3}
        monitor.update_shutdown_progress("workers", progress)
        
        assert "workers" in monitor._shutdown_progress
        assert monitor._shutdown_progress["workers"]["workers_stopped"] == 2
        assert monitor._shutdown_progress["workers"]["total_workers"] == 3
        assert "timestamp" in monitor._shutdown_progress["workers"]
        
        mock_logger.debug.assert_called_with(f"Shutdown progress updated for workers: {progress}")
        
    def test_add_error(self, monitor, mock_logger):
        """Test adding an error."""
        monitor.add_error("Test error")
        
        assert len(monitor._errors) == 1
        assert "Test error" in monitor._errors[0]
        mock_logger.error.assert_called_with("Health monitor recorded error: Test error")
        
    def test_add_warning(self, monitor, mock_logger):
        """Test adding a warning."""
        monitor.add_warning("Test warning")
        
        assert len(monitor._warnings) == 1
        assert "Test warning" in monitor._warnings[0]
        mock_logger.warning.assert_called_with("Health monitor recorded warning: Test warning")
        
    def test_error_warning_limit(self, monitor):
        """Test that errors and warnings are limited to 20."""
        # Add more than 20 errors
        for i in range(25):
            monitor.add_error(f"Error {i}")
            
        # Should only keep last 20
        assert len(monitor._errors) == 20
        assert "Error 24" in monitor._errors[-1]
        assert "Error 4" not in str(monitor._errors)  # First 5 should be gone
        
    def test_get_current_status(self, monitor):
        """Test getting current status."""
        monitor.set_server_status(ServerStatus.RUNNING)
        monitor.add_client("client1", "worker1")
        monitor.add_error("Test error")
        monitor.add_warning("Test warning")
        
        status = monitor.get_current_status()
        
        assert status["server_status"] == "running"
        assert status["shutdown_phase"] == "not_started"
        assert status["clients_count"] == 1
        assert status["errors_count"] == 1
        assert status["warnings_count"] == 1
        assert "uptime_seconds" in status
        
    def test_is_shutdown_complete_false(self, monitor):
        """Test shutdown complete check when not complete."""
        assert monitor.is_shutdown_complete() is False
        
        monitor.set_shutdown_phase(ShutdownPhase.WORKERS_STOPPING)
        assert monitor.is_shutdown_complete() is False
        
    def test_is_shutdown_complete_true(self, monitor):
        """Test shutdown complete check when complete."""
        monitor.set_shutdown_phase(ShutdownPhase.COMPLETED)
        assert monitor.is_shutdown_complete() is True
        
        monitor.set_shutdown_phase(ShutdownPhase.FAILED)
        assert monitor.is_shutdown_complete() is True
        
    def test_get_stuck_workers(self, monitor):
        """Test getting stuck workers."""
        # Add workers
        monitor.update_worker_status("worker1", 1234, 8080, "running")
        monitor.update_worker_status("worker2", 1235, 8081, "running")
        monitor.update_worker_status("worker3", 1236, 8082, "running")
        
        # Set shutdown requested for all
        monitor.set_worker_shutdown_requested("worker1")
        monitor.set_worker_shutdown_requested("worker2")
        monitor.set_worker_shutdown_requested("worker3")
        
        # Complete shutdown for worker2
        monitor.set_worker_shutdown_completed("worker2")
        
        # Make worker1 appear old (stuck)
        old_time = datetime.now() - timedelta(seconds=35)
        monitor._workers["worker1"].last_seen = old_time
        
        stuck_workers = monitor.get_stuck_workers(timeout_seconds=30)
        
        # Only worker1 should be stuck (worker2 completed, worker3 is recent)
        assert stuck_workers == ["worker1"]
        
    @patch('health_monitor.psutil.Process')
    def test_update_resource_status(self, mock_process_class, monitor):
        """Test updating resource status from system."""
        # Mock process
        mock_process = Mock()
        mock_process.open_files.return_value = [Mock(), Mock()]  # 2 files
        mock_process.net_connections.return_value = [Mock()]  # 1 connection
        mock_process.memory_info.return_value.rss = 1024 * 1024 * 100  # 100MB
        mock_process_class.return_value = mock_process
        
        monitor._update_resource_status()
        
        assert monitor._resources.open_files == 2
        assert monitor._resources.open_connections == 1
        assert monitor._resources.memory_usage_mb == 100.0
        
    @patch('health_monitor.psutil.Process')
    def test_update_resource_status_error(self, mock_process_class, monitor, mock_logger):
        """Test updating resource status with error."""
        import psutil
        mock_process_class.side_effect = psutil.AccessDenied("Process error")
        
        monitor._update_resource_status()
        
        # Should not crash, but log warning
        mock_logger.warning.assert_called_once()
        # Check that the warning message contains the key text
        warning_call = mock_logger.warning.call_args[0][0]
        assert "Could not update resource status:" in warning_call
        
    def test_generate_health_report(self, monitor):
        """Test generating health report."""
        # Set up some state
        monitor.set_server_status(ServerStatus.RUNNING)
        monitor.set_shutdown_phase(ShutdownPhase.WORKERS_STOPPING)
        monitor.add_client("client1", "worker1")
        monitor.add_error("Test error")
        monitor.add_warning("Test warning")
        monitor.update_shutdown_progress("workers", {"stopped": 1})
        
        with patch.object(monitor, '_update_resource_status'):
            report = monitor._generate_health_report()
            
        assert isinstance(report, HealthReport)
        assert report.server_status == ServerStatus.RUNNING
        assert report.shutdown_phase == ShutdownPhase.WORKERS_STOPPING
        assert len(report.clients) == 1
        assert len(report.errors) == 1
        assert len(report.warnings) == 1
        assert "workers" in report.shutdown_progress
        
    def test_generate_health_report_error(self, monitor, mock_logger):
        """Test generating health report with error."""
        # Force an error by corrupting internal state
        monitor._workers = "invalid"  # Should cause TypeError
        
        report = monitor._generate_health_report()
        
        assert report.server_status == ServerStatus.ERROR
        assert len(report.errors) == 1
        assert "Health report generation failed" in report.errors[0]
        
    def test_update_health_file(self, monitor, temp_health_file):
        """Test updating health file."""
        monitor.set_server_status(ServerStatus.RUNNING)
        
        with patch.object(monitor, '_update_resource_status'):
            monitor._update_health_file()
            
        # Check that file was written
        assert Path(temp_health_file).exists()
        
        # Check file content
        with open(temp_health_file, 'r') as f:
            data = json.load(f)
            
        assert data["server_status"] in ["running", "ServerStatus.RUNNING"]
        assert "timestamp" in data
        assert "pid" in data
        
    def test_monitoring_thread_lifecycle(self, monitor):
        """Test monitoring thread start/stop."""
        assert monitor._monitoring_thread is None
        
        # Start monitoring
        import time
        def mock_monitoring_loop():
            while monitor._should_monitor:
                time.sleep(0.1)
                
        with patch.object(monitor, '_monitoring_loop', side_effect=mock_monitoring_loop):
            monitor.start_monitoring()
            time.sleep(0.2)  # Give thread time to start
            assert monitor._monitoring_thread is not None
            assert monitor._monitoring_thread.is_alive()
            assert monitor._should_monitor is True
            
            # Stop monitoring
            monitor.stop_monitoring()
            assert monitor._should_monitor is False
            
    def test_start_monitoring_already_running(self, monitor, mock_logger):
        """Test starting monitoring when already running."""
        # Mock a running thread
        monitor._monitoring_thread = Mock()
        monitor._monitoring_thread.is_alive.return_value = True
        
        monitor.start_monitoring()
        
        mock_logger.warning.assert_called_with("Health monitoring already running")
        
    def test_cleanup_health_file(self, monitor, temp_health_file, mock_logger):
        """Test cleaning up health file."""
        # Create the file
        Path(temp_health_file).touch()
        assert Path(temp_health_file).exists()
        
        monitor.cleanup_health_file()
        
        assert not Path(temp_health_file).exists()
        mock_logger.info.assert_called_with("Health file cleaned up")
        
    def test_cleanup_health_file_not_exists(self, monitor, temp_health_file, mock_logger):
        """Test cleaning up non-existent health file."""
        # Ensure file doesn't exist
        Path(temp_health_file).unlink(missing_ok=True)
        assert not Path(temp_health_file).exists()
        
        monitor.cleanup_health_file()
        
        # Should not crash and not log cleanup message since file doesn't exist
        # Check that no "Health file cleaned up" message was logged
        cleanup_calls = [call for call in mock_logger.info.call_args_list 
                        if "Health file cleaned up" in str(call)]
        assert len(cleanup_calls) == 0


class TestHealthStatusFunctions:
    """Test standalone health status functions."""
    
    def test_read_health_status_success(self, tmp_path):
        """Test reading health status successfully."""
        health_file = tmp_path / "health.json"
        test_data = {"server_status": "running", "timestamp": "2023-01-01T12:00:00"}
        
        with open(health_file, 'w') as f:
            json.dump(test_data, f)
            
        result = read_health_status(str(health_file))
        
        assert result == test_data
        
    def test_read_health_status_not_found(self, tmp_path):
        """Test reading non-existent health status file."""
        health_file = tmp_path / "nonexistent.json"
        
        result = read_health_status(str(health_file))
        
        assert result is None
        
    def test_read_health_status_invalid_json(self, tmp_path):
        """Test reading invalid JSON health status file."""
        health_file = tmp_path / "health.json"
        
        with open(health_file, 'w') as f:
            f.write("invalid json")
            
        result = read_health_status(str(health_file))
        
        assert result == {"error": "Invalid health file format"}
        
    def test_is_server_healthy_true(self, tmp_path):
        """Test server healthy check returning true."""
        health_file = tmp_path / "health.json"
        test_data = {
            "server_status": "running",
            "timestamp": datetime.now().isoformat()
        }
        
        with open(health_file, 'w') as f:
            json.dump(test_data, f)
            
        result = is_server_healthy(str(health_file))
        
        assert result is True
        
    def test_is_server_healthy_false_old(self, tmp_path):
        """Test server healthy check returning false for old timestamp."""
        health_file = tmp_path / "health.json"
        old_time = datetime.now() - timedelta(seconds=20)
        test_data = {
            "server_status": "running",
            "timestamp": old_time.isoformat()
        }
        
        with open(health_file, 'w') as f:
            json.dump(test_data, f)
            
        result = is_server_healthy(str(health_file), max_age_seconds=10)
        
        assert result is False
        
    def test_is_server_healthy_false_status(self, tmp_path):
        """Test server healthy check returning false for bad status."""
        health_file = tmp_path / "health.json"
        test_data = {
            "server_status": "error",
            "timestamp": datetime.now().isoformat()
        }
        
        with open(health_file, 'w') as f:
            json.dump(test_data, f)
            
        result = is_server_healthy(str(health_file))
        
        assert result is False
        
    def test_is_server_healthy_no_file(self, tmp_path):
        """Test server healthy check with no file."""
        health_file = tmp_path / "nonexistent.json"
        
        result = is_server_healthy(str(health_file))
        
        assert result is False
