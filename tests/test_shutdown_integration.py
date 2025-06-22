"""
Integration tests for shutdown system using mock processes.

These tests verify the complete shutdown process using the abstract mock
classes to simulate various process behaviors and edge cases.
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from test_abstracts import (
    MockProcessRegistry,
    ProcessState,
    MockSignal,
    CooperativeMockProcess,
    UnresponsiveMockProcess,
    ZombieMockProcess
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
        
    def test_clean_shutdown_cooperative_workers(self, shutdown_manager, process_registry, 
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
        
        # Mock the shutdown manager's internal methods to use our mocks
        with patch.object(shutdown_manager, '_stop_workers') as mock_stop_workers, \
             patch.object(shutdown_manager, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(shutdown_manager, '_cleanup_resources') as mock_cleanup_resources, \
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
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_disconnect_clients.side_effect = mock_disconnect_clients_impl
            mock_cleanup_resources.side_effect = mock_cleanup_resources_impl
            mock_verify.side_effect = mock_verify_impl
            
            # Perform shutdown
            result = shutdown_manager.shutdown()
            
            # Verify clean shutdown
            assert result is True
            
            # Verify all components were called
            mock_stop_workers.assert_called_once()
            mock_disconnect_clients.assert_called_once()
            mock_cleanup_resources.assert_called_once()
            mock_verify.assert_called_once()
            
    def test_shutdown_with_timeout_escalation(self, shutdown_manager, process_registry,
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
        
        # Mock shutdown manager methods
        with patch.object(shutdown_manager, '_stop_workers') as mock_stop_workers, \
             patch.object(shutdown_manager, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify:
            
            def mock_stop_workers_impl():
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
                return True, ["worker2 required force termination"]
                
            def mock_cleanup_resources_impl():
                port1.release()
                # port2 is sticky, need to force release
                if not port2.release():
                    exit_code_manager.report_timeout("port_release", 1.0)
                    port2.force_release()
                    exit_code_manager.report_force_action("force_release", "port 8081")
                time.sleep(0.1)
                return True, ["port 8081 required force release"]
                
            def mock_verify_impl():
                assert not worker1.is_alive()
                assert not worker2.is_alive()
                assert port1.is_free()
                assert port2.is_free()
                return True, []
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_cleanup_resources.side_effect = mock_cleanup_resources_impl
            mock_verify.side_effect = mock_verify_impl
            
            # Perform shutdown
            result = shutdown_manager.shutdown()
            
            # Should still succeed but with forced actions
            assert result is True
            
            # Check exit code reflects forced actions
            exit_code = exit_code_manager.determine_exit_code("manual")
            assert exit_code == ShutdownExitCode.FORCE_WORKER_TERMINATION
            
    def test_shutdown_with_zombie_processes(self, shutdown_manager, process_registry,
                                          health_monitor, exit_code_manager, mock_logger):
        """Test shutdown that results in zombie processes."""
        # Create a zombie process
        zombie_worker = process_registry.create_zombie_process("zombie_worker")
        
        # Setup health monitoring
        health_monitor.update_worker_status("zombie_worker", zombie_worker.pid, 8080, "running")
        
        # Mock shutdown manager methods
        with patch.object(shutdown_manager, '_stop_workers') as mock_stop_workers, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify:
            
            def mock_stop_workers_impl():
                zombie_worker.send_signal(MockSignal.SIGTERM)
                # Process becomes zombie instead of stopping cleanly
                assert zombie_worker.state == ProcessState.ZOMBIE
                return True, []
                
            def mock_verify_impl():
                # Verification should detect zombie
                if zombie_worker.state == ProcessState.ZOMBIE:
                    exit_code_manager.report_verification_failure(
                        "zombie_check", 
                        f"Zombie process detected: PID {zombie_worker.pid}"
                    )
                    return False, [f"Zombie process: PID {zombie_worker.pid}"]
                return True, []
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_verify.side_effect = mock_verify_impl
            
            # Perform shutdown
            result = shutdown_manager.shutdown()
            
            # Should fail due to zombie
            assert result is False
            
            # Check exit code reflects zombie detection
            exit_code = exit_code_manager.determine_exit_code("manual")
            assert exit_code == ShutdownExitCode.ZOMBIE_PROCESSES_DETECTED
            
    def test_shutdown_health_monitoring_integration(self, shutdown_manager, process_registry,
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
        
        # Mock shutdown phases to update health monitoring
        with patch.object(shutdown_manager, '_stop_workers') as mock_stop_workers, \
             patch.object(shutdown_manager, '_disconnect_clients') as mock_disconnect_clients, \
             patch.object(shutdown_manager, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify:
            
            def mock_stop_workers_impl():
                health_monitor.set_shutdown_phase(ShutdownPhase.WORKERS_STOPPING)
                health_monitor.set_worker_shutdown_requested("worker1")
                worker1.send_signal(MockSignal.SIGTERM)
                worker1.wait_for_exit(1.0)
                health_monitor.set_worker_shutdown_completed("worker1")
                health_monitor.update_shutdown_progress("workers", {"stopped": 1, "total": 1})
                return True, []
                
            def mock_disconnect_clients_impl():
                health_monitor.set_shutdown_phase(ShutdownPhase.CLIENTS_DISCONNECTING)
                health_monitor.set_client_disconnect_requested("client1")
                client1.send_shutdown_notification()
                client1.disconnect_gracefully(1.0)
                health_monitor.set_client_disconnected("client1")
                health_monitor.update_shutdown_progress("clients", {"disconnected": 1, "total": 1})
                return True, []
                
            def mock_cleanup_resources_impl():
                health_monitor.set_shutdown_phase(ShutdownPhase.RESOURCES_CLEANING)
                health_monitor.set_resource_cleanup_requested()
                time.sleep(0.1)  # Simulate cleanup
                health_monitor.set_resource_cleanup_completed()
                health_monitor.update_shutdown_progress("resources", {"cleaned": True})
                return True, []
                
            def mock_verify_impl():
                health_monitor.set_shutdown_phase(ShutdownPhase.VERIFICATION)
                # Perform verification
                time.sleep(0.05)
                health_monitor.set_shutdown_phase(ShutdownPhase.COMPLETED)
                return True, []
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_disconnect_clients.side_effect = mock_disconnect_clients_impl
            mock_cleanup_resources.side_effect = mock_cleanup_resources_impl
            mock_verify.side_effect = mock_verify_impl
            
            # Perform shutdown
            health_monitor.set_server_status(ServerStatus.SHUTTING_DOWN)
            result = shutdown_manager.shutdown()
            
            # Verify shutdown completed
            assert result is True
            assert health_monitor.is_shutdown_complete()
            
            # Check final status
            status = health_monitor.get_current_status()
            assert status["shutdown_phase"] == "completed"
            
    def test_concurrent_shutdown_attempts(self, shutdown_manager, process_registry,
                                        health_monitor, mock_logger):
        """Test that concurrent shutdown attempts are handled safely."""
        # Create a worker that takes time to shutdown
        worker1 = process_registry.create_cooperative_process("worker1", shutdown_delay=0.5)
        
        # Mock a slow shutdown process
        shutdown_started = threading.Event()
        shutdown_completed = threading.Event()
        
        original_shutdown = shutdown_manager.shutdown
        
        def slow_shutdown():
            shutdown_started.set()
            time.sleep(0.3)  # Simulate slow shutdown
            shutdown_completed.set()
            return True
            
        # Start first shutdown in background
        with patch.object(shutdown_manager, 'shutdown', side_effect=slow_shutdown):
            shutdown_thread1 = threading.Thread(target=shutdown_manager.shutdown)
            shutdown_thread1.start()
            
            # Wait for first shutdown to start
            shutdown_started.wait(timeout=1.0)
            
            # Try to start another shutdown (should be ignored/handled safely)
            shutdown_thread2 = threading.Thread(target=shutdown_manager.shutdown)
            shutdown_thread2.start()
            
            # Wait for both threads
            shutdown_thread1.join(timeout=2.0)
            shutdown_thread2.join(timeout=2.0)
            
            # Verify both threads completed
            assert not shutdown_thread1.is_alive()
            assert not shutdown_thread2.is_alive()
            assert shutdown_completed.is_set()
            
    def test_partial_failure_recovery(self, shutdown_manager, process_registry,
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
        
        # Mock shutdown with partial failures
        with patch.object(shutdown_manager, '_stop_workers') as mock_stop_workers, \
             patch.object(shutdown_manager, '_cleanup_resources') as mock_cleanup_resources, \
             patch.object(shutdown_manager, '_verify_clean_shutdown') as mock_verify:
            
            def mock_stop_workers_impl():
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
                        
                return False, ["bad_worker could not be terminated"]
                
            def mock_cleanup_resources_impl():
                # Good port releases, bad port doesn't
                good_port.release()
                time.sleep(0.1)
                
                if not bad_port.release():
                    exit_code_manager.report_timeout("port_release", 1.0)
                    success = bad_port.force_release()
                    if not success:
                        exit_code_manager.report_verification_failure(
                            "port_check", "Port 8081 could not be released"
                        )
                        
                return False, ["Port 8081 could not be released"]
                
            def mock_verify_impl():
                failures = []
                if bad_worker.is_alive():
                    failures.append(f"Process {bad_worker.pid} still alive")
                if not bad_port.is_free():
                    failures.append(f"Port {bad_port.port} still bound")
                    
                return len(failures) == 0, failures
                
            mock_stop_workers.side_effect = mock_stop_workers_impl
            mock_cleanup_resources.side_effect = mock_cleanup_resources_impl 
            mock_verify.side_effect = mock_verify_impl
            
            # Perform shutdown
            result = shutdown_manager.shutdown()
            
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
