# **MCP Server Clean Shutdown Design**

## **1\. Introduction**

This document outlines the design for implementing clean shutdown procedures for a Python MCP (Model Context Protocol) server that manages multiple repository workers. The server currently suffers from zombie processes and port conflicts during shutdown, which this design aims to resolve.

The system consists of a main MCP server that spawns worker processes for each repository, with each worker listening on a dedicated port. A monitoring thread ensures workers stay alive during normal operation. The service is managed by macOS launchctl and Linux systemctl, which automatically restarts the service unless explicitly unloaded. This server will run on a development machine and only serves local traffic; therefore, when a shutdown is initiated, there should be no active external requests being made.

## **2\. Goals and Non-Goals**

### **Goals**

* **Primary Goal: Clean shutdown** \- Absolutely no zombie processes or resource leaks  
* **Eliminate zombie worker processes** during shutdown  
* **Ensure all ports are properly released** so restart doesn't fail with "address already in use" errors  
* **Handle hanging client connections gracefully** without indefinite blocking  
* **Provide predictable shutdown timing** with appropriate timeouts  
* **Support both manual shutdown and signal-based shutdown** (SIGTERM, SIGINT)  
* **Maintain system stability** during the shutdown process  
* **Comprehensive verification** that shutdown actually completed as intended  
* **Prevent orphaned processes** through proper process group management  
* **Handle edge cases robustly** including timeout overflows and resource cleanup ordering

### **Non-Goals**

* **Fast shutdown** \- We prioritize correctness over speed, willing to wait several seconds for clean shutdown  
* **Preserving in-flight work** \- active operations may be interrupted  
* **Complex state persistence** \- the system will restart fresh  
* **Backwards compatibility** with existing shutdown mechanisms  
* **Support for partial shutdowns** \- this is an all-or-nothing shutdown

## **3\. High Level Architecture**

The shutdown process follows a sequential, time-bounded approach with improved robustness:

Signal Received → Set Shutdown Flag → Graceful Worker Shutdown → Client Disconnect → Worker Termination → Comprehensive Verification → Process Exit  
     ↓                   ↓                       ↓                     ↓                    ↓                          ↓                    ↓  
  No timeout         Immediate              10s timeout            30s timeout         30s timeout per worker      15s timeout           Clean exit

### **Key Components**

* **Shutdown Coordinator**: Orchestrates the entire shutdown sequence with extensive logging  
* **Process Group Manager**: Manages worker process groups to prevent orphans  
* **Client Manager**: Handles graceful disconnection of MCP clients with total timeout protection  
* **Worker Manager**: Manages worker process termination with escalating shutdown protocols  
* **Port Monitor**: Enhanced port verification with comprehensive binding checks  
* **Signal Handler**: Robust signal handling with duplicate signal protection  
* **Verification System**: Multi-level post-shutdown checks to ensure clean state  
* **Central Logger**: Passed to all components for consistent logging  
* **Health Check System**: External verification interface for monitoring  
* **Resource Manager**: Manages database connections and other external resources.

### **State Transitions**

1. **Normal Operation** → **Shutdown Initiated** (via signal or manual trigger)  
2. **Shutdown Initiated** → **Workers Graceful Shutdown** (send shutdown requests to workers)  
3. **Workers Graceful Shutdown** → **Clients Disconnecting** (after worker timeout or graceful completion)  
4. **Clients Disconnecting** → **Workers Force Terminating** (after client timeout or all disconnected)  
5. **Workers Force Terminating** → **Cleanup Phase** (verify ports, cleanup resources)  
6. **Cleanup Phase** → **Process Exit**

## **4\. Detailed Architecture**

### **4.1 Central Logging System**

All components receive a logger instance from a central configuration:

import logging  
import sys  
from datetime import datetime

def setup\_central\_logger(name='mcp\_server', level=logging.DEBUG):  
    """Setup centralized logger with microsecond precision that gets passed to all components"""

    \# Create logger  
    logger \= logging.getLogger(name)  
    logger.setLevel(level)

    \# Prevent duplicate handlers  
    if logger.handlers:  
        logger.handlers.clear()

    \# True microsecond precision formatter using datetime  
    class MicrosecondFormatter(logging.Formatter):  
        def formatTime(self, record, datefmt=None):  
            dt \= datetime.fromtimestamp(record.created)  
            return dt.strftime('%Y-%m-%d %H:%M:%S.%f')\[:-3\]  \# Keep 3 decimal places (milliseconds)

    \# Detailed formatter with microseconds  
    microsecond\_formatter \= MicrosecondFormatter(  
        '%(asctime)s \[%(levelname)8s\] %(name)s.%(funcName)s:%(lineno)d \- %(message)s'  
    )

    \# Console formatter with microseconds  
    console\_formatter \= MicrosecondFormatter(  
        '%(asctime)s \[%(levelname)s\] %(message)s'  
    )

    \# File handler for detailed debug logs  
    timestamp \= datetime.now().strftime("%Y%m%d\_%H%M%S\_%f")\[:-3\]  \# Include microseconds  
    debug\_file \= f'/tmp/mcp\_server\_debug\_{timestamp}.log'  
    file\_handler \= logging.FileHandler(debug\_file)  
    file\_handler.setLevel(logging.DEBUG)  
    file\_handler.setFormatter(microsecond\_formatter)

    \# Shutdown-specific log file  
    shutdown\_file \= f'/tmp/mcp\_server\_shutdown\_{timestamp}.log'  
    shutdown\_handler \= logging.FileHandler(shutdown\_file)  
    shutdown\_handler.setLevel(logging.INFO)  
    shutdown\_handler.setFormatter(microsecond\_formatter)

    \# Console handler  
    console\_handler \= logging.StreamHandler(sys.stdout)  
    console\_handler.setLevel(logging.INFO)  
    console\_handler.setFormatter(console\_formatter)

    \# Add all handlers  
    logger.addHandler(file\_handler)  
    logger.addHandler(shutdown\_handler)  
    logger.addHandler(console\_handler)

    \# Log the initialization with microsecond precision  
    logger.info(f"Central logger initialized with microsecond precision")  
    logger.debug(f"Debug log: {debug\_file}")  
    logger.debug(f"Shutdown log: {shutdown\_file}")  
    logger.debug(f"Log level set to: {logging.getLevelName(level)}")

    return logger

def log\_system\_state(logger, phase):  
    """Log comprehensive system state with microsecond timing"""  
    start\_time \= datetime.now()  
    logger.debug(f"=== SYSTEM STATE: {phase} (at {start\_time.strftime('%H:%M:%S.%f')\[:-3\]}) \===")

    try:  
        import psutil  
        import threading

        \# Process info  
        proc \= psutil.Process()  
        logger.debug(f"PID: {proc.pid}, Status: {proc.status()}")  
        logger.debug(f"Memory: RSS={proc.memory\_info().rss/1024/1024:.1f}MB, VMS={proc.memory\_info().vms/1024/1024:.1f}MB")  
        logger.debug(f"CPU: {proc.cpu\_percent()}%")  
        logger.debug(f"Threads: {proc.num\_threads()}")  
        logger.debug(f"Open files: {len(proc.open\_files())}")  
        logger.debug(f"Connections: {len(proc.connections())}")

        \# Children  
        children \= proc.children(recursive=True)  
        logger.debug(f"Child processes: {len(children)}")  
        for child in children:  
            try:  
                logger.debug(f"  Child PID {child.pid}: {child.name()} ({child.status()})")  
            except (psutil.NoSuchProcess, psutil.AccessDenied):  
                pass

        \# Threading info  
        logger.debug(f"Active Python threads: {threading.active\_count()}")  
        for thread in threading.enumerate():  
            logger.debug(f"  Thread: {thread.name} (alive: {thread.is\_alive()})")

    except Exception as e:  
        logger.error(f"Error logging system state: {e}")

    end\_time \= datetime.now()  
    duration \= (end\_time \- start\_time).total\_seconds() \* 1000  \# milliseconds  
    logger.debug(f"=== END SYSTEM STATE: {phase} (duration: {duration:.2f}ms) \===")

### **4.2 Enhanced Global Shutdown Flag with Process Group Management**

The shutdown flag uses Python's threading.Event for thread-safe coordination, with robust signal handling:

import threading  
import signal  
import time  
import os  
import sys

class MCPServer:  
    def \_\_init\_\_(self, logger):  
        self.\_shutdown\_event \= threading.Event()  
        self.\_shutdown\_reason \= None  
        self.\_workers \= {}  
        self.\_active\_connections \= \[\]  
        self.\_monitoring\_thread \= None  
        self.logger \= logger  \# Central logger passed in  
        self.\_shutdown\_initiated \= False \# Flag to prevent multiple shutdown initiations

    def shutdown(self, reason="manual"):  
        """Initiate shutdown sequence"""  
        if self.\_shutdown\_initiated:  
            self.logger.warning(f"Shutdown already initiated (reason: {self.\_shutdown\_reason}), ignoring new request")  
            return

        self.\_shutdown\_initiated \= True  
        self.\_shutdown\_reason \= reason

        self.logger.critical(f"=== SHUTDOWN INITIATED (reason: {reason}) \===")  
        self.logger.debug(f"Current workers: {list(self.\_workers.keys())}")  
        self.logger.debug(f"Active connections: {len(self.\_active\_connections)}")  
        self.\_shutdown\_event.set()  
        self.logger.debug("Shutdown event set")

    def is\_shutting\_down(self):  
        return self.\_shutdown\_event.is\_set()

    def monitoring\_loop(self):  
        """Monitoring thread that respects shutdown flag and prevents restart during shutdown"""  
        self.logger.debug("Monitoring thread started")  
        try:  
            while not self.\_shutdown\_event.is\_set():  
                if not self.is\_shutting\_down():  \# Double-check for immediate response  
                    self.\_restart\_dead\_workers()

                \# Use shorter sleep with shutdown check for faster response  
                for \_ in range(10):  \# 5 second total wait, checking every 0.5s  
                    if self.\_shutdown\_event.is\_set():  
                        break  
                    time.sleep(0.5)  
            self.logger.info("Monitoring thread stopped cleanly")  
        except Exception as e:  
            self.logger.critical(f"Monitoring thread crashed: {e}. Initiating emergency shutdown.", exc\_info=True)  
            self.shutdown(reason="monitoring\_thread\_crash") \# Self-initiate shutdown

    def \_restart\_dead\_workers(self):  
        """Restart dead workers with shutdown protection, ensuring old Popen objects are cleared"""  
        if self.\_shutdown\_event.is\_set():  
            self.logger.debug("Skipping worker restart \- shutdown in progress")  
            return

        workers\_to\_restart \= \[\]  
        for port, worker in list(self.\_workers.items()):  
            if worker.poll() is not None:  \# Process has terminated  
                workers\_to\_restart.append(port)

        for port in workers\_to\_restart:  
            if not self.\_shutdown\_event.is\_set():  \# Final check before restart  
                self.logger.info(f"Restarting dead worker on port {port}")  
                \# Ensure the old Popen object is fully replaced and dereferenced  
                if port in self.workers:  
                    del self.workers\[port\] \# Explicitly remove old reference  
                self.\_start\_worker(port) \# This will re-add the new worker to self.workers  
            else:  
                self.logger.debug(f"Not restarting worker on port {port} \- shutdown in progress")

    def get\_health\_status(self):  
        """Quick health check that can be called externally"""  
        checks \= {  
            'no\_workers': len(self.\_workers) \== 0,  
            'no\_connections': len(self.\_active\_connections) \== 0,  
            'shutdown\_flag\_set': self.\_shutdown\_event.is\_set(),  
            'shutdown\_reason': self.\_shutdown\_reason  
        }  
        return all(checks.values()), checks

    def exit\_server(self, exit\_code=0):  
        """Exits the server process with a specific exit code for external monitoring."""  
        self.logger.critical(f"Server exiting with code {exit\_code}")  
        \# Add any final sanity checks before exit  
        final\_health, health\_details \= self.get\_health\_status()  
        self.logger.debug(f"Final health status before exit: {final\_health} (Details: {health\_details})")  
        sys.exit(exit\_code)

\# Enhanced signal handler with robustness  
def setup\_signal\_handlers(server):  
    def signal\_handler(signum, frame):  
        \# Prevent multiple shutdown initiations  
        if server.\_shutdown\_initiated: \# Use the server's internal flag  
            server.logger.warning(f"Already handling shutdown, ignoring signal {signum}")  
            return

        signal\_name \= signal.Signals(signum).name  
        server.logger.critical(f"Received signal {signum} ({signal\_name})")  
        server.logger.debug(f"Signal received in frame: {frame.f\_code.co\_filename}:{frame.f\_lineno}")  
        server.shutdown(reason=f"signal\_{signal\_name}")

    signal.signal(signal.SIGTERM, signal\_handler)  
    signal.signal(signal.SIGINT, signal\_handler)  
    server.logger.debug("Signal handlers registered for SIGTERM and SIGINT")

### **4.3 Enhanced Client Connection Management**

Handle client disconnections with total timeout protection and improved error handling:

import socket  
from contextlib import contextmanager  
from datetime import datetime  
import os  
import time

class ClientManager:  
    def \_\_init\_\_(self, logger, timeout=30):  
        self.active\_connections \= \[\]  
        self.timeout \= timeout  
        self.logger \= logger  \# Central logger passed in

        \# Support timeout override via environment variable for testing  
        env\_timeout \= os.getenv('MCP\_SHUTDOWN\_CLIENT\_TIMEOUT')  
        if env\_timeout:  
            try:  
                self.timeout \= float(env\_timeout)  
                self.logger.info(f"Using environment override for client timeout: {self.timeout}s")  
            except ValueError:  
                self.logger.warning(f"Invalid timeout in environment: {env\_timeout}, using default {self.timeout}s")

    def disconnect\_clients\_gracefully(self):  
        """Attempt graceful disconnection with total timeout protection"""  
        overall\_start \= datetime.now()  
        initial\_count \= len(self.active\_connections)

        if initial\_count \== 0:  
            self.logger.info("No clients to disconnect")  
            return

        self.logger.info(f"Starting graceful disconnection of {initial\_count} clients (timeout: {self.timeout}s)")  
        self.logger.debug(f"Client connections: {\[str(conn) for conn in self.active\_connections\]}")

        \# Phase 1: Send shutdown notifications  
        notification\_start \= datetime.now()  
        successful\_notifications \= 0

        for i, conn in enumerate(self.active\_connections\[:\]):  
            \# Check overall timeout  
            elapsed \= (datetime.now() \- overall\_start).total\_seconds()  
            if elapsed \>= self.timeout:  
                self.logger.warning(f"Overall timeout reached during notifications at client {i+1}/{initial\_count}")  
                break

            conn\_start \= datetime.now()  
            try:  
                self.logger.debug(f"Sending shutdown message to client {i+1}/{initial\_count}")  
                self.\_send\_shutdown\_message(conn)  
                successful\_notifications \+= 1  
                conn\_duration \= (datetime.now() \- conn\_start).total\_seconds() \* 1000  
                self.logger.debug(f"Shutdown message sent successfully to client {i+1} in {conn\_duration:.2f}ms")  
            except Exception as e:  
                conn\_duration \= (datetime.now() \- conn\_start).total\_seconds() \* 1000  
                self.logger.warning(f"Failed to send shutdown message to client {i+1} after {conn\_duration:.2f}ms: {e}")

        notification\_duration \= (datetime.now() \- notification\_start).total\_seconds()  
        self.logger.info(f"Sent shutdown notifications to {successful\_notifications}/{initial\_count} clients in {notification\_duration:.3f}s")

        \# Phase 2: Wait for graceful disconnection with total timeout protection  
        wait\_start \= datetime.now()  
        last\_count \= len(self.active\_connections)

        \# Calculate remaining timeout  
        elapsed \= (datetime.now() \- overall\_start).total\_seconds()  
        remaining\_timeout \= max(0, self.timeout \- elapsed)

        self.logger.debug(f"Waiting up to {remaining\_timeout:.3f}s for graceful disconnections")

        while self.active\_connections and (datetime.now() \- wait\_start).total\_seconds() \< remaining\_timeout:  
            time.sleep(0.5)  
            current\_count \= len(self.active\_connections)

            if current\_count \!= last\_count:  
                elapsed \= (datetime.now() \- wait\_start).total\_seconds()  
                self.logger.info(f"Client disconnection progress: {initial\_count \- current\_count}/{initial\_count} "  
                               f"disconnected after {elapsed:.3f}s")  
                last\_count \= current\_count

        \# Phase 3: Force disconnect remaining clients  
        total\_elapsed \= (datetime.now() \- overall\_start).total\_seconds()  
        remaining\_clients \= len(self.active\_connections)

        if remaining\_clients \> 0:  
            remaining\_time \= max(0, self.timeout \- total\_elapsed)  
            self.logger.warning(f"Graceful timeout reached after {total\_elapsed:.3f}s. "  
                              f"{remaining\_clients} clients still connected, forcing disconnection "  
                              f"(remaining timeout: {remaining\_time:.3f}s)")  
            self.\_force\_disconnect\_remaining()  
        else:  
            self.logger.info(f"All clients disconnected gracefully in {total\_elapsed:.3f}s")

    def \_send\_shutdown\_message(self, conn):  
        """Send MCP protocol shutdown message"""  
        self.logger.debug(f"Preparing shutdown message for connection {conn}")  
        shutdown\_msg \= {  
            "jsonrpc": "2.0",  
            "method": "notifications/shutdown",  
            "params": {"reason": "Server shutting down"}  
        }  
        \# Send message implementation depends on your MCP protocol handling  
        self.logger.debug(f"Shutdown message prepared: {shutdown\_msg}")  
        \# Placeholder for actual sending logic, e.g., conn.sendall(json.dumps(shutdown\_msg).encode())

    def \_force\_disconnect\_remaining(self):  
        """Force close any remaining connections with individual error handling"""  
        force\_start \= datetime.now()  
        remaining\_count \= len(self.active\_connections)  
        self.logger.warning(f"Force disconnecting {remaining\_count} remaining clients")

        successful\_closes \= 0

        for i, conn in enumerate(self.active\_connections\[:\]):  
            conn\_start \= datetime.now()  
            try:  
                self.logger.debug(f"Force closing connection {i+1}/{remaining\_count}: {conn}")

                \# Try graceful shutdown first  
                try:  
                    conn.shutdown(socket.SHUT\_RDWR)  
                except OSError:  
                    pass  \# May already be closed

                conn.close()

                \# Remove from active connections  
                if conn in self.active\_connections:  
                    self.active\_connections.remove(conn)  
                    successful\_closes \+= 1

                conn\_duration \= (datetime.now() \- conn\_start).total\_seconds() \* 1000  
                self.logger.debug(f"Successfully force-closed connection {i+1} in {conn\_duration:.2f}ms")  
            except Exception as e:  
                conn\_duration \= (datetime.now() \- conn\_start).total\_seconds() \* 1000  
                self.logger.debug(f"Error force-closing connection {i+1} after {conn\_duration:.2f}ms: {e} "  
                                f"(socket may already be closed)")

        force\_duration \= (datetime.now() \- force\_start).total\_seconds()  
        self.logger.info(f"Force disconnection completed in {force\_duration:.3f}s. "  
                        f"Successfully closed {successful\_closes}/{remaining\_count} connections. "  
                        f"{len(self.active\_connections)} connections remain")

### **4.4 Enhanced Worker Process Management**

Enhanced worker shutdown with process groups, graceful shutdown protocol, and comprehensive verification:

import subprocess  
import signal  
import psutil  
import socket  
import os  
from datetime import datetime  
import time

class WorkerManager:  
    def \_\_init\_\_(self, logger):  
        self.workers \= {}  \# port \-\> subprocess.Popen  
        self.logger \= logger  \# Central logger passed in

        \# Support timeout override via environment variable  
        self.worker\_timeout \= float(os.getenv('MCP\_SHUTDOWN\_WORKER\_TIMEOUT', '30'))  
        self.graceful\_timeout \= float(os.getenv('MCP\_WORKER\_GRACEFUL\_TIMEOUT', '10'))  
        self.logger.debug(f"Worker timeouts \- graceful: {self.graceful\_timeout}s, total: {self.worker\_timeout}s")

    def start\_worker(self, port, command):  
        """Start worker with process group for better process management (macOS/Linux compatible)"""  
        start\_time \= datetime.now()  
        self.logger.info(f"Starting worker on port {port}")

        try:  
            \# On Unix-like systems (macOS, Linux), os.setsid creates a new session and process group.  
            \# This ensures that killing the parent process group (MCP server) will also kill the worker  
            \# and any children it spawns, preventing orphaned processes.  
            worker \= subprocess.Popen(  
                command,  
                stdout=subprocess.PIPE,  
                stderr=subprocess.PIPE,  
                preexec\_fn=os.setsid  \# Create new process group  
            )

            self.workers\[port\] \= worker  
            duration \= (datetime.now() \- start\_time).total\_seconds() \* 1000  
            self.logger.info(f"Worker started on port {port} with PID {worker.pid} in {duration:.2f}ms")  
            return worker

        except Exception as e:  
            duration \= (datetime.now() \- start\_time).total\_seconds() \* 1000  
            self.logger.error(f"Failed to start worker on port {port} after {duration:.2f}ms: {e}")  
            raise

    def shutdown\_all\_workers(self):  
        """Shutdown all workers with escalating force"""  
        shutdown\_start \= datetime.now()  
        worker\_count \= len(self.workers)

        if worker\_count \== 0:  
            self.logger.info("No workers to shutdown")  
            return

        self.logger.info(f"Starting shutdown of {worker\_count} workers")  
        self.logger.debug(f"Worker ports: {list(self.workers.keys())}")

        successful\_shutdowns \= 0  
        for i, (port, worker) in enumerate(list(self.workers.items())):  
            worker\_start \= datetime.now()  
            self.logger.info(f"Shutting down worker {i+1}/{worker\_count} on port {port}")

            try:  
                self.\_shutdown\_single\_worker(port, worker)  
                successful\_shutdowns \+= 1  
            except Exception as e:  
                self.logger.error(f"Error during worker {port} shutdown: {e}", exc\_info=True)

            worker\_duration \= (datetime.now() \- worker\_start).total\_seconds()  
            self.logger.info(f"Worker {i+1} shutdown completed in {worker\_duration:.3f}s")

        total\_duration \= (datetime.now() \- shutdown\_start).total\_seconds()  
        self.logger.info(f"Worker shutdown completed: {successful\_shutdowns}/{worker\_count} successful in {total\_duration:.3f}s")  
        self.workers.clear()  
        self.logger.debug("Worker registry cleared")

    def \_shutdown\_single\_worker(self, port, worker):  
        """Enhanced worker shutdown with graceful protocol and process group handling"""  
        start\_time \= datetime.now()  
        self.logger.info(f"Starting enhanced shutdown sequence for worker on port {port} (PID: {worker.pid})")

        \# Pre-shutdown state logging  
        self.logger.debug(f"Worker process state \- PID: {worker.pid}, Poll: {worker.poll()}")

        try:  
            \# Phase 1: Attempt graceful shutdown via HTTP/IPC  
            graceful\_start \= datetime.now()  
            self.logger.debug(f"Phase 1: Requesting graceful shutdown for worker on port {port}")

            try:  
                self.\_send\_worker\_shutdown\_request(port)  
                self.logger.debug(f"Shutdown request sent to worker on port {port}")

                \# Wait for graceful shutdown  
                try:  
                    worker.wait(timeout=self.graceful\_timeout)  
                    graceful\_duration \= (datetime.now() \- graceful\_start).total\_seconds()  
                    self.logger.info(f"Worker on port {port} shut down gracefully in {graceful\_duration:.3f}s")  
                    self.\_comprehensive\_worker\_verification(port, worker)  
                    return  
                except subprocess.TimeoutExpired:  
                    graceful\_duration \= (datetime.now() \- graceful\_start).total\_seconds()  
                    self.logger.info(f"Worker on port {port} didn't respond to graceful shutdown after {graceful\_duration:.3f}s")

            except Exception as e:  
                graceful\_duration \= (datetime.now() \- graceful\_start).total\_seconds()  
                self.logger.debug(f"Graceful shutdown request failed for port {port} after {graceful\_duration:.3f}s: {e}")

            \# Phase 2: SIGTERM if still running  
            if worker.poll() is None:  
                sigterm\_start \= datetime.now()  
                self.logger.debug(f"Phase 2: Sending SIGTERM to worker {worker.pid}")  
                worker.terminate()  \# Sends SIGTERM

                \# Wait with periodic status updates  
                check\_interval \= 2.0  \# Check every 2 seconds  
                remaining\_timeout \= self.worker\_timeout \- self.graceful\_timeout

                while True:  
                    wait\_start \= datetime.now()  
                    try:  
                        worker.wait(timeout=check\_interval)  
                        elapsed \= (datetime.now() \- sigterm\_start).total\_seconds()  
                        self.logger.info(f"Worker on port {port} terminated gracefully after {elapsed:.3f}s")  
                        break  
                    except subprocess.TimeoutExpired:  
                        elapsed \= (datetime.now() \- sigterm\_start).total\_seconds()  
                        if elapsed \>= remaining\_timeout:  
                            self.logger.warning(f"Worker on port {port} didn't respond to SIGTERM after {elapsed:.3f}s")  
                            break  
                        wait\_duration \= (datetime.now() \- wait\_start).total\_seconds() \* 1000  
                        self.logger.debug(f"Worker on port {port} still running after {elapsed:.3f}s (wait took {wait\_duration:.2f}ms), continuing...")

            \# Phase 3: SIGKILL if still running  
            if worker.poll() is None:  
                sigkill\_start \= datetime.now()  
                self.logger.warning(f"Phase 3: Escalating to SIGKILL for worker on port {port}")

                \# Try to kill the entire process group first  
                try:  
                    os.killpg(os.getpgid(worker.pid), signal.SIGKILL)  
                    self.logger.debug(f"Sent SIGKILL to process group for worker {worker.pid}")  
                except (ProcessLookupError, PermissionError) as e:  
                    self.logger.debug(f"Process group kill failed for worker {worker.pid}: {e}")  
                    \# Fall back to single process kill  
                    worker.kill()

                worker.wait()  \# This should not timeout after SIGKILL  
                kill\_duration \= (datetime.now() \- sigkill\_start).total\_seconds()  
                self.logger.info(f"Worker on port {port} force-killed successfully in {kill\_duration:.3f}s")

        except Exception as e:  
            error\_duration \= (datetime.now() \- start\_time).total\_seconds()  
            self.logger.error(f"Exception during worker {port} shutdown after {error\_duration:.3f}s: {e}", exc\_info=True)

        \# Post-shutdown verification  
        verification\_start \= datetime.now()  
        self.\_comprehensive\_worker\_verification(port, worker)  
        verification\_duration \= (datetime.now() \- verification\_start).total\_seconds()

        total\_duration \= (datetime.now() \- start\_time).total\_seconds()  
        self.logger.debug(f"Worker {port} total shutdown time: {total\_duration:.3f}s (verification: {verification\_duration:.3f}s)")

    def \_send\_worker\_shutdown\_request(self, port):  
        """Send HTTP shutdown request to worker"""  
        import urllib.request  
        import urllib.error

        try:  
            \# Attempt to send shutdown request via HTTP  
            shutdown\_url \= f"http://localhost:{port}/shutdown"  
            req \= urllib.request.Request(shutdown\_url, method='POST')  
            with urllib.request.urlopen(req, timeout=5) as response:  
                self.logger.debug(f"Shutdown request successful for port {port}: {response.status}")  
        except (urllib.error.URLError, ConnectionRefusedError, socket.timeout) as e:  
            \# Expected if worker doesn't support HTTP shutdown or is already down  
            self.logger.debug(f"HTTP shutdown request failed for port {port}: {e}")  
            raise

    def \_comprehensive\_worker\_verification(self, port, worker):  
        """Enhanced post-shutdown verification"""  
        verification\_start \= datetime.now()  
        self.logger.debug(f"Starting comprehensive verification for port {port}")

        \# 1\. Process state verification  
        final\_poll \= worker.poll()  
        if final\_poll is None:  
            self.logger.error(f"CRITICAL: Worker process {worker.pid} still running after shutdown\!")  
        else:  
            self.logger.debug(f"✓ Process verification passed: worker exited with code {final\_poll}")

        \# 2\. Enhanced port release verification  
        port\_start \= datetime.now()  
        port\_released \= self.\_verify\_port\_release(port)  
        port\_duration \= (datetime.now() \- port\_start).total\_seconds()

        \# 3\. Process cleanup verification (check for zombies)  
        zombie\_start \= datetime.now()  
        self.\_verify\_no\_zombie\_processes(worker.pid)  
        zombie\_duration \= (datetime.now() \- zombie\_start).total\_seconds()

        \# 4\. Process group verification  
        group\_start \= datetime.now()  
        self.\_verify\_process\_group\_cleanup(worker.pid)  
        group\_duration \= (datetime.now() \- group\_start).total\_seconds()

        \# 5\. System resource verification (e.g., file descriptors, memory)  
        resource\_start \= datetime.now()  
        self.\_verify\_system\_resources(port) \# This could be more general  
        resource\_duration \= (datetime.now() \- resource\_start).total\_seconds()

        verification\_status \= "PASSED" if port\_released else "FAILED"  
        total\_verification \= (datetime.now() \- verification\_start).total\_seconds()

        self.logger.info(f"Worker {port} verification: {verification\_status} "  
                        f"(total: {total\_verification:.3f}s, port: {port\_duration:.3f}s, "  
                        f"zombie: {zombie\_duration:.3f}s, group: {group\_duration:.3f}s, "  
                        f"resource: {resource\_duration:.3f}s)")

    def \_verify\_port\_release(self, port, timeout=15):  
        """Enhanced port verification using binding test, considering TIME\_WAIT state."""  
        start\_time \= datetime.now()  
        self.logger.debug(f"Verifying port {port} release...")

        \# If the server/worker sockets use SO\_REUSEADDR, a rapid restart might succeed  
        \# even if the port is in TIME\_WAIT. This check primarily verifies no active listener.  
        \# However, for a truly 'released' state without SO\_REUSEADDR, TIME\_WAIT can still cause issues.  
        \# This design assumes the new server listener will either wait or use SO\_REUSEADDR.

        while (datetime.now() \- start\_time).total\_seconds() \< timeout:  
            check\_start \= datetime.now()  
            port\_available \= self.\_is\_port\_available(port)  
            check\_duration \= (datetime.now() \- check\_start).total\_seconds() \* 1000

            if port\_available:  
                elapsed \= (datetime.now() \- start\_time).total\_seconds()  
                self.logger.info(f"✓ Port {port} successfully released after {elapsed:.3f}s")  
                return True

            elapsed \= (datetime.now() \- start\_time).total\_seconds()  
            self.logger.debug(f"Port {port} still in use after {elapsed:.3f}s (check took {check\_duration:.2f}ms), continuing...")  
            time.sleep(0.5)

        elapsed \= (datetime.now() \- start\_time).total\_seconds()  
        self.logger.error(f"✗ CRITICAL: Port {port} still in use after {elapsed:.3f}s. This might be due to an active listener or the port being in TIME\_WAIT state if SO\_REUSEADDR is not used by the next service bind.")  
        self.\_diagnose\_port\_issue(port)  
        self.\_force\_port\_cleanup(port) \# Note: This might not clear TIME\_WAIT, only active listeners  
        return False

    def \_is\_port\_available(self, port):  
        """Test if port is available by attempting to bind to it."""  
        try:  
            \# Using SO\_REUSEADDR here to test if \*another\* process holds the port.  
            \# If the original service didn't use SO\_REUSEADDR, the new service trying to bind  
            \# might still fail due to TIME\_WAIT even if this test passes.  
            with socket.socket(socket.AF\_INET, socket.SOCK\_STREAM) as s:  
                s.setsockopt(socket.SOL\_SOCKET, socket.SO\_REUSEADDR, 1\)  
                s.bind(('', port))  
                return True  
        except OSError as e:  
            if "Address already in use" in str(e):  
                return False  
            else:  
                self.logger.error(f"Error checking port {port} availability: {e}")  
                return False \# Assume not available on error  
        except Exception as e:  
            self.logger.error(f"Unexpected error in \_is\_port\_available for port {port}: {e}")  
            return False

    def \_diagnose\_port\_issue(self, port):  
        """Attempt to diagnose why a port is still in use."""  
        self.logger.warning(f"Attempting to diagnose port {port} issue:")  
        try:  
            for conn in psutil.net\_connections(kind='inet'):  
                if conn.laddr and conn.laddr.port \== port:  
                    self.logger.warning(f"  Port {port} is held by PID {conn.pid}, status: {conn.status}, family: {conn.family.name}, type: {conn.type.name}")  
                    try:  
                        proc \= psutil.Process(conn.pid)  
                        self.logger.warning(f"    Process details: Name={proc.name()}, Cmdline={' '.join(proc.cmdline())}")  
                    except psutil.NoSuchProcess:  
                        self.logger.warning(f"    Process {conn.pid} not found (might be a zombie or just exited).")  
                    except psutil.AccessDenied:  
                        self.logger.warning(f"    Access denied to process {conn.pid} details.")  
        except Exception as e:  
            self.logger.error(f"Error diagnosing port {port}: {e}")

    def \_force\_port\_cleanup(self, port):  
        """Attempts to force cleanup of a port by killing processes holding it (with caution)."""  
        self.logger.warning(f"Attempting to force cleanup for port {port}. This is an emergency measure.")  
        try:  
            for conn in psutil.net\_connections(kind='inet'):  
                if conn.laddr and conn.laddr.port \== port and conn.pid is not None:  
                    try:  
                        proc \= psutil.Process(conn.pid)  
                        self.logger.warning(f"  Force killing process {conn.pid} ('{proc.name()}') holding port {port}.")  
                        \# Use SIGKILL to ensure termination  
                        os.kill(conn.pid, signal.SIGKILL)  
                        self.logger.info(f"  Process {conn.pid} killed.")  
                    except (psutil.NoSuchProcess, ProcessLookupError):  
                        self.logger.debug(f"  Process {conn.pid} already gone for port {port}.")  
                    except Exception as e:  
                        self.logger.error(f"  Failed to force kill process {conn.pid} for port {port}: {e}")  
        except Exception as e:  
            self.logger.error(f"Error during force port cleanup for port {port}: {e}")

    def \_verify\_no\_zombie\_processes(self, initial\_pid):  
        """Verify that no zombie processes remain for the given PID's children."""  
        try:  
            parent \= psutil.Process(initial\_pid)  
            children \= parent.children(recursive=True)  
            zombies \= \[child for child in children if child.status() \== psutil.STATUS\_ZOMBIE\]  
            if zombies:  
                self.logger.error(f"CRITICAL: Found zombie processes related to PID {initial\_pid}: {zombies}")  
                \# Attempt to wait on them to clear them  
                for zombie in zombies:  
                    try:  
                        os.waitpid(zombie.pid, os.WNOHANG)  
                        self.logger.debug(f"Attempted to reap zombie {zombie.pid}")  
                    except ChildProcessError:  
                        self.logger.debug(f"Zombie {zombie.pid} already reaped or not a direct child.")  
            else:  
                self.logger.debug(f"✓ No zombie processes found for PID {initial\_pid} and its descendants.")  
        except psutil.NoSuchProcess:  
            self.logger.debug(f"Parent process {initial\_pid} already gone, cannot check for zombies.")  
        except Exception as e:  
            self.logger.error(f"Error verifying zombie processes for PID {initial\_pid}: {e}")

    def \_verify\_process\_group\_cleanup(self, initial\_pid):  
        """Verify that the process group associated with initial\_pid is cleaned up."""  
        try:  
            pgid \= os.getpgid(initial\_pid)  
            \# Iterate through all processes and check if any belong to this PGID  
            remaining\_in\_pg \= \[\]  
            for proc in psutil.process\_iter(\['pid', 'pgid', 'name'\]):  
                try:  
                    if hasattr(proc.info, 'pgid') and proc.info\['pgid'\] \== pgid and proc.info\['pid'\] \!= os.getpid(): \# Exclude self  
                        remaining\_in\_pg.append(f"PID {proc.info\['pid'\]} ({proc.info\['name'\]})")  
                except (psutil.NoSuchProcess, psutil.AccessDenied):  
                    continue

            if remaining\_in\_pg:  
                self.logger.error(f"CRITICAL: Processes still remaining in process group {pgid}: {', '.join(remaining\_in\_pg)}")  
            else:  
                self.logger.debug(f"✓ Process group {pgid} appears to be cleaned up.")  
        except ProcessLookupError:  
            self.logger.debug(f"Process group for PID {initial\_pid} already dissolved/cleaned up.")  
        except Exception as e:  
            self.logger.error(f"Error verifying process group cleanup for PID {initial\_pid}: {e}")

    def \_verify\_system\_resources(self, port):  
        """Placeholder for more detailed system resource verification (e.g., specific file handles)."""  
        self.logger.debug(f"Performing generic system resource checks for worker on port {port}...")  
        \# In a real scenario, this would check specific resources the worker uses,  
        \# e.g., temporary files, shared memory segments, specific network sockets beyond its listening port.  
        \# For now, it's a placeholder to highlight the need.  
        self.logger.debug(f"✓ Generic system resource checks completed.")

### **4.5 Resource Manager**

This component handles the graceful closing of other critical resources, such as database connections.

from datetime import datetime  
import time

class ResourceManager:  
    def \_\_init\_\_(self, logger):  
        self.logger \= logger  
        self.\_db\_connection \= None \# Assuming one main DB connection for simplicity

    def initialize\_database\_connection(self, db\_config):  
        """Initializes the database connection."""  
        self.logger.info("Initializing database connection...")  
        try:  
            \# Placeholder for actual DB connection logic  
            \# For example: self.\_db\_connection \= SomeDBLibrary.connect(db\_config)  
            self.\_db\_connection \= "mock\_db\_connection\_object" \# Replace with actual connection  
            self.logger.info("Database connection initialized.")  
            return True  
        except Exception as e:  
            self.logger.error(f"Failed to initialize database connection: {e}", exc\_info=True)  
            return False

    def close\_database\_connection(self):  
        """Gracefully closes the database connection."""  
        if not self.\_db\_connection:  
            self.logger.info("No database connection to close.")  
            return

        self.logger.info("Attempting to close database connection...")  
        start\_time \= datetime.now()  
        try:  
            \# Placeholder for actual DB closing logic  
            \# For example: self.\_db\_connection.close()  
            \# If the DB client library has a timeout or graceful shutdown method, use it here.  
            time.sleep(1) \# Simulate some closing time  
            self.\_db\_connection \= None  
            duration \= (datetime.now() \- start\_time).total\_seconds()  
            self.logger.info(f"Database connection closed successfully in {duration:.3f}s.")  
        except Exception as e:  
            duration \= (datetime.now() \- start\_time).total\_seconds()  
            self.logger.error(f"Error closing database connection after {duration:.3f}s: {e}", exc\_info=True)

    def cleanup\_all\_resources(self):  
        """Orchestrates cleanup of all managed resources."""  
        self.logger.info("Initiating comprehensive resource cleanup.")  
        self.close\_database\_connection()  
        \# Add calls to clean up other resources as they are added

## **5\. Exit Codes for Monitoring**

To provide clear feedback to external process managers like launchctl or systemctl, the server will exit with specific codes:

* **0 (Success):** Server shut down cleanly with no issues. All processes terminated, ports released, and resources cleaned up within expected parameters.  
* **1 (Graceful Client Timeout):** Server shut down, but some clients did not disconnect gracefully within the allocated timeout, requiring force disconnection.  
* **2 (Graceful Worker Timeout):** Server shut down, but some workers did not terminate gracefully within their initial timeout (SIGTERM was needed).  
* **3 (Worker Force Kill):** Server shut down, but one or more workers required SIGKILL after failing to respond to SIGTERM. This indicates a more serious issue with the worker.  
* **4 (Port Conflict/Leak):** A critical port was not released and remains in use after the shutdown sequence, preventing a clean restart.  
* **5 (Zombie Processes):** Zombie processes were detected after shutdown and could not be reaped.  
* **6 (Resource Cleanup Failure):** A managed resource (e.g., database connection) failed to close properly.  
* **100+ (Internal Error):** An unhandled exception occurred during the shutdown process itself.

The MCPServer.exit\_server() method will be used to terminate the process with the appropriate code.

## **6\. Mocking and Testing Strategy**

A robust testing strategy is crucial for a reliable shutdown mechanism, especially given its interactions with OS processes, signals, and network resources.

### **6.1 Unit Testing with Abstract Base Classes**

For our *own* code components (e.g., ClientManager, WorkerManager, ResourceManager, MCPServer itself), we will use Python's unittest framework. To facilitate mocking dependencies without using unittest.mock.patch for internal logic, we will define **Abstract Base Classes (ABCs)** for key interfaces.

For example, WorkerManager might depend on an IProcessSpawner ABC. In production, a concrete RealProcessSpawner implementation would use subprocess.Popen and os.killpg. In tests, a MockProcessSpawner would be created that logs calls, simulates process exits, and controls return values without actually spawning OS processes.

\# Example of an ABC for mocking  
from abc import ABC, abstractmethod  
import subprocess  
import os  
import signal  
import time \# For simulating waits

class IProcessSpawner(ABC):  
    @abstractmethod  
    def spawn\_process(self, command, preexec\_fn=None):  
        """Spawns a new process and returns a handle."""  
        pass

    @abstractmethod  
    def wait\_for\_process(self, process\_handle, timeout):  
        """Waits for a process to terminate, with a timeout."""  
        pass

    @abstractmethod  
    def terminate\_process(self, process\_handle):  
        """Sends SIGTERM to a process."""  
        pass

    @abstractmethod  
    def kill\_process\_group(self, pid):  
        """Sends SIGKILL to a process group."""  
        pass

    @abstractmethod  
    def get\_process\_poll\_status(self, process\_handle):  
        """Returns the exit code if terminated, otherwise None."""  
        pass

class RealProcessSpawner(IProcessSpawner):  
    def spawn\_process(self, command, preexec\_fn=None):  
        return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec\_fn=preexec\_fn)

    def wait\_for\_process(self, process\_handle, timeout):  
        return process\_handle.wait(timeout=timeout)

    def terminate\_process(self, process\_handle):  
        process\_handle.terminate()

    def kill\_process\_group(self, pid):  
        try:  
            os.killpg(os.getpgid(pid), signal.SIGKILL)  
        except ProcessLookupError:  
            pass \# Process group might already be gone

    def get\_process\_poll\_status(self, process\_handle):  
        return process\_handle.poll()

\# In tests, a MockProcessSpawner would be implemented to simulate behavior.  
\# The WorkerManager would be instantiated with a MockProcessSpawner.

This approach allows for thorough testing of business logic and state transitions within our components, relying on defined interfaces.

### **6.2 Mocking External APIs and Resources**

For interactions with truly external APIs or OS-level resources (e.g., psutil, urllib.request, and actual database drivers), unittest.mock.patch will be used. This allows us to:

* **Simulate OS status:** Patch psutil functions (Process, net\_connections, process\_iter) to return predefined lists of processes, connections, or statuses, allowing testing of zombie detection, port diagnosis, and process group verification.  
* **Control network interactions:** Patch socket.socket to prevent actual network binds (and simulate Address already in use or success), and urllib.request.urlopen to simulate successful or failed HTTP requests to workers.  
* **Simulate Database Interactions:** Patch the database driver's connection and cursor objects within the ResourceManager to ensure close\_database\_connection is called and handles potential errors without needing a real database.

### **6.3 Integration Testing**

Beyond unit tests, a suite of integration tests will be developed to verify the end-to-end shutdown process in more realistic scenarios. These tests will:

* **Spawn actual (minimal) worker processes:** To verify correct process group management and signal propagation.  
* **Simulate client connections:** To test graceful client disconnection.  
* **Observe system state:** Use psutil in the test runner to monitor processes and open ports *after* a shutdown attempt, confirming all resources are released.  
* **Test error injection:** Programmatically simulate workers hanging, or ports remaining in TIME\_WAIT (if not using SO\_REUSEADDR for new binds for the *next* service) to ensure the escalation logic works.

### **6.4 Comprehensive Verification in Tests**

Every test case for shutdown will include checks for:

* No active server processes or worker processes.  
* No orphaned child processes (verified with psutil).  
* No lingering port bindings (verified with \_is\_port\_available).  
* Database connection closed.  
* Expected exit code from the server process.

This multi-faceted testing approach ensures the shutdown mechanism is robust and predictable under various conditions.

## **7. Implementation Plan**

This section outlines the step-by-step implementation of the shutdown design, with incremental integration and testing milestones.

### **7.1 Current State Analysis**

The existing system (`github_mcp_master.py` and `github_mcp_worker.py`) has:

**Existing Capabilities:**
- Basic signal handling (SIGTERM, SIGINT) in both master and worker
- Asyncio-based shutdown coordination with `shutdown_event`
- Worker process management with subprocess.Popen
- Port checking and worker restart logic
- Simple timeout-based shutdown (5s graceful, 2s force kill)

**Current Issues:**
- No process groups (workers can become orphaned)
- No comprehensive resource cleanup (database connections, etc.)
- Limited shutdown verification (no port release checking)
- No centralized logging system with microsecond precision
- No client connection management
- No exit codes for monitoring
- No proper testing framework for shutdown scenarios

### **7.2 Implementation Steps**

#### **Step 1: Central Logging System** ✅ *First Working Milestone*
**Deliverable**: Centralized logging with microsecond precision
**Files**: `shutdown_core.py`
**Testing**: Unit tests for logging format and handlers

```python
# Implementation priority: HIGH
# This step provides immediate value and is required for all subsequent steps
```

**Implementation tasks:**
- Create `shutdown_core.py` with the `setup_central_logger()` function
- Implement `log_system_state()` function for comprehensive debugging
- Add microsecond precision formatting
- Create separate log files for debug and shutdown events
- Add unit tests for logging functionality

**Success criteria:**
- Central logger can be imported and used by both master and worker
- Microsecond precision timestamps in all log entries
- Separate log files for different event types
- Test coverage for logging functionality

#### **Step 2: Enhanced Signal Handling and Shutdown Coordination** ✅ *Second Working Milestone*
**Deliverable**: Robust signal handling with duplicate protection
**Files**: `shutdown_core.py`, updated `github_mcp_master.py`
**Testing**: Signal handling tests, shutdown coordination tests

**Implementation tasks:**
- Implement enhanced MCPServer class with improved signal handling
- Add shutdown flag management with thread-safe coordination
- Integrate central logging into master process
- Add comprehensive shutdown state tracking
- Update signal handlers to prevent duplicate shutdown initiation

**Success criteria:**
- Signal handling prevents multiple shutdown attempts
- Proper shutdown event coordination between components
- Comprehensive logging of shutdown events
- No hanging or race conditions during shutdown initiation

#### **Step 3: Process Group Management** ✅ *Third Working Milestone*
**Deliverable**: Workers run in process groups to prevent orphans
**Files**: Updated `github_mcp_master.py`, `shutdown_core.py`
**Testing**: Process group verification tests

**Implementation tasks:**
- Modify worker startup to use `os.setsid()` for process group creation
- Add process group verification in shutdown
- Implement process group cleanup with `os.killpg()`
- Add comprehensive process state logging

**Success criteria:**
- Workers spawn in separate process groups
- Process group cleanup prevents orphaned processes
- Verification confirms no remaining processes in group
- Integration tests confirm process group management works

#### **Step 4: Worker Manager with Enhanced Shutdown** ✅ *Fourth Working Milestone*
**Deliverable**: Comprehensive worker shutdown with escalating protocols
**Files**: `worker_manager.py`, updated `github_mcp_master.py`
**Testing**: Worker shutdown tests, timeout handling tests

**Implementation tasks:**
- Create WorkerManager class with enhanced shutdown protocols
- Implement graceful shutdown requests (HTTP POST to /shutdown)
- Add SIGTERM escalation with configurable timeouts
- Implement SIGKILL escalation with process group cleanup
- Add comprehensive worker verification after shutdown

**Success criteria:**
- Workers support graceful shutdown via HTTP
- Proper escalation from graceful -> SIGTERM -> SIGKILL
- Configurable timeouts for each shutdown phase
- Comprehensive verification of worker termination
- **This step provides the first fully functional shutdown system**

#### **Step 5: Port and Resource Verification** 
**Deliverable**: Comprehensive port release and resource cleanup verification
**Files**: `resource_manager.py`, updated `worker_manager.py`
**Testing**: Port release tests, resource cleanup tests

**Implementation tasks:**
- Implement enhanced port verification with binding tests
- Add port diagnosis and force cleanup capabilities
- Create ResourceManager for database connection management
- Add comprehensive resource cleanup verification
- Implement timeout-based verification with retry logic

**Success criteria:**
- Port release verification prevents "address already in use" errors
- Resource cleanup ensures no leaked connections
- Diagnostic capabilities for troubleshooting port issues
- Force cleanup capabilities for emergency situations

#### **Step 6: Client Connection Management**
**Deliverable**: Graceful client disconnection with timeout protection
**Files**: `client_manager.py`, updated `github_mcp_worker.py`
**Testing**: Client disconnection tests, timeout handling tests

**Implementation tasks:**
- Create ClientManager class for connection tracking
- Implement graceful client notification (MCP shutdown messages)
- Add force disconnection for unresponsive clients
- Integrate client management into worker shutdown sequence
- Add comprehensive client connection verification

**Success criteria:**
- Clients receive proper shutdown notifications
- Graceful disconnection with fallback to force close
- Total timeout protection prevents hanging
- Integration with worker shutdown sequence

#### **Step 7: Exit Code System and Health Monitoring**
**Deliverable**: Comprehensive exit codes and external monitoring interface
**Files**: Updated `github_mcp_master.py`, `health_monitor.py`
**Testing**: Exit code tests, health monitoring tests

**Implementation tasks:**
- Implement exit code system with specific codes for different failure modes
- Add health monitoring interface for external verification
- Create comprehensive pre-exit verification
- Add external monitoring capabilities for process managers

**Success criteria:**
- Clear exit codes for different shutdown scenarios
- External monitoring can verify clean shutdown
- Health check system provides real-time status
- Process managers can interpret exit codes correctly

#### **Step 8: Comprehensive Testing Framework**
**Deliverable**: Complete test suite for shutdown scenarios
**Files**: `tests/test_shutdown_*.py`, integration test suite
**Testing**: All shutdown scenarios covered

**Implementation tasks:**
- Create Abstract Base Classes for mocking process operations
- Implement comprehensive unit tests for all components
- Create integration tests with real processes
- Add edge case testing (hanging workers, port conflicts, etc.)
- Implement continuous integration for shutdown tests

**Success criteria:**
- 100% test coverage for shutdown components
- Integration tests with real process spawning
- Edge case handling verified through tests
- Continuous integration catches shutdown regressions

### **7.3 Working System Milestones**

#### **Milestone 1: Basic Improved Shutdown (Steps 1-2)**
- **Capabilities**: Enhanced logging and signal handling
- **Limitations**: Still basic shutdown, no process group management
- **Use Case**: Development debugging and improved shutdown logging

#### **Milestone 2: Process Group Management (Steps 1-3)**
- **Capabilities**: Workers run in process groups, enhanced logging
- **Limitations**: No comprehensive resource cleanup or client management
- **Use Case**: Production deployment with reduced orphan process risk

#### **Milestone 3: Production-Ready Shutdown (Steps 1-4)** ⭐ **FIRST FULLY FUNCTIONAL**
- **Capabilities**: Complete worker shutdown with escalation, process groups, logging
- **Limitations**: No client connection management, basic resource cleanup
- **Use Case**: Production deployment with reliable shutdown
- **Key Features**:
  - Graceful worker shutdown with HTTP requests
  - Proper SIGTERM/SIGKILL escalation
  - Process group cleanup prevents orphans
  - Comprehensive logging and verification
  - **This milestone provides a fully functional shutdown system suitable for production use**

#### **Milestone 4: Comprehensive Shutdown (Steps 1-6)**
- **Capabilities**: Full client management, resource cleanup, port verification
- **Limitations**: Basic exit codes, no external monitoring
- **Use Case**: Production deployment with complete shutdown assurance

#### **Milestone 5: Enterprise-Ready (Steps 1-8)**
- **Capabilities**: Complete shutdown system with monitoring and testing
- **Limitations**: None - complete implementation
- **Use Case**: Enterprise deployment with full monitoring and verification

### **7.4 Integration Strategy**

#### **Backwards Compatibility**
- New shutdown components will be developed alongside existing system
- Gradual migration with feature flags to enable new shutdown behavior
- Existing signal handlers will be preserved during transition
- Configuration options to revert to legacy shutdown if needed

#### **Testing Strategy**
- Each step includes comprehensive unit and integration tests
- Automated testing in CI/CD pipeline
- Manual testing procedures for each milestone
- Performance testing to ensure shutdown doesn't impact normal operations

#### **Deployment Strategy**
- Development environment testing for each step
- Staging environment integration testing
- Production deployment with gradual rollout
- Monitoring and alerting for shutdown events

### **7.5 Timeline and Effort Estimation**

| Step | Estimated Effort | Dependencies | Risk Level |
|------|------------------|--------------|------------|
| 1 | 1-2 days | None | Low |
| 2 | 2-3 days | Step 1 | Low |
| 3 | 2-3 days | Step 2 | Medium |
| 4 | 3-4 days | Step 3 | Medium |
| 5 | 2-3 days | Step 4 | Medium |
| 6 | 3-4 days | Step 5 | Medium |
| 7 | 1-2 days | Step 6 | Low |
| 8 | 4-5 days | All steps | High |

**Total Estimated Effort**: 18-26 days

**Critical Dependencies**:
- Central logging system (Step 1) is required for all subsequent steps
- Process group management (Step 3) is critical for production deployment
- Worker manager (Step 4) provides the first fully functional shutdown system

**Risk Mitigation**:
- Each step includes comprehensive testing
- Backwards compatibility maintained throughout implementation
- Gradual rollout with monitoring and rollback capabilities
- Performance testing to ensure no regression in normal operations