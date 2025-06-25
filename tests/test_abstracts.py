"""
Abstract Base Classes for mocking process operations in shutdown tests.

These classes provide standardized interfaces for mocking system operations
during testing, allowing comprehensive testing without actual process spawning.
"""

import abc
import threading
import time
from typing import Dict, List, Optional, Callable
from enum import Enum



class ProcessState(Enum):
    """Process state enumeration."""
    RUNNING = "running"
    STOPPING = "stopping" 
    STOPPED = "stopped"
    ZOMBIE = "zombie"
    ERROR = "error"


class MockSignal(Enum):
    """Mock signal types."""
    SIGTERM = 15
    SIGKILL = 9
    SIGINT = 2


class AbstractMockProcess(abc.ABC):
    """Abstract base class for mock processes."""
    
    def __init__(self, pid: int, name: str):
        self.pid = pid
        self.name = name
        self.state = ProcessState.RUNNING
        self.exit_code: Optional[int] = None
        self.created_at = time.time()
        self.terminated_at: Optional[float] = None
        self._signals_received: List[MockSignal] = []
        self._shutdown_hooks: List[Callable] = []
        
    @abc.abstractmethod
    def send_signal(self, signal: MockSignal) -> bool:
        """Send signal to process."""
        pass
        
    @abc.abstractmethod
    def wait_for_exit(self, timeout: float) -> bool:
        """Wait for process to exit."""
        pass
        
    @abc.abstractmethod
    def is_alive(self) -> bool:
        """Check if process is alive."""
        pass
        
    @abc.abstractmethod
    def force_kill(self) -> bool:
        """Force kill the process."""
        pass
        
    def add_shutdown_hook(self, hook: Callable):
        """Add a shutdown hook to be called when process stops."""
        self._shutdown_hooks.append(hook)
        
    def _trigger_shutdown_hooks(self):
        """Trigger all shutdown hooks."""
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception:
                pass  # Ignore hook errors in tests


class CooperativeMockProcess(AbstractMockProcess):
    """Mock process that responds cooperatively to signals."""
    
    def __init__(self, pid: int, name: str, shutdown_delay: float = 0.1):
        super().__init__(pid, name)
        self.shutdown_delay = shutdown_delay
        self._shutdown_thread: Optional[threading.Thread] = None
        
    def send_signal(self, signal: MockSignal) -> bool:
        """Send signal to cooperative process."""
        if self.state != ProcessState.RUNNING:
            return False
            
        self._signals_received.append(signal)
        
        if signal in [MockSignal.SIGTERM, MockSignal.SIGINT]:
            self._start_graceful_shutdown()
            return True
        elif signal == MockSignal.SIGKILL:
            self._force_terminate()
            return True
            
        return False
        
    def _start_graceful_shutdown(self):
        """Start graceful shutdown in background."""
        if self._shutdown_thread and self._shutdown_thread.is_alive():
            return
            
        self.state = ProcessState.STOPPING
        self._shutdown_thread = threading.Thread(
            target=self._graceful_shutdown_worker,
            daemon=True
        )
        self._shutdown_thread.start()
        
    def _graceful_shutdown_worker(self):
        """Background worker for graceful shutdown."""
        time.sleep(self.shutdown_delay)
        self._trigger_shutdown_hooks()
        self.state = ProcessState.STOPPED
        self.exit_code = 0
        self.terminated_at = time.time()
        
    def _force_terminate(self):
        """Force terminate immediately."""
        self.state = ProcessState.STOPPED
        self.exit_code = -9
        self.terminated_at = time.time()
        self._trigger_shutdown_hooks()
        
    def wait_for_exit(self, timeout: float) -> bool:
        """Wait for process to exit."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.state == ProcessState.STOPPED:
                return True
            time.sleep(0.01)
        return False
        
    def is_alive(self) -> bool:
        """Check if process is alive."""
        return self.state in [ProcessState.RUNNING, ProcessState.STOPPING]
        
    def force_kill(self) -> bool:
        """Force kill the process."""
        if self.state == ProcessState.STOPPED:
            return True
        self._force_terminate()
        return True


class UnresponsiveMockProcess(AbstractMockProcess):
    """Mock process that doesn't respond to signals."""
    
    def __init__(self, pid: int, name: str, kill_resistant: bool = False):
        super().__init__(pid, name)
        self.kill_resistant = kill_resistant
        
    def send_signal(self, signal: MockSignal) -> bool:
        """Send signal to unresponsive process."""
        self._signals_received.append(signal)
        
        # Only respond to SIGKILL if not kill-resistant
        if signal == MockSignal.SIGKILL and not self.kill_resistant:
            self._force_terminate()
            return True
            
        # Ignore all other signals
        return False
        
    def _force_terminate(self):
        """Force terminate."""
        self.state = ProcessState.STOPPED
        self.exit_code = -9
        self.terminated_at = time.time()
        self._trigger_shutdown_hooks()
        
    def wait_for_exit(self, timeout: float) -> bool:
        """Wait for process to exit (will timeout)."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.state == ProcessState.STOPPED:
                return True
            time.sleep(0.01)
        return False
        
    def is_alive(self) -> bool:
        """Check if process is alive."""
        return self.state != ProcessState.STOPPED
        
    def force_kill(self) -> bool:
        """Force kill the process."""
        if self.kill_resistant:
            return False
        self._force_terminate()
        return True


class ZombieMockProcess(AbstractMockProcess):
    """Mock process that becomes a zombie."""
    
    def __init__(self, pid: int, name: str):
        super().__init__(pid, name)
        
    def send_signal(self, signal: MockSignal) -> bool:
        """Send signal to zombie process."""
        self._signals_received.append(signal)
        
        # Zombie becomes a proper zombie instead of stopping
        if signal in [MockSignal.SIGTERM, MockSignal.SIGKILL]:
            self.state = ProcessState.ZOMBIE
            self.terminated_at = time.time()
            return True
            
        return False
        
    def wait_for_exit(self, timeout: float) -> bool:
        """Wait for process to exit (zombies never properly exit)."""
        return False
        
    def is_alive(self) -> bool:
        """Zombies are technically alive but not functioning."""
        return self.state != ProcessState.STOPPED
        
    def force_kill(self) -> bool:
        """Can't kill zombies."""
        return False


class AbstractMockPort(abc.ABC):
    """Abstract base class for mock port operations."""
    
    def __init__(self, port: int):
        self.port = port
        self.is_bound = False
        self.process_pid: Optional[int] = None
        
    @abc.abstractmethod
    def bind(self, pid: int) -> bool:
        """Bind port to process."""
        pass
        
    @abc.abstractmethod
    def release(self) -> bool:
        """Release port."""
        pass
        
    @abc.abstractmethod
    def is_free(self) -> bool:
        """Check if port is free."""
        pass
        
    @abc.abstractmethod
    def force_release(self) -> bool:
        """Force release port."""
        pass


class CooperativeMockPort(AbstractMockPort):
    """Mock port that releases cleanly when requested."""
    
    def __init__(self, port: int, release_delay: float = 0.05):
        super().__init__(port)
        self.release_delay = release_delay
        self._release_thread: Optional[threading.Thread] = None
        
    def bind(self, pid: int) -> bool:
        """Bind port to process."""
        if self.is_bound:
            return False
        self.is_bound = True
        self.process_pid = pid
        return True
        
    def release(self) -> bool:
        """Release port with delay."""
        if not self.is_bound:
            return True
            
        if self._release_thread and self._release_thread.is_alive():
            return False  # Already releasing
            
        self._release_thread = threading.Thread(
            target=self._delayed_release,
            daemon=True
        )
        self._release_thread.start()
        return True
        
    def _delayed_release(self):
        """Release port after delay."""
        time.sleep(self.release_delay)
        self.is_bound = False
        self.process_pid = None
        
    def is_free(self) -> bool:
        """Check if port is free."""
        return not self.is_bound
        
    def force_release(self) -> bool:
        """Force release port immediately."""
        self.is_bound = False
        self.process_pid = None
        return True


class StickyMockPort(AbstractMockPort):
    """Mock port that refuses to release."""
    
    def __init__(self, port: int, force_releasable: bool = True):
        super().__init__(port)
        self.force_releasable = force_releasable
        
    def bind(self, pid: int) -> bool:
        """Bind port to process."""
        if self.is_bound:
            return False
        self.is_bound = True
        self.process_pid = pid
        return True
        
    def release(self) -> bool:
        """Refuse to release port."""
        return False
        
    def is_free(self) -> bool:
        """Check if port is free."""
        return not self.is_bound
        
    def force_release(self) -> bool:
        """Force release port if allowed."""
        if self.force_releasable:
            self.is_bound = False
            self.process_pid = None
            return True
        return False


class AbstractMockClient(abc.ABC):
    """Abstract base class for mock client connections."""
    
    def __init__(self, client_id: str, worker_id: str):
        self.client_id = client_id
        self.worker_id = worker_id
        self.connected = True
        self.last_activity = time.time()
        
    @abc.abstractmethod
    def send_shutdown_notification(self) -> bool:
        """Send shutdown notification to client."""
        pass
        
    @abc.abstractmethod
    def disconnect_gracefully(self, timeout: float) -> bool:
        """Disconnect client gracefully."""
        pass
        
    @abc.abstractmethod
    def force_disconnect(self) -> bool:
        """Force disconnect client."""
        pass
        
    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Check if client is connected."""
        pass
        
    def update_activity(self):
        """Update last activity time."""
        self.last_activity = time.time()


class CooperativeMockClient(AbstractMockClient):
    """Mock client that disconnects cooperatively."""
    
    def __init__(self, client_id: str, worker_id: str, disconnect_delay: float = 0.1):
        super().__init__(client_id, worker_id)
        self.disconnect_delay = disconnect_delay
        self._disconnect_thread: Optional[threading.Thread] = None
        self.shutdown_notification_sent = False
        
    def send_shutdown_notification(self) -> bool:
        """Send shutdown notification to client."""
        if not self.connected:
            return False
        self.shutdown_notification_sent = True
        return True
        
    def disconnect_gracefully(self, timeout: float) -> bool:
        """Disconnect client gracefully."""
        if not self.connected:
            return True
            
        if self._disconnect_thread and self._disconnect_thread.is_alive():
            return False  # Already disconnecting
            
        self._disconnect_thread = threading.Thread(
            target=self._delayed_disconnect,
            daemon=True
        )
        self._disconnect_thread.start()
        
        # Wait for disconnect to complete
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.connected:
                return True
            time.sleep(0.01)
        return False
        
    def _delayed_disconnect(self):
        """Disconnect after delay."""
        time.sleep(self.disconnect_delay)
        self.connected = False
        
    def force_disconnect(self) -> bool:
        """Force disconnect client immediately."""
        self.connected = False
        return True
        
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self.connected


class UnresponsiveMockClient(AbstractMockClient):
    """Mock client that doesn't respond to shutdown requests."""
    
    def __init__(self, client_id: str, worker_id: str):
        super().__init__(client_id, worker_id)
        self.shutdown_notification_sent = False
        
    def send_shutdown_notification(self) -> bool:
        """Send shutdown notification (client ignores it)."""
        if not self.connected:
            return False
        self.shutdown_notification_sent = True
        return True
        
    def disconnect_gracefully(self, timeout: float) -> bool:
        """Try to disconnect gracefully (will timeout)."""
        # Client ignores graceful disconnect requests
        time.sleep(min(timeout, 0.1))  # Simulate some delay
        return False
        
    def force_disconnect(self) -> bool:
        """Force disconnect client."""
        self.connected = False
        return True
        
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self.connected


class MockProcessRegistry:
    """Registry for managing mock processes during tests."""
    
    def __init__(self):
        self.processes: Dict[int, AbstractMockProcess] = {}
        self.ports: Dict[int, AbstractMockPort] = {}
        self.clients: Dict[str, AbstractMockClient] = {}
        self._next_pid = 1000
        
    def create_cooperative_process(self, name: str, shutdown_delay: float = 0.1) -> CooperativeMockProcess:
        """Create a cooperative mock process."""
        pid = self._next_pid
        self._next_pid += 1
        process = CooperativeMockProcess(pid, name, shutdown_delay)
        self.processes[pid] = process
        return process
        
    def create_unresponsive_process(self, name: str, kill_resistant: bool = False) -> UnresponsiveMockProcess:
        """Create an unresponsive mock process."""
        pid = self._next_pid
        self._next_pid += 1
        process = UnresponsiveMockProcess(pid, name, kill_resistant)
        self.processes[pid] = process
        return process
        
    def create_zombie_process(self, name: str) -> ZombieMockProcess:
        """Create a zombie mock process."""
        pid = self._next_pid
        self._next_pid += 1
        process = ZombieMockProcess(pid, name)
        self.processes[pid] = process
        return process
        
    def create_cooperative_port(self, port: int, release_delay: float = 0.05) -> CooperativeMockPort:
        """Create a cooperative mock port."""
        mock_port = CooperativeMockPort(port, release_delay)
        self.ports[port] = mock_port
        return mock_port
        
    def create_sticky_port(self, port: int, force_releasable: bool = True) -> StickyMockPort:
        """Create a sticky mock port."""
        mock_port = StickyMockPort(port, force_releasable)
        self.ports[port] = mock_port
        return mock_port
        
    def create_cooperative_client(self, client_id: str, worker_id: str, 
                                 disconnect_delay: float = 0.1) -> CooperativeMockClient:
        """Create a cooperative mock client."""
        client = CooperativeMockClient(client_id, worker_id, disconnect_delay)
        self.clients[client_id] = client
        return client
        
    def create_unresponsive_client(self, client_id: str, worker_id: str) -> UnresponsiveMockClient:
        """Create an unresponsive mock client."""
        client = UnresponsiveMockClient(client_id, worker_id)
        self.clients[client_id] = client
        return client
        
    def get_process(self, pid: int) -> Optional[AbstractMockProcess]:
        """Get process by PID."""
        return self.processes.get(pid)
        
    def get_port(self, port: int) -> Optional[AbstractMockPort]:
        """Get port by number."""
        return self.ports.get(port)
        
    def get_client(self, client_id: str) -> Optional[AbstractMockClient]:
        """Get client by ID."""
        return self.clients.get(client_id)
        
    def list_alive_processes(self) -> List[AbstractMockProcess]:
        """List all alive processes."""
        return [p for p in self.processes.values() if p.is_alive()]
        
    def list_zombie_processes(self) -> List[AbstractMockProcess]:
        """List all zombie processes."""
        return [p for p in self.processes.values() if p.state == ProcessState.ZOMBIE]
        
    def list_bound_ports(self) -> List[AbstractMockPort]:
        """List all bound ports."""
        return [p for p in self.ports.values() if p.is_bound]
        
    def list_connected_clients(self) -> List[AbstractMockClient]:
        """List all connected clients."""
        return [c for c in self.clients.values() if c.is_connected()]
        
    def cleanup_all(self):
        """Cleanup all mock objects."""
        for process in self.processes.values():
            if process.is_alive():
                process.force_kill()
        for port in self.ports.values():
            if port.is_bound:
                port.force_release()
        for client in self.clients.values():
            if client.is_connected():
                client.force_disconnect()
                
        self.processes.clear()
        self.ports.clear()
        self.clients.clear()
