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

# Configure logging (use system-appropriate log location)
log_dir = Path.home() / ".local" / "share" / "github-agent" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / 'master.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

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
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('0.0.0.0', port))
            return True
    except OSError:
        return False

async def wait_for_port_free(port: int, timeout: int = 30) -> bool:
    """Wait for a port to become available, with timeout"""
    logger.debug(f"Waiting for port {port} to become available...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if is_port_free(port):
            logger.debug(f"Port {port} is now available")
            return True
        await asyncio.sleep(0.5)  # Check every 500ms
    
    logger.error(f"Timeout waiting for port {port} to become available after {timeout}s")
    return False

class GitHubMCPMaster:
    """Master process for managing multiple MCP worker processes"""
    
    def __init__(self, config_path: str = "repositories.json"):
        self.config_path = config_path
        self.workers: Dict[str, WorkerProcess] = {}
        self.running = False
        self.shutdown_event = asyncio.Event()
        
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
    
    def stop_worker(self, worker: WorkerProcess, timeout: int = 5) -> bool:
        """Stop a worker process with timeout"""
        logger.debug(f"stop_worker called for {worker.repo_name} with timeout {timeout}")
        try:
            logger.debug(f"Checking if worker {worker.repo_name} is running...")
            logger.debug(f"worker.process: {worker.process}")
            
            if not worker.process:
                logger.info(f"Worker for {worker.repo_name} has no process object")
                return True
                
            poll_result = worker.process.poll()
            logger.debug(f"worker.process.poll() returned: {poll_result}")
            
            if poll_result is not None:
                logger.info(f"Worker for {worker.repo_name} is not running (exit code: {poll_result})")
                worker.process = None
                return True
            
            pid = worker.process.pid
            logger.debug(f"About to stop worker for {worker.repo_name} (PID: {pid})")
            
            # Send SIGTERM for graceful shutdown
            logger.debug(f"Sending SIGTERM to worker {worker.repo_name} (PID: {pid})")
            worker.process.terminate()
            logger.debug(f"SIGTERM sent to worker {worker.repo_name}")
            
            # Wait for graceful shutdown with timeout
            logger.debug(f"Waiting up to {timeout}s for worker {worker.repo_name} to stop gracefully...")
            try:
                worker.process.wait(timeout=timeout)
                logger.info(f"Worker for {worker.repo_name} stopped gracefully")
                logger.debug(f"Final poll after graceful stop: {worker.process.poll()}")
            except subprocess.TimeoutExpired:
                # Force kill if doesn't respond
                logger.warning(f"Worker for {worker.repo_name} didn't respond to SIGTERM within {timeout}s, force killing")
                logger.debug(f"Sending SIGKILL to worker {worker.repo_name} (PID: {pid})")
                worker.process.kill()
                logger.debug(f"SIGKILL sent to worker {worker.repo_name}")
                try:
                    logger.debug(f"Waiting up to 2s for force kill to complete...")
                    worker.process.wait(timeout=2)
                    logger.debug(f"Force kill completed for worker {worker.repo_name}")
                except subprocess.TimeoutExpired:
                    logger.error(f"Worker for {worker.repo_name} couldn't be killed even with SIGKILL")
                    return False
            
            logger.debug(f"Setting worker.process = None for {worker.repo_name}")
            worker.process = None
            logger.debug(f"Worker for {worker.repo_name} stopped successfully")
            return True
            
        except Exception as e:
            logger.error(f"Exception in stop_worker for {worker.repo_name}: {e}")
            logger.error(f"stop_worker exception traceback: {traceback.format_exc()}")
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
                                self.stop_worker(worker)
                                
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
        """Handle shutdown signals - minimal implementation to avoid signal handler issues"""
        # Avoid complex operations in signal handler - just set flags
        self.running = False
        # Use call_soon_threadsafe to safely signal from signal handler context
        try:
            self.loop.call_soon_threadsafe(self.shutdown_event.set)
            # Only log after setting up the shutdown to avoid hanging in signal handler
            self.loop.call_soon_threadsafe(logger.info, f"Received signal {signum}, initiating graceful shutdown...")
        except Exception:
            # If we can't use the loop, fall back to direct call (might be unsafe but better than hanging)
            self.shutdown_event.set()
    
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
        
        # Wait for shutdown signal
        logger.debug("About to wait for shutdown signal...")
        logger.debug(f"shutdown_event state before wait: {self.shutdown_event.is_set()}")
        
        try:
            logger.debug("Calling await self.shutdown_event.wait()...")
            await self.shutdown_event.wait()
            logger.debug("shutdown_event.wait() returned successfully")
        except Exception as e:
            logger.error(f"Exception in shutdown_event.wait(): {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
        
        logger.info("Shutdown signal received, beginning shutdown process...")
        logger.debug(f"self.running is now: {self.running}")
        logger.debug(f"shutdown_event.is_set() is now: {self.shutdown_event.is_set()}")
        
        try:
            # Cancel monitoring
            logger.info("About to cancel worker monitoring task...")
            logger.debug(f"monitor_task object: {monitor_task}")
            logger.debug(f"monitor_task.cancelled(): {monitor_task.cancelled() if hasattr(monitor_task, 'cancelled') else 'N/A'}")
            logger.debug(f"monitor_task.done(): {monitor_task.done() if hasattr(monitor_task, 'done') else 'N/A'}")
            
            logger.debug("Calling monitor_task.cancel()...")
            monitor_task.cancel()
            logger.debug("monitor_task.cancel() completed")
            logger.debug(f"monitor_task.cancelled() after cancel(): {monitor_task.cancelled()}")
            
            logger.debug("About to await monitor_task...")
            try:
                await monitor_task
                logger.debug("await monitor_task completed normally")
            except asyncio.CancelledError:
                logger.debug("Monitor task cancelled successfully (CancelledError caught)")
            except Exception as e:
                logger.error(f"Unexpected error awaiting monitor task: {e}")
                logger.error(f"Monitor task exception traceback: {traceback.format_exc()}")
            
            logger.info("Monitor task cancellation complete, proceeding to stop workers")
            
            # Stop all workers in parallel to avoid race conditions
            logger.info("About to stop all workers in parallel...")
            logger.debug(f"Number of workers to stop: {len(self.workers)}")
            
            async def stop_worker_with_timeout(repo_name, worker, timeout=5):
                """Stop a worker with overall timeout"""
                try:
                    logger.info(f"About to stop worker for {repo_name}...")
                    logger.debug(f"Worker {repo_name} - PID: {worker.process.pid if worker.process else 'None'}")
                    logger.debug(f"Worker {repo_name} - Port: {worker.port}")
                    
                    # Wrap the stop_worker call in asyncio.wait_for for timeout
                    def sync_stop_worker():
                        return self.stop_worker(worker, timeout=3)
                    
                    # Run in thread pool to avoid blocking
                    success = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, sync_stop_worker),
                        timeout=timeout
                    )
                    
                    logger.debug(f"stop_worker returned: {success} for {repo_name}")
                    if success:
                        logger.info(f"Successfully stopped worker for {repo_name}")
                    else:
                        logger.error(f"Failed to stop worker for {repo_name}")
                    return success
                    
                except asyncio.TimeoutError:
                    logger.error(f"Timeout stopping worker for {repo_name} after {timeout}s")
                    # Force kill if timeout
                    if worker.process:
                        try:
                            logger.warning(f"Force killing hung worker {repo_name} (PID: {worker.process.pid})")
                            worker.process.kill()
                            worker.process = None
                        except Exception as e:
                            logger.error(f"Failed to force kill worker {repo_name}: {e}")
                    return False
                except Exception as e:
                    logger.error(f"Exception stopping worker for {repo_name}: {e}")
                    logger.error(f"Worker stop exception traceback: {traceback.format_exc()}")
                    return False
            
            # Stop all workers concurrently
            stop_tasks = [
                stop_worker_with_timeout(repo_name, worker)
                for repo_name, worker in self.workers.items()
            ]
            
            if stop_tasks:
                logger.debug(f"Starting {len(stop_tasks)} concurrent stop tasks...")
                results = await asyncio.gather(*stop_tasks, return_exceptions=True)
                logger.debug(f"All stop tasks completed with results: {results}")
            else:
                logger.debug("No workers to stop")
            
            logger.info("All workers stop attempts completed")
            logger.info("GitHub MCP Master Process shutdown complete")
            return True
            
        except Exception as e:
            logger.error(f"Critical error during shutdown: {e}")
            logger.error(f"Critical error traceback: {traceback.format_exc()}")
            return False
    
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
