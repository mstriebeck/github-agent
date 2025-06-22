#!/usr/bin/env python3
"""
Test suite for shutdown_core.py components

This module tests the core shutdown components including logging,
signal handling, and shutdown coordination.
"""

import unittest
import logging
import tempfile
import os
import signal
import threading
import time
from unittest.mock import patch, MagicMock

from shutdown_core import (
    setup_enhanced_logging,
    MicrosecondFormatter,
    ShutdownCoordinator,
    setup_signal_handlers,
    ExitCodes,
    RealProcessSpawner
)
from system_utils import log_system_state, get_system_state, format_system_state_for_health


class TestCentralLogging(unittest.TestCase):
    """Test the central logging system"""
    
    def setUp(self):
        self.test_logger_name = f"test_logger_{int(time.time() * 1000000)}"
    
    def test_setup_enhanced_logging(self):
        """Test that enhanced logging is properly configured"""
        logger = logging.getLogger(self.test_logger_name)
        logger.setLevel(logging.DEBUG)
        
        # Setup enhanced logging
        enhanced_logger = setup_enhanced_logging(logger)
        
        # Verify logger is enhanced
        self.assertIsInstance(enhanced_logger, logging.Logger)
        self.assertEqual(enhanced_logger.name, self.test_logger_name)
        self.assertEqual(enhanced_logger.level, logging.DEBUG)
        
        # Verify handlers are added (file and console)
        self.assertEqual(len(enhanced_logger.handlers), 2)  # file, console
        
        # Test logging with microsecond precision
        enhanced_logger.info("Test message for microsecond precision")
        enhanced_logger.debug("Debug message")
        
        # Cleanup
        for handler in enhanced_logger.handlers[:]:
            handler.close()
            enhanced_logger.removeHandler(handler)
    
    def test_microsecond_precision(self):
        """Test that log messages include microsecond precision"""
        logger = logging.getLogger(self.test_logger_name)
        logger.setLevel(logging.DEBUG)
        logger = setup_enhanced_logging(logger)
        
        # Find the file handler to read log content
        file_handler = None
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                file_handler = handler
                break
        
        self.assertIsNotNone(file_handler)
        
        # Log a test message
        test_message = "Test microsecond precision message"
        logger.info(test_message)
        
        # Force flush
        file_handler.flush()
        
        # Read the log file
        with open(file_handler.baseFilename, 'r') as f:
            log_content = f.read()
        
        # Verify the message is there and has microsecond precision
        self.assertIn(test_message, log_content)
        # Check for pattern like 2024-01-01 12:34:56.123
        import re
        timestamp_pattern = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}'
        self.assertTrue(re.search(timestamp_pattern, log_content))
        
        # Cleanup
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        
        # Remove test log file
        try:
            os.unlink(file_handler.baseFilename)
        except:
            pass
    
    @patch('psutil.Process')
    def test_log_system_state(self, mock_process):
        """Test system state logging"""
        # Mock psutil.Process
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.status.return_value = 'running'
        mock_proc.memory_info.return_value = MagicMock(rss=1024*1024, vms=2048*1024)
        mock_proc.cpu_percent.return_value = 15.5
        mock_proc.num_threads.return_value = 4
        mock_proc.open_files.return_value = []
        mock_proc.connections.return_value = []
        mock_proc.children.return_value = []
        mock_process.return_value = mock_proc
        
        logger = logging.getLogger(self.test_logger_name)
        logger.setLevel(logging.DEBUG)
        logger = setup_enhanced_logging(logger)
        
        # Test system state logging
        log_system_state(logger, "TEST_PHASE")
        
        # Verify psutil.Process was called
        mock_process.assert_called_once()
        
        # Cleanup
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


class TestShutdownCoordinator(unittest.TestCase):
    """Test the shutdown coordinator"""
    
    def setUp(self):
        logger = logging.getLogger(f"test_coordinator_{int(time.time() * 1000000)}")
        logger.setLevel(logging.DEBUG)
        self.logger = setup_enhanced_logging(logger)
        self.coordinator = ShutdownCoordinator(self.logger)
    
    def tearDown(self):
        # Cleanup logger
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
    
    def test_shutdown_initiation(self):
        """Test shutdown initiation"""
        self.assertFalse(self.coordinator.is_shutting_down())
        self.assertIsNone(self.coordinator.get_shutdown_reason())
        
        self.coordinator.shutdown("test_reason")
        
        self.assertTrue(self.coordinator.is_shutting_down())
        self.assertEqual(self.coordinator.get_shutdown_reason(), "test_reason")
    
    def test_duplicate_shutdown_prevention(self):
        """Test that duplicate shutdown calls are ignored"""
        self.coordinator.shutdown("first_reason")
        self.assertEqual(self.coordinator.get_shutdown_reason(), "first_reason")
        
        # Second shutdown should be ignored
        self.coordinator.shutdown("second_reason")
        self.assertEqual(self.coordinator.get_shutdown_reason(), "first_reason")
    
    def test_wait_for_shutdown(self):
        """Test waiting for shutdown"""
        # Start shutdown in another thread
        def delayed_shutdown():
            time.sleep(0.1)
            self.coordinator.shutdown("delayed_test")
        
        thread = threading.Thread(target=delayed_shutdown)
        thread.start()
        
        # Wait for shutdown
        result = self.coordinator.wait_for_shutdown(timeout=1.0)
        self.assertTrue(result)
        self.assertEqual(self.coordinator.get_shutdown_reason(), "delayed_test")
        
        thread.join()
    
    def test_wait_for_shutdown_timeout(self):
        """Test waiting for shutdown with timeout"""
        result = self.coordinator.wait_for_shutdown(timeout=0.1)
        self.assertFalse(result)


class TestSignalHandling(unittest.TestCase):
    """Test signal handling setup"""
    
    def setUp(self):
        logger = logging.getLogger(f"test_signals_{int(time.time() * 1000000)}")
        logger.setLevel(logging.DEBUG)
        self.logger = setup_enhanced_logging(logger)
        self.coordinator = ShutdownCoordinator(self.logger)
    
    def tearDown(self):
        # Cleanup logger
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
    
    def test_signal_handler_setup(self):
        """Test that signal handlers are properly registered"""
        # Store original handlers
        original_sigterm = signal.signal(signal.SIGTERM, signal.SIG_DFL)
        original_sigint = signal.signal(signal.SIGINT, signal.SIG_DFL)
        
        try:
            setup_signal_handlers(self.coordinator)
            
            # Verify handlers are set (they won't be SIG_DFL anymore)
            current_sigterm = signal.signal(signal.SIGTERM, signal.SIG_DFL)
            current_sigint = signal.signal(signal.SIGINT, signal.SIG_DFL)
            
            self.assertNotEqual(current_sigterm, signal.SIG_DFL)
            self.assertNotEqual(current_sigint, signal.SIG_DFL)
            
        finally:
            # Restore original handlers
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)


class TestExitCodes(unittest.TestCase):
    """Test exit code constants"""
    
    def test_exit_codes_defined(self):
        """Test that all exit codes are properly defined"""
        self.assertEqual(ExitCodes.SUCCESS, 0)
        self.assertEqual(ExitCodes.GRACEFUL_CLIENT_TIMEOUT, 1)
        self.assertEqual(ExitCodes.GRACEFUL_WORKER_TIMEOUT, 2)
        self.assertEqual(ExitCodes.WORKER_FORCE_KILL, 3)
        self.assertEqual(ExitCodes.PORT_CONFLICT, 4)
        self.assertEqual(ExitCodes.ZOMBIE_PROCESSES, 5)
        self.assertEqual(ExitCodes.RESOURCE_CLEANUP_FAILURE, 6)
        self.assertEqual(ExitCodes.INTERNAL_ERROR, 100)


class TestSystemUtils(unittest.TestCase):
    """Test system utilities"""
    
    def test_get_system_state(self):
        """Test getting system state"""
        system_state = get_system_state()
        
        # Should have required keys
        self.assertIn('process', system_state)
        self.assertIn('memory', system_state)
        self.assertIn('children', system_state)
        self.assertIn('threads', system_state)
        self.assertIn('timestamp', system_state)
        
        # Process info should have expected structure
        process_info = system_state['process']
        self.assertIn('pid', process_info)
        self.assertIn('status', process_info)
        
        # Memory info should have expected structure
        memory_info = system_state['memory']
        self.assertIn('rss_mb', memory_info)
        self.assertIn('vms_mb', memory_info)
    
    def test_format_system_state_for_health(self):
        """Test formatting system state for health endpoint"""
        # Test with valid system state
        system_state = get_system_state()
        health_format = format_system_state_for_health(system_state)
        
        self.assertEqual(health_format['status'], 'healthy')
        self.assertIn('process', health_format)
        self.assertIn('timestamp', health_format)
        
        # Test with error state
        error_state = {'error': 'test error', 'timestamp': '2024-01-01T00:00:00'}
        health_format = format_system_state_for_health(error_state)
        
        self.assertEqual(health_format['status'], 'error')
        self.assertEqual(health_format['error'], 'test error')


class TestRealProcessSpawner(unittest.TestCase):
    """Test the real process spawner implementation"""
    
    def test_interface_implementation(self):
        """Test that RealProcessSpawner implements the interface"""
        spawner = RealProcessSpawner()
        
        # Test with a simple command that will work on most systems
        process = spawner.spawn_process(['echo', 'test'])
        
        # Test poll status
        initial_status = spawner.get_process_poll_status(process)
        
        # Wait for process
        try:
            spawner.wait_for_process(process, timeout=5)
        except:
            pass  # Process might already be done
        
        # Check final status
        final_status = spawner.get_process_poll_status(process)
        self.assertIsNotNone(final_status)  # Should have exit code now


if __name__ == '__main__':
    unittest.main()
