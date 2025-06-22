#!/usr/bin/env python3

"""
GitHub MCP Master Process - Multi-Port Architecture
Master process that spawns and monitors worker processes for each repository.

This master process:
- Reads repository configuration with port assignments
- Spawns worker processes for each repository on dedicated ports
- Monitors worker health and restarts failed processes
- Handles graceful shutdown and cleanup
"""

import asyncio
import os
import sys
import json
import signal
import logging
import subprocess
import time
import socket
import traceback
from typing import Dict, Optional
from dataclasses import dataclass
from pathlib import Path

# Import shutdown coordination components
from shutdown_core import ShutdownCoordinator, setup_signal_handlers, ExitCodes
from system_utils import log_system_state

# Configure logging with enhanced microsecond precision
from datetime import datetime

log_dir = Path.home() / ".local" / "share" / "github-agent" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

class MicrosecondFormatter(logging.Formatter):
    """Custom formatter that provides microsecond precision timestamps"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Keep 3 decimal places (milliseconds)

def setup_enhanced_logging(logger, log_file_path=None):
    """Enhance an existing logger with microsecond precision formatting
    
    This is called from the master process to enhance the main logger
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
        log_file_path = log_dir / 'master.log'
    
    file_handler = logging.FileHandler(log_file_path, mode='a')
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

# Create and setup the master logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger = setup_enhanced_logging(logger)

@dataclass
class WorkerProcess:
    """Information about a worker process"""
    repo_name: str
    port: int
    path: str
    description: str
    process: Optional[subprocess.Popen] = None
    start_time: Optional[float] = None
    restart_count: int = 0
    max_restarts: int = 5

def is_port_free(port: int) -> bool:
    """Check if a port is available for binding"""
    logger.debug(f"is_port_free: Checking port {port}")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            logger.debug(f"is_port_free: Created socket for port {port}")
            s.bind(('0.0.0.0', port))
            logger.debug(f"is_port_free: Successfully bound to port {port} - PORT IS FREE")
            return True
    except OSError as e:
        logger.debug(f"is_port_free: Failed to bind to port {port} - PORT IS OCCUPIED: {e}")
        return False

async def wait_for_port_free(port: int, timeout: int = 30) -> bool:
    """Wait for a port to become available, with timeout"""
    logger.debug(f"wait_for_port_free: Starting to wait for port {port} with timeout {timeout}s")
    start_time = time.time()
    
    check_count = 0
    while time.time() - start_time < timeout:
        check_count += 1
        elapsed = time.time() - start_time
        logger.debug(f"wait_for_port_free: Check #{check_count} for port {port} after {elapsed:.1f}s")
        
        if is_port_free(port):
            logger.debug(f"wait_for_port_free: Port {port} is now available after {elapsed:.1f}s and {check_count} checks")
            return True
        
        logger.debug(f"wait_for_port_free: Port {port} still not free, sleeping 0.5s...")
        await asyncio.sleep(0.5)  # Check every 500ms
        logger.debug(f"wait_for_port_free: Woke up from sleep for port {port}")
    
    final_elapsed = time.time() - start_time
    logger.error(f"wait_for_port_free: Timeout waiting for port {port} after {final_elapsed:.1f}s and {check_count} checks")
    return False

class GitHubMCPMaster:
    """Master process for managing multiple MCP worker processes"""
    
    def __init__(self, config_path: str = "repositories.json"):
        self.config_path = config_path
        self.workers: Dict[str, WorkerProcess] = {}
        self.running = False
        
        # Initialize shutdown coordination with our logger
        self.shutdown_coordinator = ShutdownCoordinator(logger)
        
        # Use system-appropriate log location
        self.log_dir = Path.home() / ".local" / "share" / "github-agent" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
    def load_configuration(self) -> bool:
        """Load repository configuration from JSON file"""
        try:
            if not os.path.exists(self.config_path):
                logger.error(f"Configuration file {self.config_path} not found")
                return False
                
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            repositories = config.get('repositories', {})
            if not repositories:
                logger.error("No repositories found in configuration")
                return False
            
            # Auto-assign ports if not specified
            next_port = 8081
            for repo_name, repo_config in repositories.items():
                if 'port' not in repo_config:
                    repo_config['port'] = next_port
                    next_port += 1
                
                # Validate required fields
                if 'path' not in repo_config:
                    logger.error(f"Repository {repo_name} missing required 'path' field")
                    return False
                
                if not os.path.exists(repo_config['path']):
                    logger.warning(f"Repository path {repo_config['path']} does not exist")
                
                # Create worker process info
                worker = WorkerProcess(
                    repo_name=repo_name,
                    port=repo_config['port'],
                    path=repo_config['path'],
                    description=repo_config.get('description', repo_name)
                )
                self.workers[repo_name] = worker
                
            logger.info(f"Loaded configuration for {len(self.workers)} repositories")
            
            # Check for port conflicts
            ports_used = [w.port for w in self.workers.values()]
            if len(ports_used) != len(set(ports_used)):
                logger.error("Port conflicts detected in configuration")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return False
    
    def save_configuration(self):
        """Save current configuration back to file (with auto-assigned ports)"""
        try:
            config = {"repositories": {}}
            for repo_name, worker in self.workers.items():
                config["repositories"][repo_name] = {
                    "path": worker.path,
                    "port": worker.port,
                    "description": worker.description
                }
            
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            logger.info(f"Updated configuration saved to {self.config_path}")
            
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
    
    def start_worker(self, worker: WorkerProcess) -> bool:
        """Start a worker process for a repository"""
        try:
            if worker.process and worker.process.poll() is None:
                logger.warning(f"Worker for {worker.repo_name} is already running")
                return True
            
            # Command to start worker process
            # Use the virtual environment Python explicitly
            venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', 'bin', 'python')
            python_executable = venv_python if os.path.exists(venv_python) else sys.executable
            
            cmd = [
                python_executable, 
                "github_mcp_worker.py",
                "--repo-name", worker.repo_name,
                "--repo-path", worker.path,
                "--port", str(worker.port),
                "--description", worker.description
            ]
            
            # Set up environment
            env = os.environ.copy()
            env['PYTHONPATH'] = os.getcwd()
            
            # Check if port is available before starting
            if not is_port_free(worker.port):
                logger.error(f"Port {worker.port} is not available for {worker.repo_name}")
                return False
            
            # Start the process
            worker.process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd()
            )
            
            worker.start_time = time.time()
            logger.info(f"Started worker for {worker.repo_name} on port {worker.port} (PID: {worker.process.pid})")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start worker for {worker.repo_name}: {e}")
            return False
    
    async def stop_worker(self, worker: WorkerProcess, timeout: int = 5) -> bool:
        """Stop a worker process with timeout (simplified for individual worker shutdown)"""
        try:
            if not worker.process or worker.process.poll() is not None:
                logger.info(f"Worker for {worker.repo_name} is already stopped")
                worker.process = None
                return True
            
            pid = worker.process.pid
            logger.info(f"Stopping worker {worker.repo_name} (PID: {pid})")
            
            # Send SIGTERM for graceful shutdown
            worker.process.terminate()
            
            # Wait for graceful shutdown with timeout
            try:
                await asyncio.wait_for(
                    asyncio.create_task(self._wait_for_process_exit(worker.process)),
                    timeout=timeout
                )
                logger.info(f"Worker for {worker.repo_name} stopped gracefully")
                worker.process = None
                return True
            except asyncio.TimeoutError:
                # Force kill if doesn't respond
                logger.warning(f"Worker for {worker.repo_name} didn't respond to SIGTERM within {timeout}s, force killing")
                try:
                    worker.process.kill()
                    await asyncio.wait_for(
                        asyncio.create_task(self._wait_for_process_exit(worker.process)),
                        timeout=2
                    )
                    logger.info(f"Worker for {worker.repo_name} force killed successfully")
                    worker.process = None
                    return True
                except asyncio.TimeoutError:
                    logger.error(f"Worker for {worker.repo_name} couldn't be killed even with SIGKILL")
                    return False
            
        except Exception as e:
            logger.error(f"Exception stopping worker {worker.repo_name}: {e}")
            # Emergency cleanup
            if worker.process:
                try:
                    worker.process.kill()
                    worker.process = None
                except:
                    pass
            return False
    
    def is_worker_healthy(self, worker: WorkerProcess) -> bool:
        """Check if a worker process is healthy"""
        if not worker.process:
            logger.debug(f"Worker for {worker.repo_name} has no process")
            return False
        
        # Check if process is still alive
        poll_result = worker.process.poll()
        if poll_result is not None:
            logger.warning(f"Worker for {worker.repo_name} is not running (exit code: {poll_result})")
            # Log any output from the failed process
            try:
                stdout, stderr = worker.process.communicate(timeout=1)
                if stdout:
                    logger.error(f"Worker {worker.repo_name} STDOUT: {stdout.decode()}")
                if stderr:
                    logger.error(f"Worker {worker.repo_name} STDERR: {stderr.decode()}")
            except Exception as e:
                logger.debug(f"Failed to read worker output: {e}")
            return False
        
        # TODO: Add health check HTTP endpoint call
        # For now, just check if process is running
        return True
    
    async def monitor_workers(self):
        """Monitor worker processes and restart if needed"""
        logger.debug("Worker monitoring task started")
        try:
            while self.running:
                try:
                    for repo_name, worker in self.workers.items():
                        if not self.is_worker_healthy(worker):
                            if worker.restart_count < worker.max_restarts:
                                logger.warning(f"Worker for {repo_name} is unhealthy, restarting...")
                                await self.stop_worker(worker)
                                
                                # Wait for port to be properly released before restarting
                                logger.debug(f"Waiting for port {worker.port} to be released...")
                                port_available = await wait_for_port_free(worker.port, timeout=15)
                                if not port_available:
                                    logger.error(f"Port {worker.port} still not available after 15s, skipping restart for {repo_name}")
                                    continue
                                
                                if self.start_worker(worker):
                                    worker.restart_count += 1
                                    logger.info(f"Restarted worker for {repo_name} (restart count: {worker.restart_count})")
                                else:
                                    logger.error(f"Failed to restart worker for {repo_name}")
                            else:
                                logger.error(f"Worker for {repo_name} exceeded max restarts ({worker.max_restarts})")
                    
                    # Sleep in smaller chunks to allow for faster cancellation
                    for _ in range(30):  # 30 seconds total, 1 second chunks
                        if not self.running:
                            break
                        await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error in worker monitoring: {e}")
                    await asyncio.sleep(5)
        finally:
            logger.debug("Worker monitoring task ending")
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals using the shutdown coordinator"""
        # Use the shutdown coordinator for proper signal handling
        signal_name = signal.Signals(signum).name
        self.running = False
        
        # Use call_soon_threadsafe to safely signal from signal handler context
        try:
            self.loop.call_soon_threadsafe(
                self.shutdown_coordinator.shutdown, 
                f"signal_{signal_name}"
            )
        except Exception:
            # If we can't use the loop, fall back to direct call
            self.shutdown_coordinator.shutdown(f"signal_{signal_name}")
    
    async def start(self):
        """Start the master process"""
        logger.info("Starting GitHub MCP Master Process")
        
        # Store loop reference for signal handler
        self.loop = asyncio.get_running_loop()
        
        # Load configuration
        if not self.load_configuration():
            logger.error("Failed to load configuration, exiting")
            return False
        
        # Save configuration with auto-assigned ports
        self.save_configuration()
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # Start all workers
        self.running = True
        failed_workers = []
        
        for repo_name, worker in self.workers.items():
            if not self.start_worker(worker):
                failed_workers.append(repo_name)
        
        if failed_workers:
            logger.error(f"Failed to start workers for: {failed_workers}")
        
        # Start monitoring task
        monitor_task = asyncio.create_task(self.monitor_workers())
        
        # Log startup summary
        running_workers = [name for name, worker in self.workers.items() if self.is_worker_healthy(worker)]
        logger.info(f"Master process started with {len(running_workers)} workers:")
        for repo_name, worker in self.workers.items():
            if repo_name in running_workers:
                logger.info(f"  - {repo_name}: http://localhost:{worker.port}/mcp/")
        
        # Wait for shutdown signal using shutdown coordinator
        logger.debug("About to wait for shutdown signal...")
        logger.debug(f"shutdown coordinator state: {self.shutdown_coordinator.is_shutting_down()}")
        
        # Log system state before waiting
        log_system_state(logger, "MASTER_WAITING_FOR_SHUTDOWN")
        
        try:
            logger.debug("Waiting for shutdown coordinator...")
            # Convert the synchronous wait to async
            while not self.shutdown_coordinator.is_shutting_down():
                await asyncio.sleep(0.1)
            logger.debug("Shutdown coordinator signaled shutdown")
        except Exception as e:
            logger.error(f"Exception waiting for shutdown: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
        
        logger.info("Shutdown signal received, beginning graceful shutdown...")
        
        # **CRITICAL FIX**: Stop health monitoring FIRST to prevent worker restarts during shutdown
        logger.info("Step 1: Stopping health monitoring to prevent worker restarts...")
        try:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                logger.info("Health monitoring stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping health monitoring: {e}")
        except Exception as e:
            logger.error(f"Critical error stopping health monitoring: {e}")
        
        # **Step 2**: Stop all workers with proper timeouts and connection draining
        logger.info("Step 2: Stopping all worker processes with connection draining...")
        return await self._shutdown_workers()
    
    async def _shutdown_workers(self) -> bool:
        """Shutdown all workers with proper connection draining and timeouts"""
        try:
            async def stop_worker_gracefully(repo_name: str, worker: WorkerProcess) -> bool:
                """Stop a single worker with proper connection draining"""
                logger.info(f"stop_worker_gracefully called for {repo_name}")
                try:
                    if not worker.process or worker.process.poll() is not None:
                        logger.info(f"Worker {repo_name} already stopped")
                        return True
                    
                    pid = worker.process.pid
                    logger.info(f"Stopping worker {repo_name} (PID: {pid}) on port {worker.port}")
                    
                    # Send SIGTERM for graceful shutdown
                    logger.info(f"Sending SIGTERM to worker {repo_name} (PID: {pid})")
                    worker.process.terminate()
                    
                    # Wait for worker to shutdown gracefully with shorter timeout
                    logger.info(f"Waiting up to 5s for worker {repo_name} to stop gracefully...")
                    try:
                        await asyncio.wait_for(
                            self._wait_for_process_exit(worker.process),
                            timeout=5  # Reduced to 5 seconds for faster deployment
                        )
                        logger.info(f"Worker {repo_name} stopped gracefully")
                        worker.process = None
                        return True
                    except asyncio.TimeoutError:
                        logger.warning(f"Worker {repo_name} didn't stop gracefully within 5s, force killing (PID: {pid})")
                        
                        # Force kill
                        try:
                            logger.info(f"Sending SIGKILL to worker {repo_name} (PID: {pid})")
                            worker.process.kill()
                            logger.info(f"Waiting up to 2s for force kill to complete for worker {repo_name}")
                            await asyncio.wait_for(
                                self._wait_for_process_exit(worker.process),
                                timeout=2
                            )
                            logger.info(f"Worker {repo_name} force killed successfully")
                            worker.process = None
                            return True
                        except asyncio.TimeoutError:
                            logger.error(f"Worker {repo_name} couldn't be killed even with SIGKILL after 2s")
                            # Set to None anyway to avoid hanging
                            worker.process = None
                            return False
                        except Exception as e:
                            logger.error(f"Error force killing worker {repo_name}: {e}")
                            worker.process = None
                            return False
                            
                except Exception as e:
                    logger.error(f"Exception stopping worker {repo_name}: {e}")
                    logger.error(f"Exception traceback: {traceback.format_exc()}")
                    # Emergency cleanup
                    if worker.process:
                        try:
                            logger.warning(f"Emergency cleanup: killing worker {repo_name}")
                            worker.process.kill()
                            worker.process = None
                        except Exception as cleanup_error:
                            logger.error(f"Emergency cleanup failed for {repo_name}: {cleanup_error}")
                            worker.process = None
                    return False
            
            # Stop all workers concurrently for faster shutdown
            if not self.workers:
                logger.info("No workers to stop")
                return True
            
            logger.info(f"Stopping {len(self.workers)} workers concurrently...")
            stop_tasks = [
                stop_worker_gracefully(repo_name, worker)
                for repo_name, worker in self.workers.items()
            ]
            
            # Execute all stop operations with reduced overall timeout for faster deployment
            logger.info("Starting concurrent worker stop tasks...")
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*stop_tasks, return_exceptions=True),
                    timeout=15  # Reduced to 15 seconds total for faster deployment
                )
                
                # Check results
                successful_stops = sum(1 for r in results if r is True)
                failed_stops = len(self.workers) - successful_stops
                logger.info(f"Worker stop results: {successful_stops} successful, {failed_stops} failed")
                
                if successful_stops == len(self.workers):
                    logger.info("All workers stopped successfully")
                else:
                    logger.warning(f"{failed_stops} workers failed to stop properly, but continuing shutdown")
                
            except asyncio.TimeoutError:
                logger.error("Overall worker shutdown timeout after 15s - forcing emergency cleanup")
                # Emergency cleanup for any remaining processes
                for repo_name, worker in self.workers.items():
                    if worker.process:
                        try:
                            logger.warning(f"Emergency kill of worker {repo_name} (PID: {worker.process.pid})")
                            worker.process.kill()
                            worker.process = None
                        except Exception as e:
                            logger.error(f"Emergency kill failed for {repo_name}: {e}")
                            worker.process = None
            
            logger.info("Worker shutdown process completed")
            logger.info("GitHub MCP Master Process shutdown complete")
            return True
            
        except Exception as e:
            logger.error(f"Critical error during worker shutdown: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Emergency cleanup of all workers
            for repo_name, worker in self.workers.items():
                if worker.process:
                    try:
                        logger.warning(f"Critical error cleanup: killing worker {repo_name}")
                        worker.process.kill()
                        worker.process = None
                    except:
                        worker.process = None
            return False
    
    async def _wait_for_process_exit(self, process: subprocess.Popen):
        """Async wrapper for process.wait() with polling"""
        while True:
            if process.poll() is not None:
                return process.returncode
            await asyncio.sleep(0.1)  # Poll every 100ms
    
    def status(self) -> Dict:
        """Get status of all workers"""
        status = {
            "master": {
                "running": self.running,
                "workers_count": len(self.workers),
                "config_path": self.config_path
            },
            "workers": {}
        }
        
        for repo_name, worker in self.workers.items():
            is_healthy = self.is_worker_healthy(worker)
            status["workers"][repo_name] = {
                "port": worker.port,
                "path": worker.path,
                "description": worker.description,
                "running": is_healthy,
                "pid": worker.process.pid if worker.process else None,
                "start_time": worker.start_time,
                "restart_count": worker.restart_count,
                "endpoint": f"http://localhost:{worker.port}/mcp/"
            }
        
        return status

async def main():
    """Main entry point"""
    master = GitHubMCPMaster()
    
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "status":
            # Show status and exit
            if master.load_configuration():
                status = master.status()
                print(json.dumps(status, indent=2))
            else:
                print("Failed to load configuration")
            return
        elif sys.argv[1] == "stop":
            # Stop all workers (TODO: implement proper shutdown)
            logger.info("Stop command not implemented yet")
            return
    
    # Start master process
    try:
        await master.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Master process failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
