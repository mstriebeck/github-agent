"""
Tests for the consolidated ShutdownManager functionality.
"""

import pytest
from unittest.mock import Mock, patch
from shutdown_manager import ShutdownManager
from exit_codes import ShutdownExitCode
from health_monitor import ServerStatus, ShutdownPhase


class TestShutdownManager:
    """Test ShutdownManager class."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def manager_master(self, mock_logger):
        """Create a ShutdownManager in master mode."""
        return ShutdownManager(mock_logger, mode="master")
        
    @pytest.fixture
    def manager_worker(self, mock_logger):
        """Create a ShutdownManager in worker mode."""
        return ShutdownManager(mock_logger, mode="worker")
        
    def test_initialization_master(self, manager_master, mock_logger):
        """Test initialization in master mode."""
        assert manager_master.logger == mock_logger
        assert manager_master.mode == "master"
        assert manager_master._exit_code_manager is not None
        assert manager_master._health_monitor is not None
        assert manager_master._resource_tracker is not None
        assert manager_master._client_tracker is not None
        assert manager_master._shutdown_initiated is False
        
    def test_initialization_worker(self, manager_worker, mock_logger):
        """Test initialization in worker mode."""
        assert manager_worker.logger == mock_logger
        assert manager_worker.mode == "worker"
        assert manager_worker._exit_code_manager is not None
        assert manager_worker._health_monitor is not None
        assert manager_worker._resource_tracker is not None
        assert manager_worker._client_tracker is not None
        assert manager_worker._shutdown_initiated is False
        
    def test_initialization_invalid_mode(self, mock_logger):
        """Test initialization with invalid mode."""
        with pytest.raises(ValueError, match="Mode must be 'master' or 'worker'"):
            ShutdownManager(mock_logger, mode="invalid")
            
    @pytest.mark.asyncio
    async def test_shutdown_already_initiated(self, manager_master, mock_logger):
        """Test that multiple shutdown calls are handled safely."""
        manager_master._shutdown_initiated = True
        manager_master._shutdown_reason = "previous"
        
        result = await manager_master.shutdown("new_reason")
        
        assert result is False
        mock_logger.warning.assert_called_with(
            "Shutdown already initiated (reason: previous), ignoring new request (new_reason)"
        )
        
    @patch('shutdown_manager.signal.signal')
    def test_setup_signal_handlers(self, mock_signal, manager_master):
        """Test signal handler setup."""
        manager_master._setup_signal_handlers()
        
        # Should register handlers for SIGTERM and SIGINT
        assert mock_signal.call_count == 2
        calls = mock_signal.call_args_list
        signals_registered = [call[0][0] for call in calls]
        
        import signal
        assert signal.SIGTERM in signals_registered
        assert signal.SIGINT in signals_registered
        
    def test_signal_handler_calls_shutdown(self, manager_master, mock_logger):
        """Test that signal handler calls shutdown."""
        import signal
        
        with patch.object(manager_master, 'shutdown') as mock_shutdown:
            # Call the signal handler directly
            manager_master._signal_handler(signal.SIGTERM, None)
            
            mock_shutdown.assert_called_once_with(f"signal_{signal.SIGTERM}")
            
    @pytest.mark.asyncio
    async def test_master_shutdown_phases(self, manager_master, mock_logger):
        """Test master shutdown goes through all phases."""
        with patch.object(manager_master, '_stop_workers') as mock_stop_workers, \
             patch.object(manager_master, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(manager_master, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(manager_master, '_verify_clean_shutdown') as mock_verify, \
             patch.object(manager_master._health_monitor, 'set_shutdown_phase') as mock_set_phase:
            
            # Configure mocks to return success
            mock_stop_workers.return_value = (True, [])
            mock_disconnect_clients.return_value = (True, [])
            mock_cleanup_resources.return_value = (True, [])
            mock_verify.return_value = (True, [])
            
            result = await manager_master.shutdown("test")
            
            assert result is True
            
            # Check that all phases were called
            mock_stop_workers.assert_called_once()
            mock_disconnect_clients.assert_called_once()
            mock_cleanup_resources.assert_called_once()
            mock_verify.assert_called_once()
            
            # Check shutdown phases were set
            phase_calls = mock_set_phase.call_args_list
            phases_set = [call[0][0] for call in phase_calls]
            assert ShutdownPhase.WORKERS_STOPPING in phases_set
            assert ShutdownPhase.CLIENTS_DISCONNECTING in phases_set
            assert ShutdownPhase.RESOURCES_CLEANING in phases_set
            assert ShutdownPhase.VERIFICATION in phases_set
            
    @pytest.mark.asyncio
    async def test_worker_shutdown_phases(self, manager_worker, mock_logger):
        """Test worker shutdown skips worker management phase."""
        with patch.object(manager_worker, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(manager_worker, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(manager_worker, '_verify_clean_shutdown') as mock_verify, \
             patch.object(manager_worker._health_monitor, 'set_shutdown_phase') as mock_set_phase:
            
            # Configure mocks to return success
            mock_disconnect_clients.return_value = (True, [])
            mock_cleanup_resources.return_value = (True, [])
            mock_verify.return_value = (True, [])
            
            result = await manager_worker.shutdown("test")
            
            assert result is True
            
            # Check that worker management was skipped
            mock_disconnect_clients.assert_called_once()
            mock_cleanup_resources.assert_called_once()
            mock_verify.assert_called_once()
            
            # Check appropriate phases were set (no WORKERS_STOPPING)
            phase_calls = mock_set_phase.call_args_list
            phases_set = [call[0][0] for call in phase_calls]
            assert ShutdownPhase.WORKERS_STOPPING not in phases_set
            assert ShutdownPhase.CLIENTS_DISCONNECTING in phases_set
            
    @pytest.mark.asyncio
    async def test_shutdown_phase_failure_stops_process(self, manager_master, mock_logger):
        """Test that phase failure stops the shutdown process."""
        with patch.object(manager_master, '_stop_workers') as mock_stop_workers, \
             patch.object(manager_master, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(manager_master, '_cleanup_resources') as mock_cleanup_resources:
            
            # Make workers phase fail
            mock_stop_workers.return_value = (False, ["Worker failed to stop"])
            
            result = await manager_master.shutdown("test")
            
            assert result is False
            
            # Should stop after workers phase fails
            mock_stop_workers.assert_called_once()
            mock_disconnect_clients.assert_not_called()
            mock_cleanup_resources.assert_not_called()
            
    @pytest.mark.asyncio
    async def test_exit_code_determination(self, manager_master, mock_logger):
        """Test exit code determination from shutdown result."""
        with patch.object(manager_master, '_stop_workers') as mock_stop_workers, \
             patch.object(manager_master, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(manager_master, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(manager_master, '_verify_clean_shutdown') as mock_verify, \
             patch.object(manager_master._exit_code_manager, 'determine_exit_code') as mock_determine:
            
            # Configure successful shutdown
            mock_stop_workers.return_value = (True, [])
            mock_disconnect_clients.return_value = (True, [])
            mock_cleanup_resources.return_value = (True, [])
            mock_verify.return_value = (True, [])
            mock_determine.return_value = ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN
            
            result = await manager_master.shutdown("manual")
            
            assert result is True
            mock_determine.assert_called_once_with("manual")
            
    @pytest.mark.asyncio
    async def test_health_monitoring_integration(self, manager_master, mock_logger):
        """Test health monitoring is properly integrated."""
        with patch.object(manager_master._health_monitor, 'set_server_status') as mock_set_status, \
             patch.object(manager_master._health_monitor, 'set_shutdown_phase') as mock_set_phase, \
             patch.object(manager_master, '_stop_workers') as mock_stop_workers, \
             patch.object(manager_master, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(manager_master, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(manager_master, '_verify_clean_shutdown') as mock_verify:
            
            # Configure successful shutdown
            mock_stop_workers.return_value = (True, [])
            mock_disconnect_clients.return_value = (True, [])
            mock_cleanup_resources.return_value = (True, [])
            mock_verify.return_value = (True, [])
            
            result = await manager_master.shutdown("test")
            
            assert result is True
            
            # Check health monitoring calls
            mock_set_status.assert_called_with(ServerStatus.SHUTTING_DOWN)
            
            # Should set completion phase at the end
            phase_calls = mock_set_phase.call_args_list
            final_phase = phase_calls[-1][0][0]
            assert final_phase == ShutdownPhase.COMPLETED


class TestResourceTracker:
    """Test the internal _ResourceTracker class."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def shutdown_manager(self, mock_logger):
        """Create a ShutdownManager."""
        return ShutdownManager(mock_logger, mode="master")
        
    @pytest.fixture
    def resource_tracker(self, shutdown_manager):
        """Get the resource tracker from shutdown manager."""
        return shutdown_manager._resource_tracker
        
    def test_cleanup_resources_success(self, resource_tracker, mock_logger):
        """Test successful resource cleanup."""
        with patch('shutdown_manager.psutil.Process') as mock_process_class:
            # Mock process with resources
            mock_process = Mock()
            mock_process.open_files.return_value = []
            mock_process.connections.return_value = []
            mock_process_class.return_value = mock_process
            
            success, issues = resource_tracker.cleanup_resources()
            
            assert success is True
            assert issues == []
            
    def test_cleanup_resources_with_open_files(self, resource_tracker, mock_logger):
        """Test resource cleanup with open files."""
        with patch('shutdown_manager.psutil.Process') as mock_process_class:
            # Mock process with open files
            mock_file = Mock()
            mock_file.path = "/tmp/test.log"
            mock_process = Mock()
            mock_process.open_files.return_value = [mock_file]
            mock_process.connections.return_value = []
            mock_process_class.return_value = mock_process
            
            success, issues = resource_tracker.cleanup_resources()
            
            # Should still succeed but log warning
            assert success is True
            assert len(issues) > 0
            assert "open files" in issues[0].lower()
            
    def test_verify_ports_released_success(self, resource_tracker, mock_logger):
        """Test port verification when all ports are free."""
        ports = [8080, 8081]
        
        with patch('shutdown_manager.socket.socket') as mock_socket_class:
            # Mock successful binding (ports are free)
            mock_socket = Mock()
            mock_socket_class.return_value.__enter__.return_value = mock_socket
            
            success, issues = resource_tracker.verify_ports_released(ports)
            
            assert success is True
            assert issues == []
            
    def test_verify_ports_released_failure(self, resource_tracker, mock_logger):
        """Test port verification when ports are still bound."""
        ports = [8080, 8081]
        
        with patch('shutdown_manager.socket.socket') as mock_socket_class:
            # Mock failed binding (ports still in use)
            mock_socket = Mock()
            mock_socket.bind.side_effect = OSError("Address already in use")
            mock_socket_class.return_value.__enter__.return_value = mock_socket
            
            success, issues = resource_tracker.verify_ports_released(ports)
            
            assert success is False
            assert len(issues) > 0
            assert "8080" in str(issues)


class TestClientTracker:
    """Test the internal _ClientTracker class."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def shutdown_manager(self, mock_logger):
        """Create a ShutdownManager."""
        return ShutdownManager(mock_logger, mode="worker")
        
    @pytest.fixture
    def client_tracker(self, shutdown_manager):
        """Get the client tracker from shutdown manager."""
        return shutdown_manager._client_tracker
        
    def test_add_client(self, client_tracker):
        """Test adding a client."""
        client_tracker.add_client("client1", Mock())
        
        assert "client1" in client_tracker._active_clients
        assert len(client_tracker._active_clients) == 1
        
    def test_remove_client(self, client_tracker):
        """Test removing a client."""
        mock_connection = Mock()
        client_tracker.add_client("client1", mock_connection)
        client_tracker.remove_client("client1")
        
        assert "client1" not in client_tracker._active_clients
        assert len(client_tracker._active_clients) == 0
        
    def test_disconnect_all_clients_success(self, client_tracker, mock_logger):
        """Test disconnecting all clients successfully."""
        # Add mock clients
        mock_conn1 = Mock()
        mock_conn2 = Mock()
        client_tracker.add_client("client1", mock_conn1)
        client_tracker.add_client("client2", mock_conn2)
        
        success, issues = client_tracker.disconnect_all_clients(timeout=1.0)
        
        assert success is True
        assert issues == []
        
        # Check that connections were closed
        mock_conn1.close.assert_called_once()
        mock_conn2.close.assert_called_once()
        
    def test_disconnect_all_clients_with_error(self, client_tracker, mock_logger):
        """Test disconnecting clients with connection errors."""
        # Add mock client that raises error on close
        mock_conn = Mock()
        mock_conn.close.side_effect = Exception("Connection error")
        client_tracker.add_client("client1", mock_conn)
        
        success, issues = client_tracker.disconnect_all_clients(timeout=1.0)
        
        # Should handle errors gracefully
        assert success is True  # Overall success despite individual errors
        assert len(issues) > 0
        assert "client1" in issues[0]
        
    def test_get_client_count(self, client_tracker):
        """Test getting client count."""
        assert client_tracker.get_client_count() == 0
        
        client_tracker.add_client("client1", Mock())
        assert client_tracker.get_client_count() == 1
        
        client_tracker.add_client("client2", Mock()) 
        assert client_tracker.get_client_count() == 2
        
        client_tracker.remove_client("client1")
        assert client_tracker.get_client_count() == 1


class TestShutdownManagerErrorHandling:
    """Test error handling in ShutdownManager."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def manager(self, mock_logger):
        """Create a ShutdownManager."""
        return ShutdownManager(mock_logger, mode="master")
        
    @pytest.mark.asyncio
    async def test_exception_in_stop_workers(self, manager, mock_logger):
        """Test exception handling in worker stopping phase."""
        with patch.object(manager, '_stop_workers') as mock_stop_workers, \
             patch.object(manager._exit_code_manager, 'report_system_error') as mock_report_error:
            
            # Make stop_workers raise exception
            test_exception = Exception("Worker stop failed")
            mock_stop_workers.side_effect = test_exception
            
            result = await manager.shutdown("test")
            
            assert result is False
            mock_report_error.assert_called_once_with("worker_manager", test_exception)
            
    @pytest.mark.asyncio
    async def test_exception_in_disconnect_clients(self, manager, mock_logger):
        """Test exception handling in client disconnection phase."""
        with patch.object(manager, '_stop_workers') as mock_stop_workers, \
             patch.object(manager, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(manager._exit_code_manager, 'report_system_error') as mock_report_error:
            
            # Make workers succeed but clients fail
            mock_stop_workers.return_value = (True, [])
            test_exception = Exception("Client disconnect failed")
            mock_disconnect_clients.side_effect = test_exception
            
            result = await manager.shutdown("test")
            
            assert result is False
            mock_report_error.assert_called_with("client_manager", test_exception)
            
    @pytest.mark.asyncio
    async def test_exception_in_cleanup_resources(self, manager, mock_logger):
        """Test exception handling in resource cleanup phase."""
        with patch.object(manager, '_stop_workers') as mock_stop_workers, \
             patch.object(manager, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(manager, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(manager._exit_code_manager, 'report_system_error') as mock_report_error:
            
            # Make earlier phases succeed but cleanup fail
            mock_stop_workers.return_value = (True, [])
            mock_disconnect_clients.return_value = (True, [])
            test_exception = Exception("Resource cleanup failed")
            mock_cleanup_resources.side_effect = test_exception
            
            result = await manager.shutdown("test")
            
            assert result is False
            mock_report_error.assert_called_with("resource_manager", test_exception)
            
    @pytest.mark.asyncio
    async def test_exception_in_verification(self, manager, mock_logger):
        """Test exception handling in verification phase."""
        with patch.object(manager, '_stop_workers') as mock_stop_workers, \
             patch.object(manager, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(manager, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(manager, '_verify_clean_shutdown') as mock_verify, \
             patch.object(manager._exit_code_manager, 'report_system_error') as mock_report_error:
            
            # Make all phases succeed except verification
            mock_stop_workers.return_value = (True, [])
            mock_disconnect_clients.return_value = (True, [])
            mock_cleanup_resources.return_value = (True, [])
            test_exception = Exception("Verification failed")
            mock_verify.side_effect = test_exception
            
            result = await manager.shutdown("test")
            
            assert result is False
            mock_report_error.assert_called_with("verification", test_exception)
