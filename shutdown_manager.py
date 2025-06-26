"""
Consolidated Shutdown Manager for MCP Server System

This module provides a single, comprehensive shutdown manager that handles all
shutdown operations for both master and worker processes. It absorbs the 
functionality of multiple separate managers into one cohesive system.

Key Features:
- Single entry point for all shutdown operations
- Mode-aware behavior (master vs worker)
- Comprehensive resource management
- Client connection handling
- Process lifecycle management
- Signal handling and exit codes
- Extensive logging and verification
"""

import asyncio
import logging
import signal
import time
import os
import subprocess
import threading
import json
import socket
import psutil
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass
from enum import Enum
from health_monitor import ServerStatus, ShutdownPhase

try:
    import aiohttp
except ImportError:
    aiohttp = None

# Import core utilities
from shutdown_core import ShutdownCoordinator, RealProcessSpawner
from system_utils import SystemMonitor
from exit_codes import ExitCodeManager, ShutdownExitCode
from health_monitor import HealthMonitor


# === DATA STRUCTURES ===

@dataclass
class WorkerProcess:
    """Information about a managed worker process"""
    repo_name: str
    port: int
    path: str
    description: str
    process: Optional[subprocess.Popen] = None
    start_time: Optional[float] = None
    restart_count: int = 0
    max_restarts: int = 5
    shutdown_timeout: float = 30.0
    graceful_timeout: float = 10.0
    
    def is_running(self) -> bool:
        """Check if the worker process is currently running"""
        return self.process is not None and self.process.poll() is None


class ClientState(Enum):
    """Client connection states"""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class DisconnectionReason(Enum):
    """Reasons for client disconnection"""
    SHUTDOWN = "shutdown"
    ERROR = "error"
    TIMEOUT = "timeout"
    CLIENT_REQUEST = "client_request"


@dataclass
class ClientInfo:
    """Information about a connected client"""
    client_id: str
    transport: Any
    connection_time: float
    last_activity: float
    state: ClientState
    bytes_sent: int = 0
    bytes_received: int = 0
    error_count: int = 0


# === INTERNAL CLASSES ===

class _ResourceTracker:
    """Internal class to track resources that need cleanup"""
    
    def __init__(self, logger):
        self.logger = logger
        self._resources: Dict[str, Any] = {}
        self._file_handles: Dict[str, Any] = {}
        self._database_connections: Dict[str, Any] = {}
        self._cleanup_callbacks: List[Callable] = []
        self._closed = False
    
    def add_resource(self, name: str, resource: Any, priority: int = 5) -> None:
        """Add a generic resource to be managed"""
        if self._closed:
            self.logger.warning(f"Cannot add resource {name} - tracker is closed")
            return
        self._resources[name] = {'resource': resource, 'priority': priority}
        self.logger.debug(f"Added resource: {name} (priority: {priority})")
    
    def add_file_handle(self, name: str, file_handle: Any) -> None:
        """Add a file handle to be managed"""
        if self._closed:
            self.logger.warning(f"Cannot add file handle {name} - tracker is closed")
            return
        self._file_handles[name] = file_handle
        self.logger.debug(f"Added file handle: {name}")
    
    def add_database_connection(self, name: str, connection: Any) -> None:
        """Add a database connection to be managed"""
        if self._closed:
            self.logger.warning(f"Cannot add database connection {name} - tracker is closed")
            return
        self._database_connections[name] = connection
        self.logger.debug(f"Added database connection: {name}")
    
    def add_cleanup_callback(self, name: str, callback: Callable) -> None:
        """Add a cleanup callback to be executed"""
        if self._closed:
            self.logger.warning(f"Cannot add cleanup callback {name} - tracker is closed")
            return
        self._cleanup_callbacks.append((name, callback))
        self.logger.debug(f"Added cleanup callback: {name}")
    
    async def cleanup_all(self) -> bool:
        """Clean up all tracked resources"""
        if self._closed:
            self.logger.info("Resource tracker already closed")
            return True
            
        self.logger.info("Starting comprehensive resource cleanup")
        success = True
        
        # Phase 1: Close database connections
        if self._database_connections:
            self.logger.info(f"Closing {len(self._database_connections)} database connections")
            for name, conn in self._database_connections.items():
                try:
                    if hasattr(conn, 'close'):
                        if asyncio.iscoroutinefunction(conn.close):
                            await conn.close()
                        else:
                            conn.close()
                    self.logger.debug(f"✓ Closed database connection: {name}")
                except Exception as e:
                    self.logger.error(f"✗ Failed to close database connection {name}: {e}")
                    success = False
        
        # Phase 2: Close resources by priority
        if self._resources:
            # Sort by priority (lower numbers first)
            sorted_resources = sorted(self._resources.items(), 
                                    key=lambda x: x[1]['priority'])
            
            self.logger.info(f"Closing {len(sorted_resources)} resources")
            for name, res_info in sorted_resources:
                try:
                    resource = res_info['resource']
                    if hasattr(resource, 'close'):
                        if asyncio.iscoroutinefunction(resource.close):
                            await resource.close()
                        else:
                            resource.close()
                    self.logger.debug(f"✓ Closed resource: {name}")
                except Exception as e:
                    self.logger.error(f"✗ Failed to close resource {name}: {e}")
                    success = False
        
        # Phase 3: Execute cleanup callbacks
        if self._cleanup_callbacks:
            self.logger.info(f"Executing {len(self._cleanup_callbacks)} cleanup callbacks")
            for name, callback in self._cleanup_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                    self.logger.debug(f"✓ Executed cleanup callback: {name}")
                except Exception as e:
                    self.logger.error(f"✗ Failed to execute cleanup callback {name}: {e}")
                    success = False
        
        # Phase 4: Close file handles
        if self._file_handles:
            self.logger.info(f"Closing {len(self._file_handles)} file handles")
            for name, handle in self._file_handles.items():
                try:
                    if hasattr(handle, 'close'):
                        handle.close()
                    self.logger.debug(f"✓ Closed file handle: {name}")
                except Exception as e:
                    self.logger.error(f"✗ Failed to close file handle {name}: {e}")
                    success = False
        
        self._closed = True
        status = "✓ All resources cleaned up successfully" if success else "✗ Some resources failed to clean up"
        self.logger.info(status)
        return success

    async def cleanup_all_with_result(self) -> tuple[bool, list[str]]:
        """Clean up all resources and return (success, errors)"""
        errors = []
        try:
            success = await self.cleanup_all()
            if not success:
                errors.append("Some resources failed to clean up")
            return success, errors
        except Exception as e:
            errors.append(f"Resource cleanup failed: {e}")
            return False, errors
    
    def cleanup_resources(self) -> tuple[bool, list[str]]:
        """Synchronous version of cleanup_all_with_result for test compatibility"""
        errors = []
        success = True
        
        # Phase 0: Check for process resource usage (for testing permission scenarios)
        def check_process_resources():
            current_process = psutil.Process()
            # Try to get process information - this can raise PermissionError
            open_files = current_process.open_files()
            connections = current_process.connections()
            return open_files, connections
        
        try:
            # Use threading to implement timeout for hanging operations
            import concurrent.futures
            executor = concurrent.futures.ThreadPoolExecutor()
            try:
                future = executor.submit(check_process_resources)
                try:
                    open_files, connections = future.result(timeout=2.0)  # 2 second timeout
                    self.logger.debug(f"Process has {len(open_files)} open files and {len(connections)} connections")
                    
                    # Report open files as issues for testing
                    if open_files:
                        file_paths = [f.path for f in open_files]
                        error_msg = f"Process has {len(open_files)} open files: {file_paths}"
                        self.logger.warning(error_msg)
                        errors.append(error_msg)
                        
                    if connections:
                        error_msg = f"Process has {len(connections)} active connections"
                        self.logger.warning(error_msg)
                        errors.append(error_msg)
                        
                except concurrent.futures.TimeoutError:
                    error_msg = "Timeout checking process resources (operation hanging)"
                    self.logger.warning(error_msg)
                    errors.append(error_msg)
                    future.cancel()  # Try to cancel the future
            finally:
                executor.shutdown(wait=False)  # Don't wait for hanging tasks
        except PermissionError as e:
            error_msg = f"Permission denied accessing process information: {e}"
            self.logger.warning(error_msg)
            errors.append(error_msg)
            # Don't mark as failure since this is just informational
        except Exception as e:
            error_msg = f"Failed to check process resources: {e}"
            self.logger.warning(error_msg)
            errors.append(error_msg)
        
        # Phase 1: Close database connections
        if self._database_connections:
            self.logger.info(f"Closing {len(self._database_connections)} database connections")
            for name, conn in self._database_connections.items():
                try:
                    if hasattr(conn, 'close'):
                        conn.close()
                    self.logger.debug(f"✓ Closed database connection: {name}")
                except Exception as e:
                    error_msg = f"Failed to close database connection {name}: {e}"
                    self.logger.error(f"✗ {error_msg}")
                    errors.append(error_msg)
                    success = False
        
        # Phase 2: Close resources by priority
        if self._resources:
            sorted_resources = sorted(self._resources.items(), 
                                    key=lambda x: x[1]['priority'])
            
            self.logger.info(f"Closing {len(sorted_resources)} resources")
            for name, res_info in sorted_resources:
                try:
                    resource = res_info['resource']
                    if hasattr(resource, 'close'):
                        resource.close()
                    self.logger.debug(f"✓ Closed resource: {name}")
                except Exception as e:
                    error_msg = f"Failed to close resource {name}: {e}"
                    self.logger.error(f"✗ {error_msg}")
                    errors.append(error_msg)
                    success = False
        
        # Phase 3: Execute cleanup callbacks
        if self._cleanup_callbacks:
            self.logger.info(f"Executing {len(self._cleanup_callbacks)} cleanup callbacks")
            for name, callback in self._cleanup_callbacks:
                try:
                    callback()
                    self.logger.debug(f"✓ Executed cleanup callback: {name}")
                except Exception as e:
                    error_msg = f"Failed to execute cleanup callback {name}: {e}"
                    self.logger.error(f"✗ {error_msg}")
                    errors.append(error_msg)
                    success = False
        
        # Phase 4: Close file handles  
        if self._file_handles:
            self.logger.info(f"Closing {len(self._file_handles)} file handles")
            for name, handle in self._file_handles.items():
                try:
                    if hasattr(handle, 'close'):
                        handle.close()
                    self.logger.debug(f"✓ Closed file handle: {name}")
                except Exception as e:
                    error_msg = f"Failed to close file handle {name}: {e}"
                    self.logger.error(f"✗ {error_msg}")
                    errors.append(error_msg)
                    success = False
        
        self._closed = True
        status = "✓ All resources cleaned up successfully" if success else "✗ Some resources failed to clean up"
        self.logger.info(status)
        return success, errors
    
    def verify_ports_released(self, ports: list[int]) -> tuple[bool, list[str]]:
        """Verify that the specified ports are no longer in use"""
        errors = []
        success = True
        
        for port in ports:
            try:
                # Try to bind to the port to see if it's free
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(('localhost', port))
                    self.logger.debug(f"✓ Port {port} is released")
            except OSError as e:
                error_msg = f"Port {port} is still in use: {e}"
                self.logger.error(f"✗ {error_msg}")
                errors.append(error_msg)
                success = False
            except Exception as e:
                error_msg = f"Failed to verify port {port}: {e}"
                self.logger.error(f"✗ {error_msg}")
                errors.append(error_msg)
                success = False
        
        return success, errors


class _ClientTracker:
    """Internal class to track and manage client connections"""
    
    def __init__(self, logger):
        self.logger = logger
        self._clients: Dict[str, ClientInfo] = {}
        self._client_groups: Dict[str, Set[str]] = {}
        self._closed = False
        self._lock = threading.Lock()
        # Alias for tests
        self._active_clients = self._clients
    
    def add_client(self, client_id: str, transport, group: Optional[str] = None) -> bool:
        """Add a client connection to be managed"""
        if self._closed:
            self.logger.warning(f"Cannot add client {client_id} - tracker is closed")
            return False
        
        with self._lock:
            if client_id in self._clients:
                self.logger.warning(f"Client {client_id} already exists")
                return False
            
            client_info = ClientInfo(
                client_id=client_id,
                transport=transport,
                connection_time=time.time(),
                last_activity=time.time(),
                state=ClientState.CONNECTED
            )
            
            self._clients[client_id] = client_info
            
            if group:
                if group not in self._client_groups:
                    self._client_groups[group] = set()
                self._client_groups[group].add(client_id)
            
            self.logger.debug(f"Added client: {client_id} (group: {group})")
            return True
    
    def remove_client(self, client_id: str) -> bool:
        """Remove a client connection"""
        with self._lock:
            if client_id not in self._clients:
                return False
            
            # Remove from groups
            for group_clients in self._client_groups.values():
                group_clients.discard(client_id)
            
            del self._clients[client_id]
            self.logger.debug(f"Removed client: {client_id}")
            return True
    
    def get_all_clients(self) -> List[ClientInfo]:
        """Get all client connections"""
        with self._lock:
            return list(self._clients.values())
    
    async def disconnect_all(self, grace_period: float = 10.0) -> bool:
        """Disconnect all clients gracefully"""
        if self._closed:
            return True
            
        clients = self.get_all_clients()
        if not clients:
            self.logger.info("No clients to disconnect")
            return True
        
        self.logger.info(f"Disconnecting {len(clients)} clients")
        success = True
        
        # Phase 1: Send shutdown notifications
        for client in clients:
            try:
                await self._send_shutdown_notification(client)
            except Exception as e:
                self.logger.error(f"Failed to notify client {client.client_id}: {e}")
                success = False
        
        # Phase 2: Wait for graceful disconnection
        grace_end = time.time() + grace_period
        while time.time() < grace_end and self._clients:
            await asyncio.sleep(0.5)
        
        # Phase 3: Force disconnect remaining clients
        remaining = self.get_all_clients()
        if remaining:
            self.logger.warning(f"Force disconnecting {len(remaining)} clients")
            for client in remaining:
                try:
                    await self._force_disconnect_client(client)
                except Exception as e:
                    self.logger.error(f"Failed to force disconnect {client.client_id}: {e}")
                    success = False
        
        self._closed = True
        final_count = len(self.get_all_clients())
        if final_count == 0:
            self.logger.info("✓ All clients disconnected successfully")
        else:
            self.logger.error(f"✗ {final_count} clients still connected")
            success = False
        
        return success

    def get_client_count(self) -> int:
        """Get the number of connected clients"""
        with self._lock:
            return len(self._clients)

    def disconnect_all_clients(self, timeout: Optional[float] = None) -> tuple[bool, list[str]]:
        """Synchronous version of disconnect_all_with_result for test compatibility"""
        errors = []
        success = True
        
        with self._lock:
            clients_to_disconnect = list(self._clients.values())
            
        self.logger.info(f"Disconnecting {len(clients_to_disconnect)} clients")
        
        for client in clients_to_disconnect:
            try:
                # Send shutdown notification
                if hasattr(client.transport, 'close'):
                    client.transport.close()
                        
                self.logger.debug(f"✓ Disconnected client: {client.client_id}")
            except Exception as e:
                error_msg = f"Failed to disconnect client {client.client_id}: {e}"
                self.logger.error(f"✗ {error_msg}")
                errors.append(error_msg)
                # Note: Individual client errors don't cause overall failure
            finally:
                # Always remove from tracking, even if disconnection failed
                with self._lock:
                    if client.client_id in self._clients:
                        del self._clients[client.client_id]
        
        # Clear group memberships
        with self._lock:
            self._client_groups.clear()
            
        status = "✓ All clients disconnected successfully" if success else "✗ Some clients failed to disconnect"
        self.logger.info(status)
        return success, errors
        
    async def disconnect_all_clients_async(self, timeout: Optional[float] = None) -> tuple[bool, list[str]]:
        """Async version of disconnect_all_clients"""
        return await self.disconnect_all_with_result()

    async def disconnect_all_with_result(self) -> tuple[bool, list[str]]:
        """Disconnect all clients and return (success, errors)"""
        errors = []
        try:
            success = await self.disconnect_all()
            if not success:
                errors.append("Some clients failed to disconnect")
            return success, errors
        except Exception as e:
            errors.append(f"Client disconnection failed: {e}")
            return False, errors
    
    async def _send_shutdown_notification(self, client: ClientInfo) -> None:
        """Send shutdown notification to a client"""
        message = {
            "jsonrpc": "2.0",
            "method": "server/shutdown",
            "params": {
                "reason": DisconnectionReason.SHUTDOWN.value,
                "timestamp": time.time()
            }
        }
        
        try:
            if hasattr(client.transport, 'write'):
                client.transport.write(json.dumps(message).encode() + b'\n')
                if hasattr(client.transport, 'drain'):
                    await client.transport.drain()
            elif hasattr(client.transport, 'send'):
                await client.transport.send(json.dumps(message))
            
            client.bytes_sent += len(json.dumps(message))
            self.logger.debug(f"Sent shutdown notification to {client.client_id}")
        except Exception as e:
            self.logger.error(f"Failed to send shutdown notification to {client.client_id}: {e}")
            raise
    
    async def _force_disconnect_client(self, client: ClientInfo) -> None:
        """Force disconnect a client"""
        try:
            if hasattr(client.transport, 'close'):
                if asyncio.iscoroutinefunction(client.transport.close):
                    await client.transport.close()
                else:
                    client.transport.close()
            
            self.remove_client(client.client_id)
            self.logger.debug(f"Force disconnected client: {client.client_id}")
        except Exception as e:
            self.logger.error(f"Failed to force disconnect {client.client_id}: {e}")
            raise


# === MAIN SHUTDOWN MANAGER ===

class ShutdownManager:
    """
    Consolidated shutdown manager that handles all shutdown operations
    
    This is the single entry point for shutdown operations in both master
    and worker modes. It internally manages all resources, clients, and
    processes without exposing separate manager classes.
    """
    
    def __init__(self, logger: logging.Logger, mode: str = "master"):
        """
        Initialize the shutdown manager
        
        Args:
            logger: Logger instance for shutdown operations
            mode: Either "master" or "worker" to determine capabilities
        """
        if mode not in ("master", "worker"):
            raise ValueError("Mode must be 'master' or 'worker'")
            
        self.logger = logger
        self.mode = mode
        self.shutdown_in_progress = False
        self.shutdown_start_time = None
        self._shutdown_initiated = False
        self._shutdown_reason = None
        
        # Core components
        self.shutdown_coordinator = ShutdownCoordinator(logger)
        self.system_monitor = SystemMonitor()
        self._exit_code_manager = ExitCodeManager(logger)
        self._health_monitor = HealthMonitor(logger, f"/tmp/mcp_server_health_{os.getpid()}.json")
        
        # Resource and client tracking
        self._resource_tracker = _ResourceTracker(logger)
        self._client_tracker = _ClientTracker(logger)
        
        # Mode-specific components
        if mode == "master":
            self._workers: Dict[str, WorkerProcess] = {}
            self.process_spawner = RealProcessSpawner()
        
        # Shutdown phases completed
        self._completed_phases: List[str] = []
        
        # Signal handling state
        self._pending_signal_shutdown = None
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        self.logger.info(f"Initialized ShutdownManager in {mode} mode")
    
    # === PUBLIC API FOR RESOURCE MANAGEMENT ===
    
    def add_worker(self, repo_name: str, port: int, path: str, 
                   description: str = "", **kwargs) -> Optional[WorkerProcess]:
        """Add a worker process to be managed (master mode only)"""
        if self.mode != "master":
            self.logger.warning("Worker management only available in master mode")
            return None
        
        if self.shutdown_in_progress:
            self.logger.warning(f"Cannot add worker {repo_name} - shutdown in progress")
            return None
        
        worker = WorkerProcess(
            repo_name=repo_name,
            port=port,
            path=path,
            description=description or repo_name,
            **kwargs
        )
        
        self._workers[repo_name] = worker
        self.logger.debug(f"Added worker: {repo_name} on port {port}")
        return worker
    
    def add_resource(self, name: str, resource: Any, priority: int = 5) -> None:
        """Add a generic resource to be managed during shutdown"""
        self._resource_tracker.add_resource(name, resource, priority)
    
    def add_file_handle(self, name: str, file_handle: Any) -> None:
        """Add a file handle to be managed during shutdown"""
        self._resource_tracker.add_file_handle(name, file_handle)
    
    def add_database_connection(self, name: str, connection: Any) -> None:
        """Add a database connection to be managed during shutdown"""
        self._resource_tracker.add_database_connection(name, connection)
    
    def add_cleanup_callback(self, name: str, callback: Callable) -> None:
        """Add a cleanup callback to be executed during shutdown"""
        self._resource_tracker.add_cleanup_callback(name, callback)
    
    def add_client(self, client_id: str, transport, group: Optional[str] = None) -> bool:
        """Add a client connection to be managed during shutdown"""
        return self._client_tracker.add_client(client_id, transport, group)
    
    def remove_client(self, client_id: str) -> bool:
        """Remove a client connection"""
        return self._client_tracker.remove_client(client_id)
    
    # === WORKER PROCESS MANAGEMENT (MASTER MODE) ===
    
    async def start_worker(self, repo_name: str, command: List[str]) -> bool:
        """Start a worker process (master mode only)"""
        if self.mode != "master" or repo_name not in self._workers:
            return False
        
        worker = self._workers[repo_name]
        if worker.is_running():
            self.logger.warning(f"Worker {repo_name} is already running")
            return True
        
        try:
            self.logger.info(f"Starting worker {repo_name} on port {worker.port}")
            
            # Use process groups to prevent orphans
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid  # Create new process group
            )
            
            worker.process = process
            worker.start_time = time.time()
            
            self.logger.info(f"Worker {repo_name} started with PID {process.pid}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start worker {repo_name}: {e}")
            return False
    
    def get_worker(self, repo_name: str) -> Optional[WorkerProcess]:
        """Get worker process by name"""
        if self.mode != "master":
            return None
        return self._workers.get(repo_name)
    
    def get_all_workers(self) -> List[WorkerProcess]:
        """Get all worker processes"""
        if self.mode != "master":
            return []
        return list(self._workers.values())
        
    def get_exit_code(self) -> ShutdownExitCode:
        """Get the current exit code based on shutdown status"""
        return self._exit_code_manager.determine_exit_code("shutdown")
        
    def initiate_shutdown(self, reason: str = "manual") -> bool:
        """Synchronous shutdown initiation method for signal handlers"""
        # This will initiate shutdown but not wait for completion
        # in master/worker architecture where processes handle their own shutdown
        self.logger.debug(f"Shutdown initiated: {reason}")
        self._shutdown_initiated = True
        self._shutdown_reason = reason
        return True
        
    def is_shutdown_initiated(self) -> bool:
        """Check if shutdown has been initiated"""
        return getattr(self, '_shutdown_initiated', False)
    
    # === STATUS AND MONITORING ===
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        status = {
            'mode': self.mode,
            'shutdown_in_progress': self.shutdown_in_progress,
            'completed_phases': self._completed_phases,
            'system_metrics': self.system_monitor.get_system_metrics(),
            'clients': {
                'count': len(self._client_tracker.get_all_clients()),
                'closed': self._client_tracker._closed
            },
            'resources': {
                'count': len(self._resource_tracker._resources),
                'closed': self._resource_tracker._closed
            }
        }
        
        if self.mode == "master":
            active_workers = [w for w in self._workers.values() if w.is_running()]
            status['workers'] = {
                'total': len(self._workers),
                'active': len(active_workers),
                'details': [
                    {
                        'repo_name': w.repo_name,
                        'port': w.port,
                        'running': w.is_running(),
                        'restart_count': w.restart_count
                    }
                    for w in self._workers.values()
                ]
            }
        
        if self.shutdown_start_time:
            status['shutdown_duration'] = time.time() - self.shutdown_start_time
            
        return status
    
    # === MAIN SHUTDOWN PROCESS ===
    
    async def shutdown(self, reason: str = "manual", grace_period: float = 10.0, force_timeout: float = 5.0) -> bool:
        """
        Execute comprehensive shutdown for the current mode
        
        Args:
            reason: Reason for shutdown
            grace_period: Time to wait for graceful operations
            force_timeout: Time to wait for forced operations
            
        Returns:
            True if shutdown completed successfully, False otherwise
        """
        if self._shutdown_initiated:
            self.logger.warning(f"Shutdown already initiated (reason: {self._shutdown_reason}), ignoring new request ({reason})")
            return False
        
        self._shutdown_initiated = True
        self._shutdown_reason = reason
        
        self.shutdown_in_progress = True
        self.shutdown_start_time = time.time()
        
        # Set health monitor status
        if self._health_monitor:
            self._health_monitor.set_server_status(ServerStatus.SHUTTING_DOWN)
        
        if self.mode == "master":
            return await self._shutdown_master(grace_period, force_timeout)
        else:
            return await self._shutdown_worker(grace_period, force_timeout)


    
    async def _shutdown_master(self, grace_period: float, force_timeout: float) -> bool:
        """Master shutdown: coordinate workers + cleanup master resources"""
        self.logger.info(f"🎛️ Starting master shutdown (grace: {grace_period}s, force: {force_timeout}s)")
        
        # Set server status to shutting down
        self._health_monitor.set_server_status(ServerStatus.SHUTTING_DOWN)
        
        await self.system_monitor.log_system_state(self.logger, "MASTER_SHUTDOWN_STARTING")
        
        success = True
        
        try:
            # Phase 1: Shutdown all workers
            if self._workers:
                self.logger.info(f"👷 Phase 1: Shutting down {len(self._workers)} workers")
                self._health_monitor.set_shutdown_phase(ShutdownPhase.WORKERS_STOPPING)
                worker_success = await self._shutdown_all_workers(grace_period * 0.6, force_timeout)
                if worker_success:
                    self._completed_phases.append("worker_shutdown")
                    self.logger.info("✅ Phase 1 completed: All workers shut down")
                else:
                    self.logger.warning("⚠️ Phase 1 partial: Some workers failed to shut down")
                    success = False
            else:
                self.logger.info("⏭️ Phase 1 skipped: No workers to shut down")
            
            # Phase 2: Disconnect clients
            self.logger.info("🔌 Phase 2: Disconnecting clients")
            self._health_monitor.set_shutdown_phase(ShutdownPhase.CLIENTS_DISCONNECTING)
            client_success = await self._client_tracker.disconnect_all(grace_period * 0.2)
            if client_success:
                self._completed_phases.append("client_shutdown")
                self.logger.info("✅ Phase 2 completed: All clients disconnected")
            else:
                self.logger.warning("⚠️ Phase 2 partial: Some clients failed to disconnect")
                success = False
            
            # Phase 3: Cleanup resources
            self.logger.info("🧹 Phase 3: Cleaning up master resources")
            self._health_monitor.set_shutdown_phase(ShutdownPhase.RESOURCES_CLEANING)
            resource_success = await self._resource_tracker.cleanup_all()
            if resource_success:
                self._completed_phases.append("resource_cleanup")
                self.logger.info("✅ Phase 3 completed: All resources cleaned up")
            else:
                self.logger.warning("⚠️ Phase 3 partial: Some resources failed to clean up")
                success = False
            
            # Phase 4: Final verification
            self.logger.info("🔍 Phase 4: Final verification")
            self._health_monitor.set_shutdown_phase(ShutdownPhase.VERIFICATION)
            verification_success = await self._verify_clean_shutdown()
            if verification_success:
                self._completed_phases.append("verification")
                self.logger.info("✅ Phase 4 completed: Verification passed")
            else:
                self.logger.warning("⚠️ Phase 4 partial: Verification found issues")
                success = False
            
        except Exception as e:
            self.logger.error(f"💥 Critical error during master shutdown: {e}")
            self._health_monitor.set_shutdown_phase(ShutdownPhase.FAILED)
            success = False
        
        # Set final completion phase
        if success:
            self._health_monitor.set_shutdown_phase(ShutdownPhase.COMPLETED)
        else:
            self._health_monitor.set_shutdown_phase(ShutdownPhase.FAILED)
        
        # Determine exit code
        exit_code = self._exit_code_manager.determine_exit_code(self._shutdown_reason)
        
        await self.system_monitor.log_system_state(self.logger, "MASTER_SHUTDOWN_COMPLETED")
        
        total_duration = time.time() - self.shutdown_start_time
        if success:
            self.logger.info(f"🎉 Master shutdown completed successfully in {total_duration:.3f}s")
        else:
            self.logger.error(f"💥 Master shutdown completed with errors in {total_duration:.3f}s")
        
        return success
    
    async def _shutdown_worker(self, grace_period: float, force_timeout: float) -> bool:
        """Worker shutdown: clean everything, then return (ready to be killed)"""
        self.logger.info(f"👷 Starting worker shutdown (grace: {grace_period}s, force: {force_timeout}s)")
        
        # Set server status to shutting down
        from health_monitor import ServerStatus, ShutdownPhase
        self._health_monitor.set_server_status(ServerStatus.SHUTTING_DOWN)
        
        await self.system_monitor.log_system_state(self.logger, "WORKER_SHUTDOWN_STARTING")
        
        success = True
        
        try:
            # Phase 1: Disconnect clients
            self.logger.info("🔌 Phase 1: Disconnecting clients")
            self._health_monitor.set_shutdown_phase(ShutdownPhase.CLIENTS_DISCONNECTING)
            client_success = await self._client_tracker.disconnect_all(grace_period * 0.4)
            if client_success:
                self._completed_phases.append("client_shutdown")
                self.logger.info("✅ Phase 1 completed: All clients disconnected")
            else:
                self.logger.warning("⚠️ Phase 1 partial: Some clients failed to disconnect")
                success = False
            
            # Phase 2: Cleanup resources
            self.logger.info("🧹 Phase 2: Cleaning up worker resources")
            self._health_monitor.set_shutdown_phase(ShutdownPhase.RESOURCES_CLEANING)
            resource_success = await self._resource_tracker.cleanup_all()
            if resource_success:
                self._completed_phases.append("resource_cleanup")
                self.logger.info("✅ Phase 2 completed: All resources cleaned up")
            else:
                self.logger.warning("⚠️ Phase 2 partial: Some resources failed to clean up")
                success = False
            
            # Phase 3: Final verification
            self.logger.info("🔍 Phase 3: Final verification")
            self._health_monitor.set_shutdown_phase(ShutdownPhase.VERIFICATION)
            verification_success = await self._verify_clean_shutdown()
            if verification_success:
                self._completed_phases.append("verification")
                self.logger.info("✅ Phase 3 completed: Verification passed")
            else:
                self.logger.warning("⚠️ Phase 3 partial: Verification found issues")
                success = False
            
        except Exception as e:
            self.logger.error(f"💥 Critical error during worker shutdown: {e}")
            self._health_monitor.set_shutdown_phase(ShutdownPhase.FAILED)
            success = False
        
        # Set final completion phase
        if success:
            self._health_monitor.set_shutdown_phase(ShutdownPhase.COMPLETED)
        else:
            self._health_monitor.set_shutdown_phase(ShutdownPhase.FAILED)
        
        # Determine exit code
        exit_code = self._exit_code_manager.determine_exit_code(self._shutdown_reason)
        
        await self.system_monitor.log_system_state(self.logger, "WORKER_SHUTDOWN_COMPLETED")
        
        total_duration = time.time() - self.shutdown_start_time
        if success:
            self.logger.info(f"🎉 Worker shutdown completed successfully in {total_duration:.3f}s - ready for termination")
        else:
            self.logger.error(f"💥 Worker shutdown completed with errors in {total_duration:.3f}s")
        
        return success
    
    async def _shutdown_all_workers(self, grace_period: float, force_timeout: float) -> bool:
        """Shutdown all worker processes (master mode only)"""
        if self.mode != "master" or not self._workers:
            return True
        
        workers = list(self._workers.values())
        running_workers = [w for w in workers if w.is_running()]
        
        if not running_workers:
            self.logger.info("All workers already stopped")
            return True
        
        self.logger.info(f"Shutting down {len(running_workers)} running workers")
        
        # Send shutdown requests to all workers concurrently
        shutdown_tasks = [
            self._shutdown_single_worker(worker, grace_period, force_timeout)
            for worker in running_workers
        ]
        
        results = await asyncio.gather(*shutdown_tasks, return_exceptions=True)
        
        # Check results
        success_count = sum(1 for result in results if result is True)
        total_workers = len(running_workers)
        
        if success_count == total_workers:
            self.logger.info(f"✓ All {total_workers} workers shut down successfully")
            return True
        else:
            self.logger.error(f"✗ Only {success_count}/{total_workers} workers shut down successfully")
            return False
    
    async def _shutdown_single_worker(self, worker: WorkerProcess, grace_period: float, force_timeout: float) -> bool:
        """Shutdown a single worker process"""
        if not worker.is_running():
            self.logger.info(f"Worker {worker.repo_name} already stopped")
            return True
        
        self.logger.info(f"Shutting down worker {worker.repo_name} (PID: {worker.process.pid})")
        
        try:
            # Phase 1: Try graceful shutdown via HTTP
            try:
                if aiohttp:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                        async with session.post(f"http://localhost:{worker.port}/shutdown") as response:
                            if response.status == 200:
                                self.logger.debug(f"Sent shutdown request to worker {worker.repo_name}")
                else:
                    self.logger.debug("aiohttp not available, skipping HTTP shutdown")
                
                # Wait for graceful shutdown
                grace_end = time.time() + grace_period
                while time.time() < grace_end and worker.is_running():
                    await asyncio.sleep(0.5)
                
                if not worker.is_running():
                    self.logger.info(f"✓ Worker {worker.repo_name} shut down gracefully")
                    return True
                    
            except Exception as e:
                self.logger.debug(f"HTTP shutdown failed for {worker.repo_name}: {e}")
            
            # Phase 2: SIGTERM
            if worker.is_running():
                self.logger.info(f"Sending SIGTERM to worker {worker.repo_name}")
                worker.process.terminate()
                
                try:
                    await asyncio.wait_for(
                        asyncio.create_task(self._wait_for_process_exit(worker.process)),
                        timeout=force_timeout
                    )
                    self.logger.info(f"✓ Worker {worker.repo_name} terminated gracefully")
                    return True
                except asyncio.TimeoutError:
                    self.logger.warning(f"Worker {worker.repo_name} didn't respond to SIGTERM")
            
            # Phase 3: SIGKILL
            if worker.is_running():
                self.logger.warning(f"Force killing worker {worker.repo_name}")
                try:
                    # Kill process group
                    os.killpg(os.getpgid(worker.process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    # Fall back to single process kill
                    worker.process.kill()
                
                await asyncio.wait_for(
                    asyncio.create_task(self._wait_for_process_exit(worker.process)),
                    timeout=5.0
                )
                self.logger.info(f"✓ Worker {worker.repo_name} force killed")
                return True
                
        except Exception as e:
            self.logger.error(f"✗ Failed to shutdown worker {worker.repo_name}: {e}")
            return False
        finally:
            # Clean up worker reference
            worker.process = None
    
    async def _wait_for_process_exit(self, process: subprocess.Popen) -> None:
        """Wait for a process to exit asynchronously"""
        while process.poll() is None:
            await asyncio.sleep(0.1)
    
    async def _verify_clean_shutdown(self) -> bool:
        """Verify that shutdown was clean with no remaining resources"""
        success = True
        
        # Check for remaining clients
        client_count = len(self._client_tracker.get_all_clients())
        if client_count > 0:
            self.logger.warning(f"🔌 {client_count} clients still connected after shutdown")
            success = False
        
        # Check for remaining workers (master mode)
        if self.mode == "master":
            active_workers = [w for w in self._workers.values() if w.is_running()]
            if active_workers:
                self.logger.warning(f"👷 {len(active_workers)} workers still running after shutdown")
                success = False
        
        # Check system metrics for anomalies
        try:
            metrics = self.system_monitor.get_system_metrics()
            if 'process' in metrics:
                open_files = metrics['process'].get('open_files_count', 0)
                connections = metrics['process'].get('connections_count', 0)
                
                if open_files > 10:  # Allow some baseline files
                    self.logger.warning(f"📁 {open_files} files still open after shutdown")
                
                if connections > 0:
                    self.logger.warning(f"🔗 {connections} network connections still open after shutdown")
        except Exception as e:
            self.logger.warning(f"Could not verify system metrics: {e}")
        
        return success
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        signal_name = signal.Signals(signum).name
        self.logger.info(f"🚨 Received signal {signal_name} ({signum})")
        
        # Start graceful shutdown in the background
        if not self.shutdown_in_progress:
            try:
                # Check if there's a running event loop
                loop = asyncio.get_running_loop()
                asyncio.create_task(self.shutdown(
                    reason=f"signal_{signal_name}"
                ))
            except RuntimeError:
                # No running event loop, try to create one or handle synchronously
                self.logger.warning("No running event loop for signal handler, creating new event loop")
                try:
                    # Try to run the shutdown in a new event loop
                    import threading
                    def run_shutdown():
                        asyncio.run(self.shutdown(
                            reason=f"signal_{signal_name}"
                        ))
                    
                    # Run in a separate thread to avoid blocking
                    shutdown_thread = threading.Thread(target=run_shutdown, daemon=True)
                    shutdown_thread.start()
                except Exception as e:
                    self.logger.error(f"Failed to start shutdown in new event loop: {e}")
                    # Set a flag that can be checked by the main loop
                    self._pending_signal_shutdown = {
                        'reason': f"signal_{signal_name}",
                        'grace_period': 10.0,
                        'force_timeout': 5.0
                    }

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown"""
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, self._signal_handler)
        
        self.logger.info("🎯 Signal handlers installed for graceful shutdown")

    async def _stop_workers(self) -> tuple[bool, list[str]]:
        """Stop all workers and return (success, errors)"""
        if self.mode != "master" or not self._workers:
            return True, []
        
        errors = []
        success = True
        
        for worker_name, worker in self._workers.items():
            try:
                if worker.is_running():
                    worker.process.terminate()
                    # Wait a bit for graceful shutdown
                    try:
                        worker.process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        worker.process.kill()
                        errors.append(f"Had to force kill worker {worker_name}")
                        success = False
            except Exception as e:
                errors.append(f"Error stopping worker {worker_name}: {e}")
                success = False
        
        return success, errors

    async def _disconnect_clients(self) -> tuple[bool, list[str]]:
        """Disconnect all clients and return (success, errors)"""
        return await self._client_tracker.disconnect_all_with_result()

    async def _cleanup_resources(self) -> tuple[bool, list[str]]:
        """Clean up all resources and return (success, errors)"""
        return await self._resource_tracker.cleanup_all_with_result()

    async def _verify_shutdown(self) -> tuple[bool, list[str]]:
        """Verify shutdown completed properly and return (success, errors)"""
        errors = []
        success = True
        
        # Check if any workers are still running
        if self.mode == "master":
            for worker_name, worker in self._workers.items():
                if worker.is_running():
                    errors.append(f"Worker {worker_name} still running")
                    success = False
        
        # Check if any clients are still connected
        if self._client_tracker.get_client_count() > 0:
            errors.append(f"{self._client_tracker.get_client_count()} clients still connected")
            success = False
        
        return success, errors
    
    def close(self) -> None:
        """Synchronous cleanup for emergency situations"""
        self.logger.info("🚪 Emergency close called")
        
        try:
            # This is synchronous emergency cleanup
            self._resource_tracker._closed = True
            self._client_tracker._closed = True
        except Exception as e:
            self.logger.error(f"Error during emergency close: {e}")


# === CONVENIENCE FUNCTIONS ===

def create_master_shutdown_manager(logger: logging.Logger) -> ShutdownManager:
    """Create a shutdown manager for master mode"""
    return ShutdownManager(logger, mode="master")


def create_worker_shutdown_manager(logger: logging.Logger) -> ShutdownManager:
    """Create a shutdown manager for worker mode"""
    return ShutdownManager(logger, mode="worker")
