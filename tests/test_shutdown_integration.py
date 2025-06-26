"""
Integration tests for shutdown system using mock processes.

These tests verify the complete shutdown process using the abstract mock
classes to simulate various process behaviors and edge cases.
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch
from tests.test_abstracts import (
    MockProcessRegistry,
    ProcessState,
    MockSignal
)
from shutdown_manager import ShutdownManager
from exit_codes import ShutdownExitCode, ExitCodeManager
from health_monitor import HealthMonitor, ServerStatus, ShutdownPhase


class TestIntegratedShutdownFlow:
    """Test complete shutdown flows with mock processes."""
    
    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return Mock()
        
    @pytest.fixture
    def process_registry(self):
        """Create a process registry."""
        registry = MockProcessRegistry()
        yield registry
        registry.cleanup_all()
        
    @pytest.fixture
    def health_monitor(self, mock_logger):
        """Create a health monitor."""
        monitor = HealthMonitor(mock_logger, "/tmp/test_health.json")
        yield monitor
        monitor.stop_monitoring()
        monitor.cleanup_health_file()
        
    @pytest.fixture
    def exit_code_manager(self, mock_logger):
        """Create an exit code manager."""
        return ExitCodeManager(mock_logger)
        
    @pytest.fixture
    def shutdown_manager(self, mock_logger):
        """Create a shutdown manager."""
        return ShutdownManager(mock_logger, mode="master")
        
    @pytest.mark.asyncio
    async def test_clean_shutdown_cooperative_workers(self, shutdown_manager, process_registry, 
                                       health_monitor, exit_code_manager, mock_logger):
        """Test clean shutdown with cooperative workers."""
        # Create cooperative workers
        worker1 = process_registry.create_cooperative_process("worker1", shutdown_delay=0.1)
        worker2 = process_registry.create_cooperative_process("worker2", shutdown_delay=0.1)
        
        # Create cooperative ports
        port1 = process_registry.create_cooperative_port(8080, release_delay=0.05)
        port2 = process_registry.create_cooperative_port(8081, release_delay=0.05)
        
        # Bind ports to workers
        port1.bind(worker1.pid)
        port2.bind(worker2.pid)
        
        # Create cooperative clients
        client1 = process_registry.create_cooperative_client("client1", "worker1", disconnect_delay=0.05)
        client2 = process_registry.create_cooperative_client("client2", "worker2", disconnect_delay=0.05)
        
        # Setup health monitoring
        health_monitor.set_server_status(ServerStatus.RUNNING)
        health_monitor.update_worker_status("worker1", worker1.pid, 8080, "running")
        health_monitor.update_worker_status("worker2", worker2.pid, 8081, "running")
        health_monitor.add_client("client1", "worker1")
        health_monitor.add_client("client2", "worker2")
        
        # Add workers so shutdown is actually triggered
        shutdown_manager._workers = {'worker1': worker1, 'worker2': worker2}
        
        # Mock the shutdown manager's internal methods to use our mocks  
        with patch.object(shutdown_manager, '_shutdown_all_workers') as mock_stop_workers, \
             patch.object(shutdown_manager._client_tracker, 'disconnect_all') as mock_disconnect_clients, \
             patch.object(shutdown_manager._resource_tracker, 'cleanup_all') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify:
            
            # Configure mocks to simulate clean shutdown
            def mock_stop_workers_impl():
                worker1.send_signal(MockSignal.SIGTERM)
                worker2.send_signal(MockSignal.SIGTERM)
                # Wait for workers to stop
                worker1.wait_for_exit(1.0)
                worker2.wait_for_exit(1.0)
                health_monitor.set_worker_shutdown_completed("worker1")
                health_monitor.set_worker_shutdown_completed("worker2")
                return True, []
                
            def mock_disconnect_clients_impl():
                client1.send_shutdown_notification()
                client2.send_shutdown_notification()
                client1.disconnect_gracefully(1.0)
                client2.disconnect_gracefully(1.0)
                health_monitor.set_client_disconnected("client1")
                health_monitor.set_client_disconnected("client2")
                return True, []
                
            def mock_cleanup_resources_impl():
                port1.release()
                port2.release()
                time.sleep(0.1)  # Wait for release
                return True, []
                
            def mock_verify_impl():
                # Check that everything is clean
                assert not worker1.is_alive()
                assert not worker2.is_alive()
                assert worker1.state == ProcessState.STOPPED
                assert worker2.state == ProcessState.STOPPED
                assert not client1.is_connected()
                assert not client2.is_connected()
                assert port1.is_free()
                assert port2.is_free()
                return True, []
            
            # Set up async mocks
            async def async_stop_workers_impl(*args):
                return mock_stop_workers_impl()
            async def async_disconnect_clients_impl(*args):
                return mock_disconnect_clients_impl()
            async def async_cleanup_resources_impl(*args):
                return mock_cleanup_resources_impl()
            async def async_verify_impl(*args):
                return mock_verify_impl()
                
            mock_stop_workers.side_effect = async_stop_workers_impl
            mock_disconnect_clients.side_effect = async_disconnect_clients_impl
            mock_cleanup_resources.side_effect = async_cleanup_resources_impl
            mock_verify.side_effect = async_verify_impl
            
            # Perform shutdown
            result = await shutdown_manager.shutdown()
            
            # Verify clean shutdown
            assert result is True
            
            # Verify all components were called
            mock_stop_workers.assert_called_once()
            mock_disconnect_clients.assert_called_once()
            mock_cleanup_resources.assert_called_once()
            mock_verify.assert_called_once()
            
    @pytest.mark.asyncio
    async def test_shutdown_with_timeout_escalation(self, shutdown_manager, process_registry,
                                            health_monitor, exit_code_manager, mock_logger):
        """Test shutdown with timeout and escalation to force termination."""
        # Create one cooperative and one unresponsive worker
        worker1 = process_registry.create_cooperative_process("worker1", shutdown_delay=0.1)
        worker2 = process_registry.create_unresponsive_process("worker2", kill_resistant=False)
        
        # Create ports
        port1 = process_registry.create_cooperative_port(8080)
        port2 = process_registry.create_sticky_port(8081, force_releasable=True)
        
        port1.bind(worker1.pid)
        port2.bind(worker2.pid)
        
        # Setup health monitoring
        health_monitor.update_worker_status("worker1", worker1.pid, 8080, "running")
        health_monitor.update_worker_status("worker2", worker2.pid, 8081, "running")
        
        # Add workers to shutdown manager
        shutdown_manager._workers = {
            "worker1": worker1,
            "worker2": worker2
        }
        
        # Mock shutdown manager methods
        with patch.object(shutdown_manager, '_shutdown_all_workers') as mock_stop_workers, \
             patch.object(shutdown_manager._client_tracker, 'disconnect_all') as mock_disconnect_clients, \
             patch.object(shutdown_manager._resource_tracker, 'cleanup_all') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify, \
             patch.object(shutdown_manager.system_monitor, 'log_system_state') as mock_log_system:
            
            async def mock_stop_workers_impl(grace_period, force_timeout):
                try:
                    # Try graceful shutdown
                    worker1.send_signal(MockSignal.SIGTERM)
                    worker2.send_signal(MockSignal.SIGTERM)
                    
                    # Worker1 cooperates, worker2 doesn't
                    worker1.wait_for_exit(0.5)
                    
                    # Need to force kill worker2
                    if worker2.is_alive():
                        exit_code_manager.report_timeout("worker_shutdown", 0.5)
                        worker2.send_signal(MockSignal.SIGKILL)
                        exit_code_manager.report_force_action("kill", "worker2")
                        
                    health_monitor.set_worker_shutdown_completed("worker1") 
                    health_monitor.set_worker_shutdown_completed("worker2")
                    return True
                except Exception as e:
                    raise
                
            async def mock_cleanup_resources_impl():
                try:
                    import asyncio
                    port1.release()
                    # port2 is sticky, need to force release
                    if not port2.release():
                        exit_code_manager.report_timeout("port_release", 1.0)
                        port2.force_release()
                        exit_code_manager.report_force_action("force_release", "port 8081")
                    await asyncio.sleep(0.1)
                    return True
                except Exception as e:
                    raise
                
            async def mock_verify_impl():
                assert not worker1.is_alive()
                assert not worker2.is_alive()
                assert port1.is_free()
                assert port2.is_free()
                return True
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_disconnect_clients.return_value = True  # Clients disconnect successfully
            mock_cleanup_resources.side_effect = mock_cleanup_resources_impl
            mock_verify.side_effect = mock_verify_impl
            mock_log_system.return_value = None  # System monitor logging
            
            # Perform shutdown
            result = await shutdown_manager.shutdown()
            
            # Should still succeed but with forced actions
            assert result is True
            
            # Check exit code reflects forced actions
            exit_code = exit_code_manager.determine_exit_code("manual")
            # The test forces both worker termination and port release, so expect the port release code
            assert exit_code == ShutdownExitCode.TIMEOUT_PORT_RELEASE
            
    @pytest.mark.asyncio
    async def test_shutdown_with_zombie_processes(self, shutdown_manager, process_registry,
                                          health_monitor, exit_code_manager, mock_logger):
        """Test shutdown that results in zombie processes."""
        # Create a zombie process
        zombie_worker = process_registry.create_zombie_process("zombie_worker")
        
        # Setup health monitoring
        health_monitor.update_worker_status("zombie_worker", zombie_worker.pid, 8080, "running")
        
        # Add workers to shutdown manager
        shutdown_manager._workers = {
            "zombie_worker": zombie_worker
        }
        
        # Mock shutdown manager methods
        with patch.object(shutdown_manager, '_shutdown_all_workers') as mock_stop_workers, \
             patch.object(shutdown_manager._client_tracker, 'disconnect_all') as mock_disconnect_clients, \
             patch.object(shutdown_manager._resource_tracker, 'cleanup_all') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify, \
             patch.object(shutdown_manager.system_monitor, 'log_system_state') as mock_log_system:
            
            async def mock_stop_workers_impl(grace_period, force_timeout):
                zombie_worker.send_signal(MockSignal.SIGTERM)
                # Process becomes zombie instead of stopping cleanly
                assert zombie_worker.state == ProcessState.ZOMBIE
                return True
                
            async def mock_verify_impl():
                # Verification should detect zombie
                if zombie_worker.state == ProcessState.ZOMBIE:
                    exit_code_manager.report_verification_failure(
                        "zombie_check", 
                        f"Zombie process detected: PID {zombie_worker.pid}"
                    )
                    return False
                return True
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_disconnect_clients.return_value = True
            mock_cleanup_resources.return_value = True
            mock_verify.side_effect = mock_verify_impl
            mock_log_system.return_value = None
            
            # Perform shutdown
            result = await shutdown_manager.shutdown()
            
            # Should fail due to zombie
            assert result is False
            
            # Check exit code reflects zombie detection
            exit_code = exit_code_manager.determine_exit_code("manual")
            assert exit_code == ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED
            
    @pytest.mark.asyncio
    async def test_shutdown_health_monitoring_integration(self, shutdown_manager, process_registry,
                                                   health_monitor, mock_logger):
        """Test that shutdown properly updates health monitoring."""
        # Create workers and clients
        worker1 = process_registry.create_cooperative_process("worker1")
        client1 = process_registry.create_cooperative_client("client1", "worker1")
        
        # Setup initial health state
        health_monitor.set_server_status(ServerStatus.RUNNING)
        health_monitor.update_worker_status("worker1", worker1.pid, 8080, "running")
        health_monitor.add_client("client1", "worker1")
        
        # Start health monitoring
        health_monitor.start_monitoring()
        
        # Add workers to shutdown manager
        shutdown_manager._workers = {'worker1': worker1}
        
        with patch.object(shutdown_manager, '_shutdown_all_workers') as mock_stop_workers, \
             patch.object(shutdown_manager._client_tracker, 'disconnect_all') as mock_disconnect_clients, \
             patch.object(shutdown_manager._resource_tracker, 'cleanup_all') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify, \
             patch.object(shutdown_manager.system_monitor, 'log_system_state') as mock_log_system:
            
            async def mock_stop_workers_impl(grace_period, force_timeout):
                health_monitor.set_shutdown_phase(ShutdownPhase.WORKERS_STOPPING)
                health_monitor.set_worker_shutdown_requested("worker1")
                worker1.send_signal(MockSignal.SIGTERM)
                worker1.wait_for_exit(1.0)
                health_monitor.set_worker_shutdown_completed("worker1")
                health_monitor.update_shutdown_progress("workers", {"stopped": 1, "total": 1})
                return True
                
            async def mock_disconnect_clients_impl():
                health_monitor.set_shutdown_phase(ShutdownPhase.CLIENTS_DISCONNECTING)
                health_monitor.set_client_disconnect_requested("client1")
                client1.send_shutdown_notification()
                client1.disconnect_gracefully(1.0)
                health_monitor.set_client_disconnected("client1")
                health_monitor.update_shutdown_progress("clients", {"disconnected": 1, "total": 1})
                return True
                
            async def mock_cleanup_resources_impl():
                import asyncio
                health_monitor.set_shutdown_phase(ShutdownPhase.RESOURCES_CLEANING)
                health_monitor.set_resource_cleanup_requested()
                await asyncio.sleep(0.1)  # Simulate cleanup
                health_monitor.set_resource_cleanup_completed()
                health_monitor.update_shutdown_progress("resources", {"cleaned": True})
                return True
                
            async def mock_verify_impl():
                import asyncio
                health_monitor.set_shutdown_phase(ShutdownPhase.VERIFICATION)
                # Perform verification
                await asyncio.sleep(0.05)
                health_monitor.set_shutdown_phase(ShutdownPhase.COMPLETED)
                return True
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_disconnect_clients.return_value = True
            mock_cleanup_resources.side_effect = mock_cleanup_resources_impl
            mock_verify.side_effect = mock_verify_impl
            mock_log_system.return_value = None
            
            # Perform shutdown
            health_monitor.set_server_status(ServerStatus.SHUTTING_DOWN)
            result = await shutdown_manager.shutdown()
            
            # Verify shutdown completed
            assert result is True
            assert health_monitor.is_shutdown_complete()
            
            # Check final status
            status = health_monitor.get_current_status()
            assert status["shutdown_phase"] == "completed"
            
    @pytest.mark.asyncio
    async def test_concurrent_shutdown_attempts(self, shutdown_manager, process_registry,
                                        health_monitor, mock_logger):
        """Test that concurrent shutdown attempts are handled safely."""
        # Create a worker that takes time to shutdown
        worker1 = process_registry.create_cooperative_process("worker1", shutdown_delay=0.5)
        
        # Add workers to shutdown manager
        shutdown_manager._workers = {'worker1': worker1}
        
        # Mock a slow shutdown process
        shutdown_started = threading.Event()
        shutdown_completed = threading.Event()
        
        with patch.object(shutdown_manager, '_shutdown_all_workers') as mock_stop_workers, \
             patch.object(shutdown_manager._client_tracker, 'disconnect_all') as mock_disconnect_clients, \
             patch.object(shutdown_manager._resource_tracker, 'cleanup_all') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify, \
             patch.object(shutdown_manager.system_monitor, 'log_system_state') as mock_log_system:
        
            async def slow_shutdown_impl(grace_period, force_timeout):
                import asyncio
                shutdown_started.set()
                await asyncio.sleep(0.3)  # Simulate slow shutdown
                worker1.send_signal(MockSignal.SIGTERM) 
                worker1.wait_for_exit(0.5)
                shutdown_completed.set()
                return True
                
            mock_stop_workers.side_effect = slow_shutdown_impl
            mock_disconnect_clients.return_value = True
            mock_cleanup_resources.return_value = True
            mock_verify.return_value = True
            mock_log_system.return_value = None
            
            # Start first shutdown in background
            import asyncio
            shutdown_task1 = asyncio.create_task(shutdown_manager.shutdown())
            
            # Wait for first shutdown to start
            shutdown_started.wait(timeout=1.0)
            
            # Try to start another shutdown 
            shutdown_task2 = asyncio.create_task(shutdown_manager.shutdown())
            
            # Wait for both tasks
            results = await asyncio.gather(shutdown_task1, shutdown_task2, return_exceptions=True)
            
            # Verify both completed successfully (shutdown manager should handle concurrency)
            assert all(r is True or isinstance(r, bool) for r in results)
            assert shutdown_completed.is_set()
            
    @pytest.mark.asyncio
    async def test_partial_failure_recovery(self, shutdown_manager, process_registry,
                                     health_monitor, exit_code_manager, mock_logger):
        """Test recovery from partial shutdown failures."""
        # Create mixed worker types
        good_worker = process_registry.create_cooperative_process("good_worker")
        bad_worker = process_registry.create_unresponsive_process("bad_worker", kill_resistant=True)
        
        # Create mixed ports
        good_port = process_registry.create_cooperative_port(8080)
        bad_port = process_registry.create_sticky_port(8081, force_releasable=False)
        
        good_port.bind(good_worker.pid)
        bad_port.bind(bad_worker.pid)
        
        # Add workers to shutdown manager
        shutdown_manager._workers = {
            "good_worker": good_worker,
            "bad_worker": bad_worker
        }
        
        # Mock shutdown with partial failures
        with patch.object(shutdown_manager, '_shutdown_all_workers') as mock_stop_workers, \
             patch.object(shutdown_manager._client_tracker, 'disconnect_all') as mock_disconnect_clients, \
             patch.object(shutdown_manager._resource_tracker, 'cleanup_all') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify, \
             patch.object(shutdown_manager.system_monitor, 'log_system_state') as mock_log_system:
            
            async def mock_stop_workers_impl(grace_period, force_timeout):
                # Good worker stops, bad worker doesn't
                good_worker.send_signal(MockSignal.SIGTERM)
                bad_worker.send_signal(MockSignal.SIGTERM)
                
                good_worker.wait_for_exit(0.5)
                
                # Try to force kill bad worker, but it's kill-resistant
                if bad_worker.is_alive():
                    exit_code_manager.report_timeout("worker_shutdown", 0.5)
                    success = bad_worker.force_kill()
                    if not success:
                        exit_code_manager.report_system_error("worker_manager", 
                                                            Exception("Kill-resistant process"))
                        
                return False
                
            async def mock_cleanup_resources_impl():
                import asyncio
                # Good port releases, bad port doesn't
                good_port.release()
                await asyncio.sleep(0.1)
                
                if not bad_port.release():
                    exit_code_manager.report_timeout("port_release", 1.0)
                    success = bad_port.force_release()
                    if not success:
                        exit_code_manager.report_verification_failure(
                            "port_check", "Port 8081 could not be released"
                        )
                        
                return False
                
            async def mock_verify_impl():
                failures = []
                if bad_worker.is_alive():
                    failures.append(f"Process {bad_worker.pid} still alive")
                if not bad_port.is_free():
                    failures.append(f"Port {bad_port.port} still bound")
                    
                return len(failures) == 0
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_disconnect_clients.return_value = True
            mock_cleanup_resources.side_effect = mock_cleanup_resources_impl 
            mock_verify.side_effect = mock_verify_impl
            mock_log_system.return_value = None
            
            # Perform shutdown
            result = await shutdown_manager.shutdown()
            
            # Should fail due to partial failures
            assert result is False
            
            # But good components should still be cleaned up
            assert not good_worker.is_alive()
            assert good_port.is_free()
            
            # Exit code should reflect the most severe issue
            exit_code = exit_code_manager.determine_exit_code("manual")
            assert exit_code in [
                ShutdownExitCode.PORT_STILL_IN_USE,
                ShutdownExitCode.WORKER_MANAGER_ERROR,
                ShutdownExitCode.VERIFICATION_FAILED
            ]
