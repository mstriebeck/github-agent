#!/usr/bin/env python3
"""
Test suite for resource_manager.py

This module tests the comprehensive resource management including
database connections, file handles, external services, and cleanup procedures.
"""

import asyncio
import logging
import time
import unittest

from resource_manager import (
    DatabaseConnectionManager,
    ExternalServiceManager,
    FileHandleManager,
    ResourceManager,
)
from shutdown_core import ExitCodes


class MockResource:
    """Mock resource for testing"""

    def __init__(self, name: str, fail_close: bool = False):
        self.name = name
        self.fail_close = fail_close
        self.closed = False
        self.close_called = False

    def close(self):
        self.close_called = True
        if self.fail_close:
            raise Exception(f"Mock close failure for {self.name}")
        self.closed = True

    def is_closed(self):
        return self.closed


class MockAsyncResource:
    """Mock async resource for testing"""

    def __init__(self, name: str, fail_close: bool = False):
        self.name = name
        self.fail_close = fail_close
        self.closed = False
        self.close_called = False

    async def close(self):
        self.close_called = True
        if self.fail_close:
            raise Exception(f"Mock async close failure for {self.name}")
        await asyncio.sleep(0.01)  # Simulate async work
        self.closed = True

    def is_closed(self):
        return self.closed


class TestDatabaseConnectionManager(unittest.TestCase):
    """Test the DatabaseConnectionManager class"""

    def setUp(self):
        self.logger = logging.getLogger(f"test_db_manager_{int(time.time() * 1000000)}")
        self.logger.setLevel(logging.DEBUG)

        # Add basic handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        self.db_manager = DatabaseConnectionManager(self.logger)

    def tearDown(self):
        # Cleanup logger
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

    def test_add_connection(self):
        """Test adding database connections"""
        mock_conn = MockResource("test_db")

        self.db_manager.add_connection("test_conn", mock_conn)

        status = self.db_manager.get_status()
        self.assertEqual(status["connections_count"], 1)
        self.assertIn("test_conn", status["connections"])

    def test_add_connection_pool(self):
        """Test adding database connection pools"""
        mock_pool = MockResource("test_pool")

        self.db_manager.add_connection_pool("test_pool", mock_pool)

        status = self.db_manager.get_status()
        self.assertEqual(status["pools_count"], 1)
        self.assertIn("test_pool", status["pools"])

    async def async_test_close_all_connections(self):
        """Test closing all database connections"""
        mock_conn1 = MockResource("conn1")
        mock_conn2 = MockAsyncResource("conn2")
        mock_pool = MockResource("pool1")

        self.db_manager.add_connection("conn1", mock_conn1)
        self.db_manager.add_connection("conn2", mock_conn2)
        self.db_manager.add_connection_pool("pool1", mock_pool)

        success = await self.db_manager.close_all_connections()

        self.assertTrue(success)
        self.assertTrue(mock_conn1.close_called)
        self.assertTrue(mock_conn2.close_called)
        self.assertTrue(mock_pool.close_called)

        status = self.db_manager.get_status()
        self.assertTrue(status["closed"])
        self.assertEqual(status["connections_count"], 0)
        self.assertEqual(status["pools_count"], 0)

    async def async_test_close_connections_with_failure(self):
        """Test closing connections when some fail"""
        mock_conn_good = MockResource("good_conn")
        mock_conn_bad = MockResource("bad_conn", fail_close=True)

        self.db_manager.add_connection("good", mock_conn_good)
        self.db_manager.add_connection("bad", mock_conn_bad)

        success = await self.db_manager.close_all_connections()

        self.assertFalse(success)  # Should return False due to failure
        self.assertTrue(mock_conn_good.close_called)
        self.assertTrue(mock_conn_bad.close_called)

        status = self.db_manager.get_status()
        self.assertTrue(status["closed"])  # Manager still marked as closed


class TestFileHandleManager(unittest.TestCase):
    """Test the FileHandleManager class"""

    def setUp(self):
        self.logger = logging.getLogger(
            f"test_file_manager_{int(time.time() * 1000000)}"
        )
        self.logger.setLevel(logging.DEBUG)

        # Add basic handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        self.file_manager = FileHandleManager(self.logger)

    def tearDown(self):
        # Cleanup logger
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

    def test_add_file_handle(self):
        """Test adding file handles"""
        mock_file = MockResource("test_file")

        self.file_manager.add_file_handle("test_file", mock_file)

        status = self.file_manager.get_status()
        self.assertEqual(status["handles_count"], 1)
        self.assertIn("test_file", status["handles"])

    def test_close_all_files(self):
        """Test closing all file handles"""
        mock_file1 = MockResource("file1")
        mock_file2 = MockResource("file2")

        self.file_manager.add_file_handle("file1", mock_file1)
        self.file_manager.add_file_handle("file2", mock_file2)

        success = self.file_manager.close_all_files()

        self.assertTrue(success)
        self.assertTrue(mock_file1.close_called)
        self.assertTrue(mock_file2.close_called)

        status = self.file_manager.get_status()
        self.assertTrue(status["closed"])
        self.assertEqual(status["handles_count"], 0)


class TestExternalServiceManager(unittest.TestCase):
    """Test the ExternalServiceManager class"""

    def setUp(self):
        self.logger = logging.getLogger(
            f"test_service_manager_{int(time.time() * 1000000)}"
        )
        self.logger.setLevel(logging.DEBUG)

        # Add basic handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        self.service_manager = ExternalServiceManager(self.logger)

    def tearDown(self):
        # Cleanup logger
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

    def test_add_service(self):
        """Test adding external services"""
        mock_service = MockResource("test_service")

        self.service_manager.add_service("test_service", mock_service)

        status = self.service_manager.get_status()
        self.assertEqual(status["services_count"], 1)
        self.assertIn("test_service", status["services"])

    async def async_test_close_all_services(self):
        """Test closing all external services"""
        mock_service1 = MockResource("service1")
        mock_service2 = MockAsyncResource("service2")

        # Custom cleanup function
        cleanup_called = False

        def custom_cleanup(service):
            nonlocal cleanup_called
            cleanup_called = True
            service.custom_closed = True

        mock_service3 = MockResource("service3")

        self.service_manager.add_service("service1", mock_service1)
        self.service_manager.add_service("service2", mock_service2)
        self.service_manager.add_service("service3", mock_service3, custom_cleanup)

        success = await self.service_manager.close_all_services()

        self.assertTrue(success)
        self.assertTrue(mock_service1.close_called)
        self.assertTrue(mock_service2.close_called)
        self.assertTrue(cleanup_called)
        self.assertTrue(hasattr(mock_service3, "custom_closed"))

        status = self.service_manager.get_status()
        self.assertTrue(status["closed"])
        self.assertEqual(status["services_count"], 0)


class TestResourceManager(unittest.TestCase):
    """Test the main ResourceManager class"""

    def setUp(self):
        self.logger = logging.getLogger(
            f"test_resource_manager_{int(time.time() * 1000000)}"
        )
        self.logger.setLevel(logging.DEBUG)

        # Add basic handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        self.resource_manager = ResourceManager(self.logger)

    def tearDown(self):
        # Cleanup logger
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

    def test_add_generic_resource(self):
        """Test adding generic resources"""
        mock_resource = MockResource("generic_resource")

        self.resource_manager.add_resource("test_resource", mock_resource, priority=1)

        status = self.resource_manager.get_resource_status()
        self.assertEqual(status["generic_resources"]["count"], 1)

        resources = status["generic_resources"]["resources"]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["name"], "test_resource")
        self.assertEqual(resources[0]["priority"], 1)

    def test_add_cleanup_callback(self):
        """Test adding cleanup callbacks"""
        callback_called = False

        def test_callback():
            nonlocal callback_called
            callback_called = True

        self.resource_manager.add_cleanup_callback(test_callback)

        status = self.resource_manager.get_resource_status()
        self.assertEqual(status["cleanup_callbacks"]["count"], 1)
        self.assertIn("test_callback", status["cleanup_callbacks"]["callbacks"])

    async def async_test_cleanup_all_resources_success(self):
        """Test successful cleanup of all resources"""
        # Add various resources
        db_conn = MockResource("db_conn")
        file_handle = MockResource("file_handle")
        service = MockAsyncResource("external_service")
        generic_resource = MockResource("generic")

        callback_called = False

        def cleanup_callback():
            nonlocal callback_called
            callback_called = True

        self.resource_manager.add_database_connection("db_conn", db_conn)
        self.resource_manager.add_file_handle("file_handle", file_handle)
        self.resource_manager.add_external_service("service", service)
        self.resource_manager.add_resource("generic", generic_resource)
        self.resource_manager.add_cleanup_callback(cleanup_callback)

        exit_code = await self.resource_manager.cleanup_all_resources()

        self.assertEqual(exit_code, ExitCodes.SUCCESS)
        self.assertTrue(db_conn.close_called)
        self.assertTrue(file_handle.close_called)
        self.assertTrue(service.close_called)
        self.assertTrue(generic_resource.close_called)
        self.assertTrue(callback_called)

        status = self.resource_manager.get_resource_status()
        self.assertTrue(status["closed"])

    async def async_test_cleanup_with_failures(self):
        """Test cleanup when some resources fail"""
        # Add resources that will fail to close
        bad_db = MockResource("bad_db", fail_close=True)
        good_file = MockResource("good_file")

        def bad_callback():
            raise Exception("Callback failure")

        self.resource_manager.add_database_connection("bad_db", bad_db)
        self.resource_manager.add_file_handle("good_file", good_file)
        self.resource_manager.add_cleanup_callback(bad_callback)

        exit_code = await self.resource_manager.cleanup_all_resources()

        self.assertEqual(exit_code, ExitCodes.RESOURCE_CLEANUP_FAILURE)
        self.assertTrue(bad_db.close_called)  # Should still try to close
        self.assertTrue(good_file.close_called)  # Good resources should still close

        status = self.resource_manager.get_resource_status()
        self.assertTrue(status["closed"])  # Manager should still be marked as closed

    async def async_test_resource_priority_ordering(self):
        """Test that resources are closed in priority order"""
        close_order = []

        def make_resource_with_callback(name, priority):
            resource = MockResource(name)
            original_close = resource.close

            def close_with_tracking():
                close_order.append(name)
                original_close()

            # Use setattr to avoid mypy method assignment error
            resource.close = close_with_tracking
            return resource

        # Add resources with different priorities (lower number = higher priority)
        resource_high = make_resource_with_callback("high_priority", 1)
        resource_low = make_resource_with_callback("low_priority", 10)
        resource_medium = make_resource_with_callback("medium_priority", 5)

        self.resource_manager.add_resource("high", resource_high, priority=1)
        self.resource_manager.add_resource("low", resource_low, priority=10)
        self.resource_manager.add_resource("medium", resource_medium, priority=5)

        await self.resource_manager.cleanup_all_resources()

        # Should close in priority order: high (1), medium (5), low (10)
        self.assertEqual(
            close_order, ["high_priority", "medium_priority", "low_priority"]
        )

    def test_prevent_operations_after_close(self):
        """Test that operations are prevented after manager is closed"""
        self.resource_manager._closed = True

        mock_resource = MockResource("test")

        # These should not add anything and should log warnings
        self.resource_manager.add_resource("test", mock_resource)
        self.resource_manager.add_database_connection("db", mock_resource)

        status = self.resource_manager.get_resource_status()
        self.assertEqual(status["generic_resources"]["count"], 0)
        self.assertEqual(status["databases"]["connections_count"], 0)


async def run_async_tests():
    """Run async tests manually"""
    print("Running async tests:")

    test_classes = [
        TestDatabaseConnectionManager,
        TestExternalServiceManager,
        TestResourceManager,
    ]

    for test_class in test_classes:
        print(f"\nTesting {test_class.__name__}:")

        # Find async test methods
        for method_name in dir(test_class):
            if method_name.startswith("async_test_") and asyncio.iscoroutinefunction(
                getattr(test_class, method_name)
            ):
                print(f"  Running {method_name}...")
                test_instance = test_class()
                test_instance.setUp()

                try:
                    await getattr(test_instance, method_name)()
                    print(f"  ✓ {method_name} passed")
                except Exception as e:
                    print(f"  ✗ {method_name} failed: {e}")
                finally:
                    test_instance.tearDown()


if __name__ == "__main__":
    # Run regular unittest for sync tests
    unittest.main(verbosity=2, exit=False)

    print("\n" + "=" * 50)
    print("Running async tests separately:")
    print("=" * 50)

    # Run async tests
    asyncio.run(run_async_tests())
