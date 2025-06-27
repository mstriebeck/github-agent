"""
Resource Manager for Clean Shutdown

This module provides resource management for database connections, file handles,
external services, and other resources that need clean shutdown procedures.
"""

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from shutdown_core import ExitCodes
from system_utils import log_system_state


class Resource(Protocol):
    """Protocol for resources that can be managed during shutdown"""

    def close(self) -> None:
        """Close the resource synchronously"""
        ...

    def is_closed(self) -> bool:
        """Check if the resource is closed"""
        ...


class AsyncResource(Protocol):
    """Protocol for async resources that can be managed during shutdown"""

    async def close(self) -> None:
        """Close the resource asynchronously"""
        ...

    def is_closed(self) -> bool:
        """Check if the resource is closed"""
        ...


@dataclass
class ResourceInfo:
    """Information about a managed resource"""

    name: str
    resource: Any
    cleanup_func: Callable | None = None
    is_async: bool = False
    priority: int = 0  # Lower number = higher priority for cleanup
    timeout: float = 10.0
    created_at: datetime = field(default_factory=datetime.now)
    closed_at: datetime | None = None
    close_attempts: int = 0


class DatabaseConnectionManager:
    """Manages database connections with graceful shutdown"""

    def __init__(self, logger):
        self.logger = logger
        self._connections: dict[str, Any] = {}
        self._connection_pools: dict[str, Any] = {}
        self._closed = False

    def add_connection(self, name: str, connection: Any) -> None:
        """Add a database connection to be managed"""
        if self._closed:
            self.logger.warning(f"Cannot add connection {name} - manager is closed")
            return

        self._connections[name] = connection
        self.logger.debug(f"Added database connection: {name}")

    def add_connection_pool(self, name: str, pool: Any) -> None:
        """Add a database connection pool to be managed"""
        if self._closed:
            self.logger.warning(
                f"Cannot add connection pool {name} - manager is closed"
            )
            return

        self._connection_pools[name] = pool
        self.logger.debug(f"Added database connection pool: {name}")

    async def close_all_connections(self, timeout: float = 30.0) -> bool:
        """Close all database connections and pools"""
        if self._closed:
            self.logger.info("Database connections already closed")
            return True

        start_time = datetime.now()
        self.logger.info(
            f"Closing {len(self._connections)} connections and {len(self._connection_pools)} pools"
        )

        success = True

        # Close individual connections
        for name, connection in list(self._connections.items()):
            try:
                conn_start = datetime.now()
                self.logger.debug(f"Closing database connection: {name}")

                # Try different close methods depending on the connection type
                if hasattr(connection, "close"):
                    if asyncio.iscoroutinefunction(connection.close):
                        await asyncio.wait_for(connection.close(), timeout=5.0)
                    else:
                        connection.close()
                elif hasattr(connection, "disconnect"):
                    if asyncio.iscoroutinefunction(connection.disconnect):
                        await asyncio.wait_for(connection.disconnect(), timeout=5.0)
                    else:
                        connection.disconnect()

                conn_duration = (datetime.now() - conn_start).total_seconds()
                self.logger.info(
                    f"✓ Closed database connection {name} in {conn_duration:.3f}s"
                )

            except Exception as e:
                conn_duration = (datetime.now() - conn_start).total_seconds()
                self.logger.error(
                    f"✗ Failed to close database connection {name} after {conn_duration:.3f}s: {e}"
                )
                success = False

        # Close connection pools
        for name, pool in list(self._connection_pools.items()):
            try:
                pool_start = datetime.now()
                self.logger.debug(f"Closing database connection pool: {name}")

                if hasattr(pool, "close"):
                    if asyncio.iscoroutinefunction(pool.close):
                        await asyncio.wait_for(pool.close(), timeout=10.0)
                    else:
                        pool.close()
                elif hasattr(pool, "terminate"):
                    if asyncio.iscoroutinefunction(pool.terminate):
                        await asyncio.wait_for(pool.terminate(), timeout=10.0)
                    else:
                        pool.terminate()

                pool_duration = (datetime.now() - pool_start).total_seconds()
                self.logger.info(
                    f"✓ Closed database connection pool {name} in {pool_duration:.3f}s"
                )

            except Exception as e:
                pool_duration = (datetime.now() - pool_start).total_seconds()
                self.logger.error(
                    f"✗ Failed to close database connection pool {name} after {pool_duration:.3f}s: {e}"
                )
                success = False

        # Clear the registries
        self._connections.clear()
        self._connection_pools.clear()
        self._closed = True

        total_duration = (datetime.now() - start_time).total_seconds()
        status = (
            "✓ All database connections closed"
            if success
            else "✗ Some database connections failed to close"
        )
        self.logger.info(f"{status} in {total_duration:.3f}s")

        return success

    def get_status(self) -> dict[str, Any]:
        """Get status of managed database connections"""
        return {
            "closed": self._closed,
            "connections_count": len(self._connections),
            "pools_count": len(self._connection_pools),
            "connections": list(self._connections.keys()),
            "pools": list(self._connection_pools.keys()),
        }


class FileHandleManager:
    """Manages file handles and ensures they're closed during shutdown"""

    def __init__(self, logger):
        self.logger = logger
        self._file_handles: dict[str, Any] = {}
        self._closed = False

    def add_file_handle(self, name: str, file_handle: Any) -> None:
        """Add a file handle to be managed"""
        if self._closed:
            self.logger.warning(f"Cannot add file handle {name} - manager is closed")
            return

        self._file_handles[name] = file_handle
        self.logger.debug(f"Added file handle: {name}")

    def close_all_files(self) -> bool:
        """Close all managed file handles"""
        if self._closed:
            self.logger.info("File handles already closed")
            return True

        start_time = datetime.now()
        self.logger.info(f"Closing {len(self._file_handles)} file handles")

        success = True

        for name, file_handle in list(self._file_handles.items()):
            try:
                handle_start = datetime.now()
                self.logger.debug(f"Closing file handle: {name}")

                if hasattr(file_handle, "close"):
                    file_handle.close()
                elif hasattr(file_handle, "flush"):
                    file_handle.flush()

                handle_duration = (datetime.now() - handle_start).total_seconds()
                self.logger.info(
                    f"✓ Closed file handle {name} in {handle_duration:.3f}s"
                )

            except Exception as e:
                handle_duration = (datetime.now() - handle_start).total_seconds()
                self.logger.error(
                    f"✗ Failed to close file handle {name} after {handle_duration:.3f}s: {e}"
                )
                success = False

        self._file_handles.clear()
        self._closed = True

        total_duration = (datetime.now() - start_time).total_seconds()
        status = (
            "✓ All file handles closed"
            if success
            else "✗ Some file handles failed to close"
        )
        self.logger.info(f"{status} in {total_duration:.3f}s")

        return success

    def get_status(self) -> dict[str, Any]:
        """Get status of managed file handles"""
        return {
            "closed": self._closed,
            "handles_count": len(self._file_handles),
            "handles": list(self._file_handles.keys()),
        }


class ExternalServiceManager:
    """Manages connections to external services"""

    def __init__(self, logger):
        self.logger = logger
        self._services: dict[str, Any] = {}
        self._closed = False

    def add_service(
        self, name: str, service: Any, cleanup_func: Callable | None = None
    ) -> None:
        """Add an external service connection to be managed"""
        if self._closed:
            self.logger.warning(f"Cannot add service {name} - manager is closed")
            return

        self._services[name] = {"service": service, "cleanup_func": cleanup_func}
        self.logger.debug(f"Added external service: {name}")

    async def close_all_services(self, timeout: float = 20.0) -> bool:
        """Close all external service connections"""
        if self._closed:
            self.logger.info("External services already closed")
            return True

        start_time = datetime.now()
        self.logger.info(f"Closing {len(self._services)} external services")

        success = True

        for name, service_info in list(self._services.items()):
            try:
                service_start = datetime.now()
                self.logger.debug(f"Closing external service: {name}")

                service = service_info["service"]
                cleanup_func = service_info.get("cleanup_func")

                if cleanup_func:
                    # Use custom cleanup function
                    if asyncio.iscoroutinefunction(cleanup_func):
                        await asyncio.wait_for(cleanup_func(service), timeout=5.0)
                    else:
                        cleanup_func(service)
                elif hasattr(service, "close"):
                    # Try standard close method
                    if asyncio.iscoroutinefunction(service.close):
                        await asyncio.wait_for(service.close(), timeout=5.0)
                    else:
                        service.close()
                elif hasattr(service, "disconnect"):
                    # Try disconnect method
                    if asyncio.iscoroutinefunction(service.disconnect):
                        await asyncio.wait_for(service.disconnect(), timeout=5.0)
                    else:
                        service.disconnect()

                service_duration = (datetime.now() - service_start).total_seconds()
                self.logger.info(
                    f"✓ Closed external service {name} in {service_duration:.3f}s"
                )

            except Exception as e:
                service_duration = (datetime.now() - service_start).total_seconds()
                self.logger.error(
                    f"✗ Failed to close external service {name} after {service_duration:.3f}s: {e}"
                )
                success = False

        self._services.clear()
        self._closed = True

        total_duration = (datetime.now() - start_time).total_seconds()
        status = (
            "✓ All external services closed"
            if success
            else "✗ Some external services failed to close"
        )
        self.logger.info(f"{status} in {total_duration:.3f}s")

        return success

    def get_status(self) -> dict[str, Any]:
        """Get status of managed external services"""
        return {
            "closed": self._closed,
            "services_count": len(self._services),
            "services": list(self._services.keys()),
        }


class ResourceManager:
    """Comprehensive resource manager for clean shutdown"""

    def __init__(self, logger):
        self.logger = logger
        self.database_manager = DatabaseConnectionManager(logger)
        self.file_manager = FileHandleManager(logger)
        self.service_manager = ExternalServiceManager(logger)

        # Generic resource registry
        self._resources: dict[str, ResourceInfo] = {}
        self._cleanup_callbacks: list[Callable] = []
        self._closed = False
        self._lock = threading.Lock()

    def add_resource(
        self,
        name: str,
        resource: Any,
        cleanup_func: Callable | None = None,
        is_async: bool = False,
        priority: int = 0,
        timeout: float = 10.0,
    ) -> None:
        """Add a generic resource to be managed"""
        with self._lock:
            if self._closed:
                self.logger.warning(f"Cannot add resource {name} - manager is closed")
                return

            resource_info = ResourceInfo(
                name=name,
                resource=resource,
                cleanup_func=cleanup_func,
                is_async=is_async,
                priority=priority,
                timeout=timeout,
            )

            self._resources[name] = resource_info
            self.logger.debug(
                f"Added resource: {name} (priority: {priority}, async: {is_async})"
            )

    def add_cleanup_callback(self, callback: Callable) -> None:
        """Add a cleanup callback to be executed during shutdown"""
        self._cleanup_callbacks.append(callback)
        self.logger.debug(f"Added cleanup callback: {callback.__name__}")

    def add_database_connection(self, name: str, connection: Any) -> None:
        """Add a database connection to be managed"""
        if self._closed:
            self.logger.warning(
                f"Cannot add database connection {name} - manager is closed"
            )
            return
        self.database_manager.add_connection(name, connection)

    def add_database_pool(self, name: str, pool: Any) -> None:
        """Add a database connection pool to be managed"""
        self.database_manager.add_connection_pool(name, pool)

    def add_file_handle(self, name: str, file_handle: Any) -> None:
        """Add a file handle to be managed"""
        self.file_manager.add_file_handle(name, file_handle)

    def add_external_service(
        self, name: str, service: Any, cleanup_func: Callable | None = None
    ) -> None:
        """Add an external service to be managed"""
        self.service_manager.add_service(name, service, cleanup_func)

    async def cleanup_all_resources(self, timeout: float = 60.0) -> int:
        """Clean up all managed resources and return appropriate exit code"""
        if self._closed:
            self.logger.info("Resources already cleaned up")
            return ExitCodes.SUCCESS

        with self._lock:
            self._closed = True

        start_time = datetime.now()
        self.logger.info("Starting comprehensive resource cleanup")

        # Log system state before cleanup
        log_system_state(self.logger, "RESOURCE_CLEANUP_STARTING")

        failed_resources = []

        try:
            # Phase 1: Close databases (high priority)
            self.logger.info("Phase 1: Closing database connections")
            db_success = await asyncio.wait_for(
                self.database_manager.close_all_connections(), timeout=20.0
            )
            if not db_success:
                failed_resources.append("database_connections")

            # Phase 2: Close external services
            self.logger.info("Phase 2: Closing external services")
            services_success = await asyncio.wait_for(
                self.service_manager.close_all_services(), timeout=15.0
            )
            if not services_success:
                failed_resources.append("external_services")

            # Phase 3: Close generic resources (by priority)
            if self._resources:
                self.logger.info(
                    f"Phase 3: Closing {len(self._resources)} generic resources"
                )
                resources_success = await self._close_generic_resources()
                if not resources_success:
                    failed_resources.append("generic_resources")

            # Phase 4: Execute cleanup callbacks
            if self._cleanup_callbacks:
                self.logger.info(
                    f"Phase 4: Executing {len(self._cleanup_callbacks)} cleanup callbacks"
                )
                callbacks_success = await self._execute_cleanup_callbacks()
                if not callbacks_success:
                    failed_resources.append("cleanup_callbacks")

            # Phase 5: Close file handles (lowest priority)
            self.logger.info("Phase 5: Closing file handles")
            files_success = self.file_manager.close_all_files()
            if not files_success:
                failed_resources.append("file_handles")

        except TimeoutError:
            self.logger.error(f"Resource cleanup timed out after {timeout}s")
            failed_resources.append("timeout")
        except Exception as e:
            self.logger.error(
                f"Unexpected error during resource cleanup: {e}", exc_info=True
            )
            failed_resources.append("unexpected_error")

        # Log final system state
        log_system_state(self.logger, "RESOURCE_CLEANUP_COMPLETED")

        total_duration = (datetime.now() - start_time).total_seconds()

        if not failed_resources:
            self.logger.info(
                f"✓ All resources cleaned up successfully in {total_duration:.3f}s"
            )
            return ExitCodes.SUCCESS
        else:
            self.logger.error(
                f"✗ Resource cleanup completed with failures in {total_duration:.3f}s: {failed_resources}"
            )
            return ExitCodes.RESOURCE_CLEANUP_FAILURE

    async def _close_generic_resources(self) -> bool:
        """Close generic resources in priority order"""
        # Sort resources by priority (lower number = higher priority)
        sorted_resources = sorted(self._resources.values(), key=lambda r: r.priority)

        success = True

        for resource_info in sorted_resources:
            try:
                resource_start = datetime.now()
                self.logger.debug(f"Closing resource: {resource_info.name}")

                resource_info.close_attempts += 1

                if resource_info.cleanup_func:
                    # Use custom cleanup function
                    if resource_info.is_async:
                        await asyncio.wait_for(
                            resource_info.cleanup_func(resource_info.resource),
                            timeout=resource_info.timeout,
                        )
                    else:
                        resource_info.cleanup_func(resource_info.resource)
                elif hasattr(resource_info.resource, "close"):
                    # Use standard close method
                    if resource_info.is_async:
                        await asyncio.wait_for(
                            resource_info.resource.close(),
                            timeout=resource_info.timeout,
                        )
                    else:
                        resource_info.resource.close()

                resource_info.closed_at = datetime.now()
                resource_duration = (
                    resource_info.closed_at - resource_start
                ).total_seconds()
                self.logger.info(
                    f"✓ Closed resource {resource_info.name} in {resource_duration:.3f}s"
                )

            except Exception as e:
                resource_duration = (datetime.now() - resource_start).total_seconds()
                self.logger.error(
                    f"✗ Failed to close resource {resource_info.name} after {resource_duration:.3f}s: {e}"
                )
                success = False

        return success

    async def _execute_cleanup_callbacks(self) -> bool:
        """Execute all cleanup callbacks"""
        success = True

        for callback in self._cleanup_callbacks:
            try:
                callback_start = datetime.now()
                self.logger.debug(f"Executing cleanup callback: {callback.__name__}")

                if asyncio.iscoroutinefunction(callback):
                    await asyncio.wait_for(callback(), timeout=10.0)
                else:
                    callback()

                callback_duration = (datetime.now() - callback_start).total_seconds()
                self.logger.info(
                    f"✓ Executed cleanup callback {callback.__name__} in {callback_duration:.3f}s"
                )

            except Exception as e:
                callback_duration = (datetime.now() - callback_start).total_seconds()
                self.logger.error(
                    f"✗ Failed to execute cleanup callback {callback.__name__} after {callback_duration:.3f}s: {e}"
                )
                success = False

        return success

    def get_resource_status(self) -> dict[str, Any]:
        """Get comprehensive status of all managed resources"""
        with self._lock:
            return {
                "closed": self._closed,
                "databases": self.database_manager.get_status(),
                "files": self.file_manager.get_status(),
                "services": self.service_manager.get_status(),
                "generic_resources": {
                    "count": len(self._resources),
                    "resources": [
                        {
                            "name": info.name,
                            "priority": info.priority,
                            "is_async": info.is_async,
                            "close_attempts": info.close_attempts,
                            "created_at": info.created_at.isoformat(),
                            "closed_at": info.closed_at.isoformat()
                            if info.closed_at
                            else None,
                        }
                        for info in self._resources.values()
                    ],
                },
                "cleanup_callbacks": {
                    "count": len(self._cleanup_callbacks),
                    "callbacks": [cb.__name__ for cb in self._cleanup_callbacks],
                },
            }

    def is_closed(self) -> bool:
        """Check if the resource manager is closed"""
        return self._closed
