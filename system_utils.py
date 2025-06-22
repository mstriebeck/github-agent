"""
System utilities for monitoring and diagnostics

This module provides system monitoring and diagnostic utilities that can be used
throughout the MCP server system, including in health endpoints and shutdown procedures.
"""

import asyncio
import logging
import psutil
import threading
import time
from datetime import datetime


class MicrosecondFormatter(logging.Formatter):
    """Custom formatter that provides microsecond precision timestamps"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Keep 3 decimal places (milliseconds)


def get_system_state():
    """Get comprehensive system state information as a dictionary"""
    try:
        # Process info
        proc = psutil.Process()
        
        # Get memory info
        memory_info = proc.memory_info()
        
        # Get children
        children = proc.children(recursive=True)
        child_info = []
        for child in children:
            try:
                child_info.append({
                    'pid': child.pid,
                    'name': child.name(),
                    'status': child.status()
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Get thread info
        thread_info = []
        for thread in threading.enumerate():
            thread_info.append({
                'name': thread.name,
                'alive': thread.is_alive(),
                'daemon': thread.daemon
            })
        
        system_state = {
            'process': {
                'pid': proc.pid,
                'status': proc.status(),
                'cpu_percent': proc.cpu_percent(),
                'num_threads': proc.num_threads(),
                'open_files_count': len(proc.open_files()),
                'connections_count': len(proc.net_connections())
            },
            'memory': {
                'rss_mb': memory_info.rss / 1024 / 1024,
                'vms_mb': memory_info.vms / 1024 / 1024
            },
            'children': child_info,
            'threads': {
                'count': threading.active_count(),
                'details': thread_info
            },
            'timestamp': datetime.now().isoformat()
        }
        
        return system_state
        
    except Exception as e:
        return {
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


def log_system_state(logger, phase):
    """Log comprehensive system state with microsecond timing for debugging"""
    start_time = datetime.now()
    logger.debug(f"=== SYSTEM STATE: {phase} (at {start_time.strftime('%H:%M:%S.%f')[:-3]}) ===")
    
    try:
        system_state = get_system_state()
        
        if 'error' in system_state:
            logger.error(f"Error getting system state: {system_state['error']}")
            return
        
        # Log process info
        proc_info = system_state['process']
        logger.debug(f"PID: {proc_info['pid']}, Status: {proc_info['status']}")
        logger.debug(f"Memory: RSS={system_state['memory']['rss_mb']:.1f}MB, VMS={system_state['memory']['vms_mb']:.1f}MB")
        logger.debug(f"CPU: {proc_info['cpu_percent']}%")
        logger.debug(f"Threads: {proc_info['num_threads']}")
        logger.debug(f"Open files: {proc_info['open_files_count']}")
        logger.debug(f"Connections: {proc_info['connections_count']}")
        
        # Log children
        children = system_state['children']
        logger.debug(f"Child processes: {len(children)}")
        for child in children:
            logger.debug(f"  Child PID {child['pid']}: {child['name']} ({child['status']})")
        
        # Log threading info
        thread_info = system_state['threads']
        logger.debug(f"Active Python threads: {thread_info['count']}")
        for thread in thread_info['details']:
            logger.debug(f"  Thread: {thread['name']} (alive: {thread['alive']}, daemon: {thread['daemon']})")
            
    except Exception as e:
        logger.error(f"Error logging system state: {e}")
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() * 1000  # milliseconds
    logger.debug(f"=== END SYSTEM STATE: {phase} (duration: {duration:.2f}ms) ===")


def format_system_state_for_health(system_state):
    """Format system state information for health endpoint response"""
    if 'error' in system_state:
        return {
            'status': 'error',
            'error': system_state['error'],
            'timestamp': system_state['timestamp']
        }
    
    return {
        'status': 'healthy',
        'process': {
            'pid': system_state['process']['pid'],
            'status': system_state['process']['status'],
            'cpu_percent': system_state['process']['cpu_percent'],
            'memory_mb': {
                'rss': round(system_state['memory']['rss_mb'], 1),
                'vms': round(system_state['memory']['vms_mb'], 1)
            },
            'threads': system_state['process']['num_threads'],
            'open_files': system_state['process']['open_files_count'],
            'connections': system_state['process']['connections_count']
        },
        'children_count': len(system_state['children']),
        'python_threads_count': system_state['threads']['count'],
        'timestamp': system_state['timestamp']
    }


class SystemMonitor:
    """System monitoring utilities for async operations"""
    
    def __init__(self):
        pass
    
    async def log_system_state(self, logger, phase: str) -> None:
        """Async version of log_system_state"""
        # Run the synchronous system state collection in a thread pool
        # to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, log_system_state, logger, phase)
    
    def get_system_metrics(self) -> dict:
        """Get basic system metrics"""
        return get_system_state()
    
    async def wait_for_condition(self, condition_func, timeout: float = 5.0, 
                                check_interval: float = 0.1) -> bool:
        """Wait for condition to be true with timeout"""
        end_time = time.time() + timeout
        
        while time.time() < end_time:
            if condition_func():
                return True
            await asyncio.sleep(check_interval)
        
        return False
