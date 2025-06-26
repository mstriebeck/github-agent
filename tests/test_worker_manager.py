#!/usr/bin/env python3
"""
Test suite for worker_manager.py

This module tests the enhanced worker process management including
process groups, graceful shutdown, and comprehensive verification.
"""

import unittest
import asyncio
import logging
import time
import socket
import sys
import os
from unittest.mock import Mock, patch

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker_manager import WorkerManager, WorkerProcess
from shutdown_core import IProcessSpawner


class MockProcessSpawner(IProcessSpawner):
    """Mock process spawner for testing"""
    
    def __init__(self):
        self.spawned_processes = []
        self.process_states = {}  # pid -> exit_code (None if running)
        self.next_pid = 1000
    
    def spawn_process(self, command, preexec_fn=None):
        """Mock process spawning"""
        mock_process = Mock()
        mock_process.pid = self.next_pid
        self.next_pid += 1
        
        # Track this process as running
        self.process_states[mock_process.pid] = None
        self.spawned_processes.append(mock_process)
        
        return mock_process
    
    def wait_for_process(self, process_handle, timeout):
        """Mock process waiting"""
        return self.process_states.get(process_handle.pid, 0)
    
    def terminate_process(self, process_handle):
        """Mock process termination"""
        self.process_states[process_handle.pid] = 0  # Mark as terminated
    
    def kill_process_group(self, pid):
        """Mock process group killing"""
        self.process_states[pid] = -9  # Mark as killed
    
    def get_process_poll_status(self, process_handle):
        """Mock process polling"""
        return self.process_states.get(process_handle.pid)
    
    def set_process_exit_code(self, pid, exit_code):
        """Helper method to set process exit code for testing"""
        self.process_states[pid] = exit_code


class TestWorkerManager(unittest.TestCase):
    """Test the WorkerManager class"""
    
    def setUp(self):
        self.logger = logging.getLogger(f"test_worker_manager_{int(time.time() * 1000000)}")
        self.logger.setLevel(logging.DEBUG)
        
        # Add basic handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        self.mock_spawner = MockProcessSpawner()
        self.manager = WorkerManager(self.logger, self.mock_spawner)
    
    def tearDown(self):
        # Cleanup logger
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
    
    def test_add_worker(self):
        """Test adding a worker to the manager"""
        worker = WorkerProcess(
            repo_name="test-repo",
            port=8000,
            path="/path/to/repo",
            description="Test repository"
        )
        
        self.manager.add_worker(worker)
        
        # Verify worker was added
        self.assertEqual(self.manager.get_worker_count(), 1)
        retrieved_worker = self.manager.get_worker("test-repo")
        self.assertIsNotNone(retrieved_worker)
        self.assertEqual(retrieved_worker.repo_name, "test-repo")
        self.assertEqual(retrieved_worker.port, 8000)
    
    def test_remove_worker(self):
        """Test removing a worker from the manager"""
        worker = WorkerProcess(
            repo_name="test-repo",
            port=8000,
            path="/path/to/repo",
            description="Test repository"
        )
        
        self.manager.add_worker(worker)
        self.assertEqual(self.manager.get_worker_count(), 1)
        
        removed_worker = self.manager.remove_worker("test-repo")
        self.assertIsNotNone(removed_worker)
        self.assertEqual(removed_worker.repo_name, "test-repo")
        self.assertEqual(self.manager.get_worker_count(), 0)
    
    @patch('worker_manager.WorkerManager._is_port_available')
    def test_start_worker_success(self, mock_port_check):
        """Test successful worker startup"""
        mock_port_check.return_value = True  # Port is available
        
        worker = WorkerProcess(
            repo_name="test-repo",
            port=8000,
            path="/path/to/repo",
            description="Test repository"
        )
        self.manager.add_worker(worker)
        
        command = ["python", "test_worker.py"]
        result = self.manager.start_worker(worker, command)
        
        self.assertTrue(result)
        self.assertIsNotNone(worker.process)
        self.assertIsNotNone(worker.start_time)
        self.assertEqual(len(self.mock_spawner.spawned_processes), 1)
    
    @patch('worker_manager.WorkerManager._is_port_available')
    def test_start_worker_port_unavailable(self, mock_port_check):
        """Test worker startup when port is unavailable"""
        mock_port_check.return_value = False  # Port is not available
        
        worker = WorkerProcess(
            repo_name="test-repo",
            port=8000,
            path="/path/to/repo",
            description="Test repository"
        )
        self.manager.add_worker(worker)
        
        command = ["python", "test_worker.py"]
        result = self.manager.start_worker(worker, command)
        
        self.assertFalse(result)
        self.assertIsNone(worker.process)
        self.assertEqual(len(self.mock_spawner.spawned_processes), 0)
    
    def test_is_worker_healthy(self):
        """Test worker health checking"""
        worker = WorkerProcess(
            repo_name="test-repo",
            port=8000,
            path="/path/to/repo",
            description="Test repository"
        )
        
        # Worker without process should not be healthy
        self.assertFalse(self.manager.is_worker_healthy(worker))
        
        # Add a mock process
        mock_process = Mock()
        mock_process.pid = 1234
        worker.process = mock_process
        
        # Mock process as running
        self.mock_spawner.process_states[1234] = None
        
        # Mock port as not available (worker is using it)
        with patch.object(self.manager, '_is_port_available', return_value=False):
            self.assertTrue(self.manager.is_worker_healthy(worker))
        
        # Mock process as terminated
        self.mock_spawner.process_states[1234] = 0
        self.assertFalse(self.manager.is_worker_healthy(worker))
    
    @patch('worker_manager.WorkerManager._is_port_available')

    async def async_test_shutdown_single_worker_graceful(self, mock_port_check):
        """Test graceful worker shutdown"""
        mock_port_check.return_value = True  # Port becomes available after shutdown
        
        worker = WorkerProcess(
            repo_name="test-repo",
            port=8000,
            path="/path/to/repo",
            description="Test repository",
            graceful_timeout=1.0,
            shutdown_timeout=5.0
        )
        
        # Create a mock process
        mock_process = Mock()
        mock_process.pid = 1234
        worker.process = mock_process
        self.mock_spawner.process_states[1234] = None  # Running
        
        self.manager.add_worker(worker)
        
        # Mock the HTTP shutdown request to succeed
        async def mock_shutdown_request(port):
            # Simulate graceful shutdown by marking process as terminated
            self.mock_spawner.process_states[1234] = 0
        
        with patch.object(self.manager, '_send_worker_shutdown_request', side_effect=mock_shutdown_request):
            result = await self.manager._shutdown_single_worker_async("test-repo", worker, 1, 1)
        
        self.assertTrue(result)
        self.assertEqual(self.mock_spawner.process_states[1234], 0)  # Process should be terminated
    

    async def async_test_shutdown_all_workers(self):
        """Test shutting down all workers"""
        # Add multiple workers
        workers = []
        for i in range(3):
            worker = WorkerProcess(
                repo_name=f"repo-{i}",
                port=8000 + i,
                path=f"/path/to/repo-{i}",
                description=f"Test repository {i}",
                graceful_timeout=0.1,
                shutdown_timeout=0.5
            )
            
            # Mock processes
            mock_process = Mock()
            mock_process.pid = 1000 + i
            worker.process = mock_process
            self.mock_spawner.process_states[1000 + i] = None  # Running
            
            workers.append(worker)
            self.manager.add_worker(worker)
        
        # Mock port availability checks
        with patch.object(self.manager, '_is_port_available', return_value=True):
            # Mock HTTP shutdown requests to succeed by terminating processes
            async def mock_shutdown_request(port):
                for worker in workers:
                    if worker.port == port:
                        self.mock_spawner.process_states[worker.process.pid] = 0
                        break
            
            with patch.object(self.manager, '_send_worker_shutdown_request', side_effect=mock_shutdown_request):
                result = await self.manager.shutdown_all_workers()
        
        self.assertTrue(result)
        self.assertEqual(self.manager.get_worker_count(), 0)  # All workers should be removed
        
        # All processes should be terminated
        for i in range(3):
            self.assertEqual(self.mock_spawner.process_states[1000 + i], 0)
    
    def test_get_worker_status(self):
        """Test getting worker status information"""
        worker1 = WorkerProcess(
            repo_name="repo-1",
            port=8000,
            path="/path/to/repo-1",
            description="Test repository 1"
        )
        worker2 = WorkerProcess(
            repo_name="repo-2",
            port=8001,
            path="/path/to/repo-2",
            description="Test repository 2"
        )
        
        # Add mock processes
        mock_process1 = Mock()
        mock_process1.pid = 1001
        worker1.process = mock_process1
        worker1.start_time = time.time()
        
        worker2.process = None  # No process
        
        self.manager.add_worker(worker1)
        self.manager.add_worker(worker2)
        
        status = self.manager.get_worker_status()
        
        self.assertEqual(len(status), 2)
        self.assertIn("repo-1", status)
        self.assertIn("repo-2", status)
        
        self.assertEqual(status["repo-1"]["port"], 8000)
        self.assertEqual(status["repo-1"]["pid"], 1001)
        self.assertIsNotNone(status["repo-1"]["start_time"])
        
        self.assertEqual(status["repo-2"]["port"], 8001)
        self.assertIsNone(status["repo-2"]["pid"])
    
    def test_port_availability_check(self):
        """Test port availability checking"""
        # Test with a port that should be available (high port number)
        high_port = 65432
        self.assertTrue(self.manager._is_port_available(high_port))
        
        # Test with a port in use (create a socket and bind to it)
        test_port = 0  # Let the OS choose
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', test_port))
            actual_port = s.getsockname()[1]
            
            # Create another socket to test the same port
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # This should fail because port is in use
                test_socket.bind(('127.0.0.1', actual_port))
                test_socket.close()
                # If we get here, the test setup isn't working as expected
                self.fail("Expected port to be unavailable")
            except OSError:
                # This is expected - port should be in use
                pass
            finally:
                test_socket.close()
        
        # Port should be available again after socket is closed
        self.assertTrue(self.manager._is_port_available(actual_port))


class TestWorkerProcess(unittest.TestCase):
    """Test the WorkerProcess dataclass"""
    
    def test_worker_process_creation(self):
        """Test creating a WorkerProcess instance"""
        worker = WorkerProcess(
            repo_name="test-repo",
            port=8000,
            path="/path/to/repo",
            description="Test repository"
        )
        
        self.assertEqual(worker.repo_name, "test-repo")
        self.assertEqual(worker.port, 8000)
        self.assertEqual(worker.path, "/path/to/repo")
        self.assertEqual(worker.description, "Test repository")
        self.assertIsNone(worker.process)
        self.assertIsNone(worker.start_time)
        self.assertEqual(worker.restart_count, 0)
        self.assertEqual(worker.max_restarts, 5)
        self.assertEqual(worker.shutdown_timeout, 30.0)
        self.assertEqual(worker.graceful_timeout, 10.0)
    
    def test_worker_process_with_custom_timeouts(self):
        """Test creating a WorkerProcess with custom timeouts"""
        worker = WorkerProcess(
            repo_name="test-repo",
            port=8000,
            path="/path/to/repo",
            description="Test repository",
            shutdown_timeout=60.0,
            graceful_timeout=15.0
        )
        
        self.assertEqual(worker.shutdown_timeout, 60.0)
        self.assertEqual(worker.graceful_timeout, 15.0)


async def run_async_tests():
    """Run async tests manually"""
    print("Running async tests:")
    
    # Create test instance
    test_instance = TestWorkerManager()
    test_instance.setUp()
    
    try:
        # Run async test methods
        await test_instance.async_test_shutdown_single_worker_graceful()
        print("✓ async_test_shutdown_single_worker_graceful passed")
        
        await test_instance.async_test_shutdown_all_workers()
        print("✓ async_test_shutdown_all_workers passed")
        
    except Exception as e:
        print(f"✗ Async test failed: {e}")
    finally:
        test_instance.tearDown()


if __name__ == '__main__':
    # Run regular unittest for sync tests
    unittest.main(verbosity=2, exit=False)
    
    print("\n" + "="*50)
    print("Running async tests separately:")
    print("="*50)
    
    # Run async tests
    asyncio.run(run_async_tests())
