"""
Client Connection Manager for MCP Server Shutdown System

Manages Model Context Protocol (MCP) client connections and ensures graceful 
disconnection during server shutdown.

Design Focus:
- Clean client disconnection with proper MCP protocol closure
- Connection tracking and status monitoring
- Graceful vs forced disconnection strategies
- Client notification and timeout handling
- Connection state validation and cleanup
"""

import asyncio
import json
import logging
import time
import threading
from typing import Dict, List, Any, Optional, Callable, Set
from dataclasses import dataclass
from enum import Enum


from system_utils import SystemMonitor


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
    PROTOCOL_VIOLATION = "protocol_violation"


@dataclass
class ClientInfo:
    """Information about a connected client"""
    client_id: str
    connection_time: float
    last_activity: float
    state: ClientState
    protocol_version: str
    capabilities: Dict[str, Any]
    pending_requests: int
    bytes_sent: int
    bytes_received: int
    error_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for status reporting"""
        return {
            'client_id': self.client_id,
            'connection_time': self.connection_time,
            'last_activity': self.last_activity,
            'state': self.state.value,
            'protocol_version': self.protocol_version,
            'capabilities': self.capabilities,
            'pending_requests': self.pending_requests,
            'bytes_sent': self.bytes_sent,
            'bytes_received': self.bytes_received,
            'error_count': self.error_count,
            'uptime': time.time() - self.connection_time
        }


class MCPClient:
    """Represents an MCP client connection"""
    
    def __init__(self, client_id: str, transport, logger: logging.Logger):
        self.client_id = client_id
        self.transport = transport
        self.logger = logger
        self.info = ClientInfo(
            client_id=client_id,
            connection_time=time.time(),
            last_activity=time.time(),
            state=ClientState.CONNECTING,
            protocol_version="1.0",
            capabilities={},
            pending_requests=0,
            bytes_sent=0,
            bytes_received=0,
            error_count=0
        )
        self._disconnect_callbacks: List[Callable] = []
        self._lock = threading.Lock()
    
    def add_disconnect_callback(self, callback: Callable) -> None:
        """Add callback to be called on disconnect"""
        with self._lock:
            self._disconnect_callbacks.append(callback)
    
    def update_activity(self) -> None:
        """Update last activity timestamp"""
        with self._lock:
            self.info.last_activity = time.time()
    
    def increment_pending_requests(self) -> None:
        """Increment pending request counter"""
        with self._lock:
            self.info.pending_requests += 1
    
    def decrement_pending_requests(self) -> None:
        """Decrement pending request counter"""
        with self._lock:
            self.info.pending_requests = max(0, self.info.pending_requests - 1)
    
    def add_bytes_sent(self, count: int) -> None:
        """Add to bytes sent counter"""
        with self._lock:
            self.info.bytes_sent += count
    
    def add_bytes_received(self, count: int) -> None:
        """Add to bytes received counter"""
        with self._lock:
            self.info.bytes_received += count
    
    def increment_errors(self) -> None:
        """Increment error counter"""
        with self._lock:
            self.info.error_count += 1
    
    def set_state(self, state: ClientState) -> None:
        """Set client state"""
        with self._lock:
            old_state = self.info.state
            self.info.state = state
            self.logger.debug(f"Client {self.client_id} state: {old_state.value} → {state.value}")
    
    async def send_notification(self, method: str, params: Dict[str, Any]) -> bool:
        """Send MCP notification to client"""
        try:
            message = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params
            }
            message_str = json.dumps(message)
            
            if hasattr(self.transport, 'write'):
                self.transport.write(message_str.encode() + b'\n')
                await self.transport.drain()
            elif hasattr(self.transport, 'send'):
                await self.transport.send(message_str)
            else:
                self.logger.warning(f"Unknown transport type for client {self.client_id}")
                return False
            
            self.add_bytes_sent(len(message_str))
            self.update_activity()
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send notification to client {self.client_id}: {e}")
            self.increment_errors()
            return False
    
    async def send_shutdown_notification(self, reason: DisconnectionReason, 
                                       grace_period: float) -> bool:
        """Send shutdown notification to client"""
        return await self.send_notification("server/shutdown", {
            "reason": reason.value,
            "grace_period_seconds": grace_period,
            "timestamp": time.time()
        })
    
    async def close_connection(self, reason: DisconnectionReason) -> bool:
        """Close the client connection"""
        try:
            self.set_state(ClientState.DISCONNECTING)
            
            # Call disconnect callbacks
            for callback in self._disconnect_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(self.client_id, reason)
                    else:
                        callback(self.client_id, reason)
                except Exception as e:
                    self.logger.error(f"Error in disconnect callback: {e}")
            
            # Close transport
            if hasattr(self.transport, 'close'):
                if asyncio.iscoroutinefunction(self.transport.close):
                    await self.transport.close()
                else:
                    self.transport.close()
            
            self.set_state(ClientState.DISCONNECTED)
            self.logger.info(f"✓ Client {self.client_id} disconnected ({reason.value})")
            return True
            
        except Exception as e:
            self.logger.error(f"✗ Failed to close client {self.client_id}: {e}")
            self.set_state(ClientState.ERROR)
            return False


class ClientConnectionManager:
    """Manages all MCP client connections throughout their lifecycle"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._clients: Dict[str, MCPClient] = {}
        self._client_groups: Dict[str, Set[str]] = {}  # Group name -> client IDs
        self._shutdown_in_progress = False
        self._closed = False
        self._lock = threading.Lock()
        self._system_monitor = SystemMonitor()
    
    def add_client(self, client_id: str, transport, 
                   protocol_version: str = "1.0",
                   capabilities: Optional[Dict[str, Any]] = None,
                   group: Optional[str] = None) -> MCPClient:
        """Add a new client connection"""
        if self._closed:
            self.logger.warning(f"Cannot add client {client_id} - manager is closed")
            raise RuntimeError("Client manager is closed")
        
        with self._lock:
            if client_id in self._clients:
                self.logger.warning(f"Client {client_id} already exists")
                return self._clients[client_id]
            
            client = MCPClient(client_id, transport, self.logger)
            client.info.protocol_version = protocol_version
            client.info.capabilities = capabilities or {}
            client.set_state(ClientState.CONNECTED)
            
            self._clients[client_id] = client
            
            # Add to group if specified
            if group:
                if group not in self._client_groups:
                    self._client_groups[group] = set()
                self._client_groups[group].add(client_id)
            
            self.logger.debug(f"Added client: {client_id} (group: {group})")
            return client
    
    def remove_client(self, client_id: str, reason: DisconnectionReason = DisconnectionReason.CLIENT_REQUEST) -> bool:
        """Remove a client connection"""
        with self._lock:
            if client_id not in self._clients:
                self.logger.warning(f"Client {client_id} not found")
                return False
            
            # Remove from groups
            for group_name, group_clients in self._client_groups.items():
                group_clients.discard(client_id)
            
            del self._clients[client_id]
            self.logger.debug(f"Removed client: {client_id} ({reason.value})")
            return True
    
    def get_client(self, client_id: str) -> Optional[MCPClient]:
        """Get client by ID"""
        with self._lock:
            return self._clients.get(client_id)
    
    def get_clients_by_group(self, group: str) -> List[MCPClient]:
        """Get all clients in a group"""
        with self._lock:
            if group not in self._client_groups:
                return []
            
            return [self._clients[cid] for cid in self._client_groups[group] 
                   if cid in self._clients]
    
    def get_all_clients(self) -> List[MCPClient]:
        """Get all connected clients"""
        with self._lock:
            return list(self._clients.values())
    
    async def broadcast_notification(self, method: str, params: Dict[str, Any],
                                   group: Optional[str] = None) -> Dict[str, bool]:
        """Broadcast notification to clients"""
        if group:
            clients = self.get_clients_by_group(group)
        else:
            clients = self.get_all_clients()
        
        results = {}
        for client in clients:
            success = await client.send_notification(method, params)
            results[client.client_id] = success
        
        return results
    
    async def graceful_shutdown(self, grace_period: float = 10.0,
                              force_timeout: float = 5.0) -> bool:
        """Gracefully disconnect all clients"""
        if self._shutdown_in_progress:
            self.logger.warning("Shutdown already in progress")
            return False
        
        self._shutdown_in_progress = True
        start_time = time.time()
        
        self.logger.info(f"Starting graceful client shutdown (grace: {grace_period}s, force: {force_timeout}s)")
        
        # Log system state before shutdown
        await self._system_monitor.log_system_state(self.logger, "CLIENT_SHUTDOWN_STARTING")
        
        clients = self.get_all_clients()
        if not clients:
            self.logger.info("✓ No clients to disconnect")
            self._closed = True
            return True
        
        self.logger.info(f"Disconnecting {len(clients)} clients")
        
        # Phase 1: Send shutdown notifications
        self.logger.info("Phase 1: Sending shutdown notifications")
        notification_results = await self.broadcast_notification(
            "server/shutdown", 
            {
                "reason": DisconnectionReason.SHUTDOWN.value,
                "grace_period_seconds": grace_period,
                "timestamp": time.time()
            }
        )
        
        successful_notifications = sum(1 for success in notification_results.values() if success)
        self.logger.info(f"Sent shutdown notifications to {successful_notifications}/{len(clients)} clients")
        
        # Phase 2: Wait for graceful disconnection
        self.logger.info(f"Phase 2: Waiting {grace_period}s for graceful disconnection")
        grace_end_time = time.time() + grace_period
        
        while time.time() < grace_end_time:
            remaining_clients = [c for c in self.get_all_clients() 
                               if c.info.state in [ClientState.CONNECTED, ClientState.CONNECTING]]
            
            if not remaining_clients:
                break
            
            self.logger.debug(f"Waiting for {len(remaining_clients)} clients to disconnect")
            await asyncio.sleep(0.5)
        
        # Phase 3: Force disconnect remaining clients
        remaining_clients = [c for c in self.get_all_clients() 
                           if c.info.state in [ClientState.CONNECTED, ClientState.CONNECTING]]
        
        if remaining_clients:
            self.logger.info(f"Phase 3: Force disconnecting {len(remaining_clients)} clients")
            
            # Use asyncio.gather with timeout for concurrent disconnection
            disconnect_tasks = [
                self._force_disconnect_client(client, force_timeout)
                for client in remaining_clients
            ]
            
            try:
                await asyncio.wait_for(
                    asyncio.gather(*disconnect_tasks, return_exceptions=True),
                    timeout=force_timeout
                )
            except asyncio.TimeoutError:
                self.logger.warning(f"Some clients failed to disconnect within {force_timeout}s")
        
        # Final cleanup
        final_clients = self.get_all_clients()
        success = len(final_clients) == 0
        
        total_duration = time.time() - start_time
        
        if success:
            self.logger.info(f"✓ All clients disconnected successfully in {total_duration:.3f}s")
        else:
            self.logger.error(f"✗ {len(final_clients)} clients failed to disconnect in {total_duration:.3f}s")
        
        # Log final system state
        await self._system_monitor.log_system_state(self.logger, "CLIENT_SHUTDOWN_COMPLETED")
        
        self._closed = True
        return success
    
    async def _force_disconnect_client(self, client: MCPClient, timeout: float) -> bool:
        """Force disconnect a single client with timeout"""
        try:
            return await asyncio.wait_for(
                client.close_connection(DisconnectionReason.SHUTDOWN),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            self.logger.error(f"✗ Client {client.client_id} disconnect timed out after {timeout}s")
            # Remove from our tracking even if disconnect failed
            self.remove_client(client.client_id, DisconnectionReason.TIMEOUT)
            return False
        except Exception as e:
            self.logger.error(f"✗ Error disconnecting client {client.client_id}: {e}")
            self.remove_client(client.client_id, DisconnectionReason.ERROR)
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status of all client connections"""
        with self._lock:
            clients_by_state = {}
            for state in ClientState:
                clients_by_state[state.value] = []
            
            total_bytes_sent = 0
            total_bytes_received = 0
            total_pending_requests = 0
            total_errors = 0
            
            for client in self._clients.values():
                client_info = client.info.to_dict()
                clients_by_state[client.info.state.value].append(client_info)
                
                total_bytes_sent += client.info.bytes_sent
                total_bytes_received += client.info.bytes_received
                total_pending_requests += client.info.pending_requests
                total_errors += client.info.error_count
            
            return {
                'total_clients': len(self._clients),
                'clients_by_state': clients_by_state,
                'groups': {name: list(clients) for name, clients in self._client_groups.items()},
                'shutdown_in_progress': self._shutdown_in_progress,
                'closed': self._closed,
                'statistics': {
                    'total_bytes_sent': total_bytes_sent,
                    'total_bytes_received': total_bytes_received,
                    'total_pending_requests': total_pending_requests,
                    'total_errors': total_errors
                }
            }
    
    def close(self) -> None:
        """Close the client manager (synchronous)"""
        self.logger.info("Closing client connection manager")
        self._closed = True



