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


def setup_central_logger(name='mcp_server', level=logging.DEBUG):
    """Setup centralized logger with microsecond precision that gets passed to all components"""
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Prevent duplicate handlers
    if logger.handlers:
        logger.handlers.clear()
    
    # True microsecond precision formatter using datetime
    class MicrosecondFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created)
            return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Keep 3 decimal places (milliseconds)
    
    # Detailed formatter with microseconds
    microsecond_formatter = MicrosecondFormatter(
        '%(asctime)s [%(levelname)8s] %(name)s.%(funcName)s:%(lineno)d - %(message)s'
    )
    
    # Console formatter with microseconds
    console_formatter = MicrosecondFormatter(
        '%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # File handler for detailed debug logs
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include microseconds
    debug_file = f'/tmp/mcp_server_debug_{timestamp}.log'
    file_handler = logging.FileHandler(debug_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(microsecond_formatter)
    
    # Shutdown-specific log file
    shutdown_file = f'/tmp/mcp_server_shutdown_{timestamp}.log'
    shutdown_handler = logging.FileHandler(shutdown_file)
    shutdown_handler.setLevel(logging.INFO)
    shutdown_handler.setFormatter(microsecond_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    
    # Add all handlers
    logger.addHandler(file_handler)
    logger.addHandler(shutdown_handler)
    logger.addHandler(console_handler)
    
    # Log the initialization with microsecond precision
    logger.info(f"Central logger initialized with microsecond precision")
    logger.debug(f"Debug log: {debug_file}")
    logger.debug(f"Shutdown log: {shutdown_file}")
    logger.debug(f"Log level set to: {logging.getLevelName(level)}")
    
    return logger


def log_system_state(logger, phase):
    """Log comprehensive system state with microsecond timing"""
    start_time = datetime.now()
    logger.debug(f"=== SYSTEM STATE: {phase} (at {start_time.strftime('%H:%M:%S.%f')[:-3]}) ===")
    
    try:
        import psutil
        import threading
        
        # Process info
        proc = psutil.Process()
        logger.debug(f"PID: {proc.pid}, Status: {proc.status()}")
        logger.debug(f"Memory: RSS={proc.memory_info().rss/1024/1024:.1f}MB, VMS={proc.memory_info().vms/1024/1024:.1f}MB")
        logger.debug(f"CPU: {proc.cpu_percent()}%")
        logger.debug(f"Threads: {proc.num_threads()}")
        logger.debug(f"Open files: {len(proc.open_files())}")
        logger.debug(f"Connections: {len(proc.connections())}")
        
        # Children
        children = proc.children(recursive=True)
        logger.debug(f"Child processes: {len(children)}")
        for child in children:
            try:
                logger.debug(f"  Child PID {child.pid}: {child.name()} ({child.status()})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Threading info
        logger.debug(f"Active Python threads: {threading.active_count()}")
        for thread in threading.enumerate():
            logger.debug(f"  Thread: {thread.name} (alive: {thread.is_alive()})")
            
    except Exception as e:
        logger.error(f"Error logging system state: {e}")
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() * 1000  # milliseconds
    logger.debug(f"=== END SYSTEM STATE: {phase} (duration: {duration:.2f}ms) ===")


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
