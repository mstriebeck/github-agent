"""
MCP Server Clean Shutdown Core Components

This module provides the core components for implementing clean shutdown
procedures for a Python MCP server that manages multiple repository workers.
"""

import logging
import sys
import threading
import signal
import time
import os
from datetime import datetime
from abc import ABC, abstractmethod


class MicrosecondFormatter(logging.Formatter):
    """Custom formatter that provides microsecond precision timestamps"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Keep 3 decimal places (milliseconds)


def setup_enhanced_logging(logger, log_file_path=None):
    """Enhance an existing logger with microsecond precision formatting
    
    This should be called from the master process to enhance the main logger
    that will be passed to all components throughout the system.
    """
    # Prevent duplicate handlers
    if logger.handlers:
        logger.handlers.clear()
    
    # Detailed formatter with microseconds
    detailed_formatter = MicrosecondFormatter(
        '%(asctime)s [%(levelname)8s] %(name)s.%(funcName)s:%(lineno)d - %(message)s'
    )
    
    # Console formatter with microseconds
    console_formatter = MicrosecondFormatter(
        '%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # File handler for detailed debug logs (use provided path or default)
    if log_file_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        log_file_path = f'/tmp/mcp_server_{timestamp}.log'
    
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"Enhanced logging initialized with microsecond precision")
    logger.debug(f"Log file: {log_file_path}")
    logger.debug(f"Log level set to: {logging.getLevelName(logger.level)}")
    
    return logger



class ShutdownCoordinator:
    """Central shutdown coordinator that orchestrates the entire shutdown sequence"""
    
    def __init__(self, logger):
        self._shutdown_event = threading.Event()
        self._shutdown_reason = None
        self._shutdown_initiated = False  # Flag to prevent multiple shutdown initiations
        self.logger = logger  # Central logger passed in
        
    def shutdown(self, reason="manual"):
        """Initiate shutdown sequence"""
        if self._shutdown_initiated:
            self.logger.warning(f"Shutdown already initiated (reason: {self._shutdown_reason}), ignoring new request")
            return
        
        self._shutdown_initiated = True
        self._shutdown_reason = reason
        
        self.logger.critical(f"=== SHUTDOWN INITIATED (reason: {reason}) ===")
        self._shutdown_event.set()
        self.logger.debug("Shutdown event set")
    
    def is_shutting_down(self):
        """Check if shutdown is in progress"""
        return self._shutdown_event.is_set()
    
    def wait_for_shutdown(self, timeout=None):
        """Wait for shutdown to be initiated"""
        return self._shutdown_event.wait(timeout)
    
    def get_shutdown_reason(self):
        """Get the reason for shutdown"""
        return self._shutdown_reason


def setup_signal_handlers(shutdown_coordinator):
    """Enhanced signal handler with robustness"""
    def signal_handler(signum, frame):
        # Prevent multiple shutdown initiations
        if shutdown_coordinator._shutdown_initiated:  # Use the coordinator's internal flag
            shutdown_coordinator.logger.warning(f"Already handling shutdown, ignoring signal {signum}")
            return
        
        signal_name = signal.Signals(signum).name
        shutdown_coordinator.logger.critical(f"Received signal {signum} ({signal_name})")
        shutdown_coordinator.logger.debug(f"Signal received in frame: {frame.f_code.co_filename}:{frame.f_lineno}")
        shutdown_coordinator.shutdown(reason=f"signal_{signal_name}")
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    shutdown_coordinator.logger.debug("Signal handlers registered for SIGTERM and SIGINT")


# Exit codes for monitoring
class ExitCodes:
    """Exit codes for monitoring and debugging"""
    SUCCESS = 0                    # Clean shutdown
    GRACEFUL_CLIENT_TIMEOUT = 1    # Clients didn't disconnect gracefully
    GRACEFUL_WORKER_TIMEOUT = 2    # Workers didn't terminate gracefully
    WORKER_FORCE_KILL = 3          # Workers required SIGKILL
    PORT_CONFLICT = 4              # Port not released
    ZOMBIE_PROCESSES = 5           # Zombie processes detected
    RESOURCE_CLEANUP_FAILURE = 6   # Resource cleanup failed
    INTERNAL_ERROR = 100           # Unhandled exception during shutdown


# Abstract base classes for testing
class IProcessSpawner(ABC):
    """Abstract interface for process spawning to enable mocking in tests"""
    
    @abstractmethod
    def spawn_process(self, command, preexec_fn=None):
        """Spawns a new process and returns a handle."""
        pass
    
    @abstractmethod
    def wait_for_process(self, process_handle, timeout):
        """Waits for a process to terminate, with a timeout."""
        pass
    
    @abstractmethod
    def terminate_process(self, process_handle):
        """Sends SIGTERM to a process."""
        pass
    
    @abstractmethod
    def kill_process_group(self, pid):
        """Sends SIGKILL to a process group."""
        pass
    
    @abstractmethod
    def get_process_poll_status(self, process_handle):
        """Returns the exit code if terminated, otherwise None."""
        pass


class RealProcessSpawner(IProcessSpawner):
    """Production implementation of process spawning"""
    
    def spawn_process(self, command, preexec_fn=None):
        import subprocess
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=preexec_fn
        )
    
    def wait_for_process(self, process_handle, timeout):
        return process_handle.wait(timeout=timeout)
    
    def terminate_process(self, process_handle):
        process_handle.terminate()
    
    def kill_process_group(self, pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # Process group might already be gone
    
    def get_process_poll_status(self, process_handle):
        return process_handle.poll()
