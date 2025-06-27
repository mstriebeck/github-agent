"""
Integrated Shutdown Manager for MCP Server System

This module integrates all shutdown components into a comprehensive system that
can be used by the MCP master and worker processes for clean shutdown.

Key Features:
- Orchestrates all shutdown phases in the correct order
- Manages workers, clients, resources, and system cleanup
- Provides both master and worker integration points
- Comprehensive logging and monitoring throughout
"""

import asyncio
import logging
import signal
import time
from collections.abc import Callable
from typing import Any, Optional, Awaitable

from client_manager import ClientConnectionManager
from resource_manager import ResourceManager

# Import all our shutdown components
from exit_codes import ShutdownExitCode
from shutdown_core import ShutdownCoordinator
from system_utils import SystemMonitor
from worker_manager import WorkerManager, WorkerProcess


class IntegratedShutdownManager:
    """
    Comprehensive shutdown manager that orchestrates all shutdown components

    This is the main integration point that brings together:
    - Worker process management (for master)
    - Resource cleanup (databases, files, etc.)
    - Client connection management (MCP protocol clients)
    - System monitoring and verification
    """

    def __init__(self, logger: logging.Logger, mode: str = "master"):
        """
        Initialize the integrated shutdown manager

        Args:
            logger: Logger instance for shutdown operations
            mode: Either "master" or "worker" to determine available components
        """
        self.logger = logger
        self.mode = mode
        self.shutdown_in_progress = False
        self.shutdown_start_time: Optional[float] = None

        # Core components
        self.shutdown_coordinator = ShutdownCoordinator(logger)
        self.system_monitor = SystemMonitor()

        # Mode-specific components
        self.worker_manager: Optional[WorkerManager]
        if mode == "master":
            self.worker_manager = WorkerManager(logger)
        else:
            self.worker_manager = None

        self.resource_manager = ResourceManager(logger)
        self.client_manager = ClientConnectionManager(logger)

        # Shutdown callbacks
        self._shutdown_callbacks: list[Callable[[], None]] = []
        self._async_shutdown_callbacks: list[Callable[[], Awaitable[None]]] = []

        # Shutdown phases completed
        self._completed_phases: list[str] = []

        self.logger.info(f"Initialized IntegratedShutdownManager in {mode} mode")

    def register_shutdown_callback(
        self, callback: Callable[[], None], is_async: bool = False
    ) -> None:
        """Register a custom shutdown callback"""
        if is_async:
            # Type: ignore here because we know the callback is actually async
            self._async_shutdown_callbacks.append(callback)  # type: ignore
        else:
            self._shutdown_callbacks.append(callback)
        self.logger.debug(
            f"Registered shutdown callback: {callback.__name__} (async: {is_async})"
        )

    # Worker Management (Master mode only)
    def add_worker(
        self, repo_name: str, port: int, path: str, description: str = "", **kwargs: Any
    ) -> Optional[WorkerProcess]:
        """Add a worker process to be managed (master mode only)"""
        if self.mode != "master" or not self.worker_manager:
            self.logger.warning("Worker management only available in master mode")
            return None

        worker = WorkerProcess(
            repo_name=repo_name,
            port=port,
            path=path,
            description=description,
            **kwargs
        )
        self.worker_manager.add_worker(worker)
        return worker

    def get_worker(self, repo_name: str) -> Optional[WorkerProcess]:
        """Get worker process by name"""
        if self.mode != "master" or not self.worker_manager:
            return None
        return self.worker_manager.get_worker(repo_name)

    def get_all_workers(self) -> list[WorkerProcess]:
        """Get all worker processes"""
        if self.mode != "master" or not self.worker_manager:
            return []
        return list(self.worker_manager.workers.values())

    async def start_worker(self, repo_name: str, command: list[str], env: Optional[dict[str, str]] = None) -> bool:
        """Start a worker process"""
        if self.mode != "master" or not self.worker_manager:
            return False
        worker = self.worker_manager.get_worker(repo_name)
        if not worker:
            return False
        return self.worker_manager.start_worker(worker, command, env)

    # Resource Management
    def add_database_connection(self, name: str, connection: Any) -> None:
        """Add database connection to be managed"""
        self.resource_manager.add_database_connection(name, connection)

    def add_file_handle(self, name: str, file_handle: Any) -> None:
        """Add file handle to be managed"""
        self.resource_manager.add_file_handle(name, file_handle)

    def add_external_service(self, name: str, service: Any) -> None:
        """Add external service to be managed"""
        self.resource_manager.add_external_service(name, service)

    def add_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """Add resource cleanup callback"""
        self.resource_manager.add_cleanup_callback(callback)

    # Client Connection Management
    def add_client(self, client_id: str, transport: Any, **kwargs: Any) -> Any:
        """Add MCP client connection to be managed"""
        return self.client_manager.add_client(client_id, transport, **kwargs)

    def remove_client(self, client_id: str, reason: Any = None) -> Any:
        """Remove MCP client connection"""
        from client_manager import DisconnectionReason

        reason = reason or DisconnectionReason.CLIENT_REQUEST
        return self.client_manager.remove_client(client_id, reason)

    def get_client(self, client_id: str) -> Any:
        """Get MCP client by ID"""
        return self.client_manager.get_client(client_id)

    async def broadcast_to_clients(
        self, method: str, params: dict[str, Any], group: Optional[str] = None
    ) -> Any:
        """Broadcast notification to clients"""
        return await self.client_manager.broadcast_notification(method, params, group)

    # Status and Monitoring
    def get_status(self) -> dict[str, Any]:
        """Get comprehensive system status"""
        status = {
            "mode": self.mode,
            "shutdown_in_progress": self.shutdown_in_progress,
            "completed_phases": self._completed_phases,
            "system_metrics": self.system_monitor.get_system_metrics(),
            "resources": self.resource_manager.get_resource_status(),
            "clients": self.client_manager.get_status(),
        }

        if self.mode == "master" and self.worker_manager:
            status["workers"] = self.worker_manager.get_worker_status()

        if self.shutdown_start_time:
            status["shutdown_duration"] = time.time() - self.shutdown_start_time

        return status

    # Main Shutdown Process
    async def graceful_shutdown(
        self,
        grace_period: float = 10.0,
        force_timeout: float = 5.0,
        exit_code: int = ShutdownExitCode.SUCCESS_CLEAN_SHUTDOWN,
    ) -> bool:
        """
        Execute comprehensive graceful shutdown

        Shutdown phases:
        1. Signal shutdown start and notify clients
        2. Stop accepting new connections/requests
        3. Gracefully disconnect clients
        4. Shutdown worker processes (master mode)
        5. Cleanup resources (databases, files, services)
        6. Execute custom shutdown callbacks
        7. Final system verification

        Args:
            grace_period: Time to wait for graceful operations
            force_timeout: Time to wait for forced operations
            exit_code: Exit code to use when shutting down

        Returns:
            True if shutdown completed successfully, False otherwise
        """
        if self.shutdown_in_progress:
            self.logger.warning("Shutdown already in progress")
            return False

        self.shutdown_in_progress = True
        self.shutdown_start_time = time.time()

        self.logger.info(
            f"🔄 Starting comprehensive system shutdown (grace: {grace_period}s, force: {force_timeout}s)"
        )

        # Log initial system state
        await self.system_monitor.log_system_state(
            self.logger, "COMPREHENSIVE_SHUTDOWN_STARTING"
        )

        try:
            success = True

            # Phase 1: Notify clients of impending shutdown
            self.logger.info("📢 Phase 1: Notifying clients of shutdown")
            try:
                from client_manager import DisconnectionReason

                await self.client_manager.broadcast_notification(
                    "server/shutdown_initiated",
                    {
                        "reason": DisconnectionReason.SHUTDOWN.value,
                        "grace_period_seconds": grace_period,
                        "timestamp": time.time(),
                    },
                )
                self._completed_phases.append("client_notification")
                self.logger.info("✅ Phase 1 completed: Client notification sent")
            except Exception as e:
                self.logger.error(f"❌ Phase 1 failed: Client notification error: {e}")
                success = False

            # Phase 2: Gracefully disconnect clients
            self.logger.info("🔌 Phase 2: Gracefully disconnecting clients")
            try:
                client_success = await self.client_manager.graceful_shutdown(
                    grace_period=grace_period
                    * 0.3,  # Use 30% of grace period for clients
                    force_timeout=force_timeout * 0.5,
                )
                if client_success:
                    self._completed_phases.append("client_shutdown")
                    self.logger.info("✅ Phase 2 completed: All clients disconnected")
                else:
                    self.logger.warning(
                        "⚠️ Phase 2 partial: Some clients failed to disconnect"
                    )
                    success = False
            except Exception as e:
                self.logger.error(f"❌ Phase 2 failed: Client disconnect error: {e}")
                success = False

            # Phase 3: Shutdown worker processes (master mode only)
            if self.mode == "master" and self.worker_manager:
                self.logger.info("👷 Phase 3: Shutting down worker processes")
                try:
                    worker_success = await self.worker_manager.shutdown_all_workers()
                    if worker_success:
                        self._completed_phases.append("worker_shutdown")
                        self.logger.info("✅ Phase 3 completed: All workers shut down")
                    else:
                        self.logger.warning(
                            "⚠️ Phase 3 partial: Some workers failed to shut down"
                        )
                        success = False
                except Exception as e:
                    self.logger.error(f"❌ Phase 3 failed: Worker shutdown error: {e}")
                    success = False
            else:
                self.logger.info(
                    "⏭️ Phase 3 skipped: Worker management not available in worker mode"
                )

            # Phase 4: Execute custom shutdown callbacks
            self.logger.info("🔧 Phase 4: Executing custom shutdown callbacks")
            try:
                callback_success = await self._execute_shutdown_callbacks()
                if callback_success:
                    self._completed_phases.append("custom_callbacks")
                    self.logger.info("✅ Phase 4 completed: Custom callbacks executed")
                else:
                    self.logger.warning("⚠️ Phase 4 partial: Some callbacks failed")
                    success = False
            except Exception as e:
                self.logger.error(f"❌ Phase 4 failed: Callback execution error: {e}")
                success = False

            # Phase 5: Cleanup resources
            self.logger.info("🧹 Phase 5: Cleaning up resources")
            try:
                resource_success = await self.resource_manager.cleanup_all_resources()
                if resource_success:
                    self._completed_phases.append("resource_cleanup")
                    self.logger.info("✅ Phase 5 completed: All resources cleaned up")
                else:
                    self.logger.warning(
                        "⚠️ Phase 5 partial: Some resources failed to clean up"
                    )
                    success = False
            except Exception as e:
                self.logger.error(f"❌ Phase 5 failed: Resource cleanup error: {e}")
                success = False

            # Phase 6: Final system verification
            self.logger.info("🔍 Phase 6: Final system verification")
            try:
                verification_success = await self._verify_clean_shutdown()
                if verification_success:
                    self._completed_phases.append("verification")
                    self.logger.info("✅ Phase 6 completed: System verification passed")
                else:
                    self.logger.warning(
                        "⚠️ Phase 6 partial: System verification found issues"
                    )
                    success = False
            except Exception as e:
                self.logger.error(f"❌ Phase 6 failed: System verification error: {e}")
                success = False

            # Log final system state
            await self.system_monitor.log_system_state(
                self.logger, "COMPREHENSIVE_SHUTDOWN_COMPLETED"
            )

            total_duration = time.time() - self.shutdown_start_time

            if success:
                self.logger.info(
                    f"🎉 Comprehensive shutdown completed successfully in {total_duration:.3f}s"
                )
                self.logger.info(
                    f"📊 Completed phases: {', '.join(self._completed_phases)}"
                )
            else:
                self.logger.error(
                    f"💥 Comprehensive shutdown completed with errors in {total_duration:.3f}s"
                )
                self.logger.error(
                    f"📊 Completed phases: {', '.join(self._completed_phases)}"
                )

            # Set exit code for the shutdown coordinator
            # Note: ShutdownCoordinator doesn't have exit_code attribute, 
            # this should be handled by the application using this manager
            self.logger.info(
                f"Shutdown completed with exit code: {exit_code if success else ShutdownExitCode.SHUTDOWN_COORDINATOR_ERROR}"
            )

            return success

        except Exception as e:
            self.logger.error(f"💥 Critical error during shutdown: {e}")
            import traceback

            self.logger.error(f"Traceback: {traceback.format_exc()}")
            # Log the error exit code instead of setting it on coordinator
            self.logger.error(f"Critical shutdown error, exit code: {ShutdownExitCode.SHUTDOWN_COORDINATOR_ERROR}")
            return False

    async def _execute_shutdown_callbacks(self) -> bool:
        """Execute all registered shutdown callbacks"""
        success = True

        # Execute synchronous callbacks
        for callback in self._shutdown_callbacks:
            try:
                self.logger.debug(f"Executing sync callback: {callback.__name__}")
                callback()
            except Exception as e:
                self.logger.error(f"Sync callback {callback.__name__} failed: {e}")
                success = False

        # Execute asynchronous callbacks
        for async_callback in self._async_shutdown_callbacks:
            try:
                self.logger.debug(f"Executing async callback: {async_callback.__name__}")
                await async_callback()
            except Exception as e:
                self.logger.error(f"Async callback {async_callback.__name__} failed: {e}")
                success = False

        return success

    async def _verify_clean_shutdown(self) -> bool:
        """Verify that shutdown was clean with no remaining resources"""
        success = True

        # Check for remaining clients
        client_count = len(self.client_manager.get_all_clients())
        if client_count > 0:
            self.logger.warning(
                f"🔌 {client_count} clients still connected after shutdown"
            )
            success = False

        # Check for remaining workers (master mode)
        if self.mode == "master" and self.worker_manager:
            active_workers = [
                w for w in self.worker_manager.workers.values() if self.worker_manager.is_worker_healthy(w)
            ]
            if active_workers:
                self.logger.warning(
                    f"👷 {len(active_workers)} workers still running after shutdown"
                )
                success = False

        # Check system metrics for anomalies
        try:
            metrics = self.system_monitor.get_system_metrics()
            if "process" in metrics:
                open_files = metrics["process"].get("open_files_count", 0)
                connections = metrics["process"].get("connections_count", 0)

                if open_files > 10:  # Allow some baseline files
                    self.logger.warning(
                        f"📁 {open_files} files still open after shutdown"
                    )

                if connections > 0:
                    self.logger.warning(
                        f"🔗 {connections} network connections still open after shutdown"
                    )
        except Exception as e:
            self.logger.warning(f"Could not verify system metrics: {e}")

        return success

    def setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown"""

        def signal_handler(signum: int, frame: Any) -> None:
            signal_name = signal.Signals(signum).name
            self.logger.info(f"🚨 Received signal {signal_name} ({signum})")

            # Start graceful shutdown in the background
            if not self.shutdown_in_progress:
                asyncio.create_task(
                    self.graceful_shutdown(
                        grace_period=10.0,
                        force_timeout=5.0,
                        exit_code=ShutdownExitCode.SUCCESS_SIGNAL_SHUTDOWN,
                    )
                )

        # Register signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, signal_handler)

        self.logger.info("🎯 Signal handlers installed for graceful shutdown")

    def close(self) -> None:
        """Synchronous cleanup for emergency situations"""
        self.logger.info("🚪 Emergency close called")

        try:
            # Use proper cleanup methods instead of non-existent close() methods
            if hasattr(self.resource_manager, 'cleanup_all_resources'):
                # Run async cleanup synchronously in emergency
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If loop is running, schedule cleanup for later
                        asyncio.create_task(self.resource_manager.cleanup_all_resources())
                    else:
                        loop.run_until_complete(self.resource_manager.cleanup_all_resources())
                except RuntimeError:
                    # No event loop, skip async cleanup
                    self.logger.warning("Cannot run async resource cleanup in emergency close")
            
            if hasattr(self.client_manager, 'graceful_shutdown'):
                # Similarly handle client manager cleanup
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.client_manager.graceful_shutdown())
                    else:
                        loop.run_until_complete(self.client_manager.graceful_shutdown())
                except RuntimeError:
                    self.logger.warning("Cannot run async client cleanup in emergency close")
            
            if self.worker_manager and hasattr(self.worker_manager, 'shutdown_all_workers'):
                # Handle worker manager cleanup
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.worker_manager.shutdown_all_workers())
                    else:
                        loop.run_until_complete(self.worker_manager.shutdown_all_workers())
                except RuntimeError:
                    self.logger.warning("Cannot run async worker cleanup in emergency close")
        except Exception as e:
            self.logger.error(f"Error during emergency close: {e}")


# Convenience functions for easy integration


def create_master_shutdown_manager(logger: logging.Logger) -> IntegratedShutdownManager:
    """Create a shutdown manager for master mode"""
    return IntegratedShutdownManager(logger, mode="master")


def create_worker_shutdown_manager(logger: logging.Logger) -> IntegratedShutdownManager:
    """Create a shutdown manager for worker mode"""
    return IntegratedShutdownManager(logger, mode="worker")


async def graceful_system_shutdown(
    shutdown_manager: IntegratedShutdownManager,
    grace_period: float = 10.0,
    force_timeout: float = 5.0,
) -> bool:
    """Convenience function for graceful system shutdown"""
    return await shutdown_manager.graceful_shutdown(grace_period, force_timeout)
