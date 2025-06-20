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
from typing import Dict, List, Optional
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
            cmd = [
                sys.executable, 
                "github_mcp_worker.py",
                "--repo-name", worker.repo_name,
                "--repo-path", worker.path,
                "--port", str(worker.port),
                "--description", worker.description
            ]
            
            # Set up environment
            env = os.environ.copy()
            env['PYTHONPATH'] = os.getcwd()
            
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
    
    def stop_worker(self, worker: WorkerProcess) -> bool:
        """Stop a worker process"""
        try:
            if not worker.process or worker.process.poll() is not None:
                logger.info(f"Worker for {worker.repo_name} is not running")
                return True
            
            # Send SIGTERM for graceful shutdown
            worker.process.terminate()
            
            # Wait for graceful shutdown
            try:
                worker.process.wait(timeout=10)
                logger.info(f"Worker for {worker.repo_name} stopped gracefully")
            except subprocess.TimeoutExpired:
                # Force kill if doesn't respond
                worker.process.kill()
                worker.process.wait()
                logger.warning(f"Worker for {worker.repo_name} force killed")
            
            worker.process = None
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop worker for {worker.repo_name}: {e}")
            return False
    
    def is_worker_healthy(self, worker: WorkerProcess) -> bool:
        """Check if a worker process is healthy"""
        if not worker.process:
            return False
        
        # Check if process is still alive
        if worker.process.poll() is not None:
            return False
        
        # TODO: Add health check HTTP endpoint call
        # For now, just check if process is running
        return True
    
    async def monitor_workers(self):
        """Monitor worker processes and restart if needed"""
        while self.running:
            try:
                for repo_name, worker in self.workers.items():
                    if not self.is_worker_healthy(worker):
                        if worker.restart_count < worker.max_restarts:
                            logger.warning(f"Worker for {repo_name} is unhealthy, restarting...")
                            self.stop_worker(worker)
                            
                            # Wait a bit before restarting
                            await asyncio.sleep(2)
                            
                            if self.start_worker(worker):
                                worker.restart_count += 1
                                logger.info(f"Restarted worker for {repo_name} (restart count: {worker.restart_count})")
                            else:
                                logger.error(f"Failed to restart worker for {repo_name}")
                        else:
                            logger.error(f"Worker for {repo_name} exceeded max restarts ({worker.max_restarts})")
                
                # Check every 30 seconds
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in worker monitoring: {e}")
                await asyncio.sleep(5)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False
        self.shutdown_event.set()
    
    async def start(self):
        """Start the master process"""
        logger.info("Starting GitHub MCP Master Process")
        
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
        await self.shutdown_event.wait()
        
        # Cancel monitoring
        monitor_task.cancel()
        
        # Stop all workers
        logger.info("Stopping all workers...")
        for repo_name, worker in self.workers.items():
            self.stop_worker(worker)
        
        logger.info("GitHub MCP Master Process shutdown complete")
        return True
    
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
