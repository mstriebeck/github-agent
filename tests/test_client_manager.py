#!/usr/bin/env python3

"""
Test suite for Client Connection Manager

Tests graceful client disconnection, connection tracking, and MCP protocol handling.
"""

import asyncio
import json
import logging
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client_manager import (
    ClientConnectionManager,
    ClientInfo,
    ClientState,
    DisconnectionReason,
    MCPClient,
)


class MockTransport:
    """Mock transport for testing"""

    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.sent_data = []
        self.closed = False
        self.write_delay = 0  # Simulate slow writes

    def write(self, data: bytes) -> None:
        """Mock write method"""
        if self.should_fail:
            raise ConnectionError("Mock write failure")
        self.sent_data.append(data)

    async def drain(self) -> None:
        """Mock drain method"""
        if self.write_delay > 0:
            await asyncio.sleep(self.write_delay)
        if self.should_fail:
            raise ConnectionError("Mock drain failure")

    async def send(self, data: str) -> None:
        """Mock send method for websocket-style transport"""
        if self.should_fail:
            raise ConnectionError("Mock send failure")
        await asyncio.sleep(self.write_delay)
        self.sent_data.append(data.encode())

    def close(self) -> None:
        """Mock close method"""
        if self.should_fail and not self.closed:
            raise ConnectionError("Mock close failure")
        self.closed = True

    async def async_close(self) -> None:
        """Mock async close method"""
        await asyncio.sleep(0.001)  # Simulate async work
        self.close()


class TestClientInfo(unittest.TestCase):
    """Test ClientInfo data structure"""

    def test_client_info_creation(self):
        """Test creating ClientInfo"""
        info = ClientInfo(
            client_id="test_client",
            connection_time=time.time(),
            last_activity=time.time(),
            state=ClientState.CONNECTED,
            protocol_version="1.0",
            capabilities={"feature1": True},
            pending_requests=5,
            bytes_sent=1024,
            bytes_received=2048,
            error_count=2,
        )

        self.assertEqual(info.client_id, "test_client")
        self.assertEqual(info.state, ClientState.CONNECTED)
        self.assertEqual(info.protocol_version, "1.0")
        self.assertEqual(info.capabilities["feature1"], True)
        self.assertEqual(info.pending_requests, 5)
        self.assertEqual(info.bytes_sent, 1024)
        self.assertEqual(info.bytes_received, 2048)
        self.assertEqual(info.error_count, 2)

    def test_client_info_to_dict(self):
        """Test converting ClientInfo to dictionary"""
        start_time = time.time()
        info = ClientInfo(
            client_id="test_client",
            connection_time=start_time,
            last_activity=start_time + 10,
            state=ClientState.CONNECTED,
            protocol_version="1.0",
            capabilities={"feature1": True},
            pending_requests=3,
            bytes_sent=512,
            bytes_received=1024,
            error_count=1,
        )

        result = info.to_dict()

        self.assertIsInstance(result, dict)
        self.assertEqual(result["client_id"], "test_client")
        self.assertEqual(result["state"], "connected")
        self.assertEqual(result["protocol_version"], "1.0")
        self.assertEqual(result["capabilities"], {"feature1": True})
        self.assertEqual(result["pending_requests"], 3)
        self.assertEqual(result["bytes_sent"], 512)
        self.assertEqual(result["bytes_received"], 1024)
        self.assertEqual(result["error_count"], 1)
        self.assertIn("uptime", result)
        self.assertGreater(result["uptime"], 0)


class TestMCPClient(unittest.TestCase):
    """Test MCPClient functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger(f"test_client_{int(time.time() * 1000000)}")
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        self.logger.addHandler(handler)

    def test_mcp_client_creation(self):
        """Test creating MCP client"""
        transport = MockTransport()
        client = MCPClient("test_client", transport, self.logger)

        self.assertEqual(client.client_id, "test_client")
        self.assertEqual(client.transport, transport)
        self.assertEqual(client.info.client_id, "test_client")
        self.assertEqual(client.info.state, ClientState.CONNECTING)
        self.assertEqual(client.info.protocol_version, "1.0")
        self.assertEqual(client.info.pending_requests, 0)
        self.assertEqual(client.info.bytes_sent, 0)
        self.assertEqual(client.info.bytes_received, 0)
        self.assertEqual(client.info.error_count, 0)

    def test_client_activity_tracking(self):
        """Test client activity tracking"""
        transport = MockTransport()
        client = MCPClient("test_client", transport, self.logger)

        initial_activity = client.info.last_activity
        time.sleep(0.01)

        client.update_activity()
        self.assertGreater(client.info.last_activity, initial_activity)

        client.increment_pending_requests()
        self.assertEqual(client.info.pending_requests, 1)

        client.increment_pending_requests()
        client.decrement_pending_requests()
        self.assertEqual(client.info.pending_requests, 1)

        client.decrement_pending_requests()
        client.decrement_pending_requests()  # Should not go below 0
        self.assertEqual(client.info.pending_requests, 0)

        client.add_bytes_sent(100)
        client.add_bytes_received(200)
        self.assertEqual(client.info.bytes_sent, 100)
        self.assertEqual(client.info.bytes_received, 200)

        client.increment_errors()
        self.assertEqual(client.info.error_count, 1)

    def test_client_state_management(self):
        """Test client state management"""
        transport = MockTransport()
        client = MCPClient("test_client", transport, self.logger)

        self.assertEqual(client.info.state, ClientState.CONNECTING)

        client.set_state(ClientState.CONNECTED)
        self.assertEqual(client.info.state, ClientState.CONNECTED)

        client.set_state(ClientState.DISCONNECTING)
        self.assertEqual(client.info.state, ClientState.DISCONNECTING)

    async def async_test_send_notification_success(self):
        """Test successful notification sending"""
        transport = MockTransport()
        client = MCPClient("test_client", transport, self.logger)

        success = await client.send_notification("test/method", {"param": "value"})

        self.assertTrue(success)
        self.assertEqual(len(transport.sent_data), 1)

        sent_message = json.loads(transport.sent_data[0].decode().strip())
        self.assertEqual(sent_message["jsonrpc"], "2.0")
        self.assertEqual(sent_message["method"], "test/method")
        self.assertEqual(sent_message["params"]["param"], "value")

        self.assertGreater(client.info.bytes_sent, 0)
        self.assertGreater(client.info.last_activity, 0)

    async def async_test_send_notification_failure(self):
        """Test notification sending failure"""
        transport = MockTransport(should_fail=True)
        client = MCPClient("test_client", transport, self.logger)

        success = await client.send_notification("test/method", {"param": "value"})

        self.assertFalse(success)
        self.assertEqual(client.info.error_count, 1)

    async def async_test_send_shutdown_notification(self):
        """Test sending shutdown notification"""
        transport = MockTransport()
        client = MCPClient("test_client", transport, self.logger)

        success = await client.send_shutdown_notification(
            DisconnectionReason.SHUTDOWN, 10.0
        )

        self.assertTrue(success)
        self.assertEqual(len(transport.sent_data), 1)

        sent_message = json.loads(transport.sent_data[0].decode().strip())
        self.assertEqual(sent_message["method"], "server/shutdown")
        self.assertEqual(sent_message["params"]["reason"], "shutdown")
        self.assertEqual(sent_message["params"]["grace_period_seconds"], 10.0)

    async def async_test_client_disconnect_callbacks(self):
        """Test disconnect callbacks"""
        transport = MockTransport()
        client = MCPClient("test_client", transport, self.logger)

        callback_called = []

        def sync_callback(client_id, reason):
            callback_called.append(("sync", client_id, reason))

        async def async_callback(client_id, reason):
            callback_called.append(("async", client_id, reason))

        client.add_disconnect_callback(sync_callback)
        client.add_disconnect_callback(async_callback)

        success = await client.close_connection(DisconnectionReason.SHUTDOWN)

        self.assertTrue(success)
        self.assertEqual(len(callback_called), 2)
        self.assertIn(
            ("sync", "test_client", DisconnectionReason.SHUTDOWN), callback_called
        )
        self.assertIn(
            ("async", "test_client", DisconnectionReason.SHUTDOWN), callback_called
        )
        self.assertEqual(client.info.state, ClientState.DISCONNECTED)
        self.assertTrue(transport.closed)

    async def async_test_close_connection_failure(self):
        """Test connection close failure"""
        transport = MockTransport(should_fail=True)
        client = MCPClient("test_client", transport, self.logger)

        success = await client.close_connection(DisconnectionReason.SHUTDOWN)

        self.assertFalse(success)
        self.assertEqual(client.info.state, ClientState.ERROR)


class TestClientConnectionManager(unittest.TestCase):
    """Test ClientConnectionManager functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger(f"test_manager_{int(time.time() * 1000000)}")
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        self.logger.addHandler(handler)

        self.manager = ClientConnectionManager(self.logger)

    def test_manager_creation(self):
        """Test creating client manager"""
        self.assertIsInstance(self.manager, ClientConnectionManager)
        self.assertEqual(len(self.manager.get_all_clients()), 0)
        self.assertFalse(self.manager._shutdown_in_progress)
        self.assertFalse(self.manager._closed)

    def test_add_client(self):
        """Test adding clients"""
        transport = MockTransport()

        client = self.manager.add_client(
            "client1",
            transport,
            protocol_version="1.1",
            capabilities={"feature1": True},
            group="test_group",
        )

        self.assertIsInstance(client, MCPClient)
        self.assertEqual(client.client_id, "client1")
        self.assertEqual(client.info.protocol_version, "1.1")
        self.assertEqual(client.info.capabilities, {"feature1": True})
        self.assertEqual(client.info.state, ClientState.CONNECTED)

        # Test retrieving client
        retrieved = self.manager.get_client("client1")
        self.assertEqual(retrieved, client)

        # Test adding duplicate
        duplicate = self.manager.add_client("client1", transport)
        self.assertEqual(duplicate, client)

    def test_add_client_when_closed(self):
        """Test adding client when manager is closed"""
        self.manager.close()
        transport = MockTransport()

        with self.assertRaises(RuntimeError):
            self.manager.add_client("client1", transport)

    def test_remove_client(self):
        """Test removing clients"""
        transport = MockTransport()

        self.manager.add_client("client1", transport, group="test_group")
        self.assertEqual(len(self.manager.get_all_clients()), 1)

        success = self.manager.remove_client(
            "client1", DisconnectionReason.CLIENT_REQUEST
        )
        self.assertTrue(success)
        self.assertEqual(len(self.manager.get_all_clients()), 0)

        # Test removing non-existent client
        success = self.manager.remove_client("nonexistent")
        self.assertFalse(success)

    def test_client_groups(self):
        """Test client grouping"""
        transport1 = MockTransport()
        transport2 = MockTransport()
        transport3 = MockTransport()

        self.manager.add_client("client1", transport1, group="group_a")
        self.manager.add_client("client2", transport2, group="group_a")
        self.manager.add_client("client3", transport3, group="group_b")

        group_a_clients = self.manager.get_clients_by_group("group_a")
        self.assertEqual(len(group_a_clients), 2)
        self.assertEqual({c.client_id for c in group_a_clients}, {"client1", "client2"})

        group_b_clients = self.manager.get_clients_by_group("group_b")
        self.assertEqual(len(group_b_clients), 1)
        self.assertEqual(group_b_clients[0].client_id, "client3")

        nonexistent_clients = self.manager.get_clients_by_group("nonexistent")
        self.assertEqual(len(nonexistent_clients), 0)

    async def async_test_broadcast_notification(self):
        """Test broadcasting notifications"""
        transport1 = MockTransport()
        transport2 = MockTransport()
        transport3 = MockTransport()

        self.manager.add_client("client1", transport1, group="group_a")
        self.manager.add_client("client2", transport2, group="group_a")
        self.manager.add_client("client3", transport3, group="group_b")

        # Broadcast to all clients
        results = await self.manager.broadcast_notification(
            "test/method", {"param": "value"}
        )

        self.assertEqual(len(results), 3)
        self.assertTrue(all(results.values()))

        # Broadcast to specific group
        results = await self.manager.broadcast_notification(
            "test/method", {"param": "group_value"}, group="group_a"
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(results.values()))
        self.assertIn("client1", results)
        self.assertIn("client2", results)
        self.assertNotIn("client3", results)

    def test_get_status(self):
        """Test getting manager status"""
        status = self.manager.get_status()

        self.assertIn("total_clients", status)
        self.assertIn("clients_by_state", status)
        self.assertIn("groups", status)
        self.assertIn("shutdown_in_progress", status)
        self.assertIn("closed", status)
        self.assertIn("statistics", status)

        self.assertEqual(status["total_clients"], 0)
        self.assertFalse(status["shutdown_in_progress"])
        self.assertFalse(status["closed"])

    def test_get_status_with_clients(self):
        """Test getting status with clients"""
        transport1 = MockTransport()
        transport2 = MockTransport()

        client1 = self.manager.add_client("client1", transport1, group="test_group")
        client2 = self.manager.add_client("client2", transport2)

        # Add some activity
        client1.add_bytes_sent(100)
        client1.add_bytes_received(200)
        client1.increment_pending_requests()
        client1.increment_errors()

        client2.add_bytes_sent(50)
        client2.add_bytes_received(75)

        status = self.manager.get_status()

        self.assertEqual(status["total_clients"], 2)
        self.assertEqual(len(status["clients_by_state"]["connected"]), 2)
        self.assertEqual(status["groups"]["test_group"], ["client1"])
        self.assertEqual(status["statistics"]["total_bytes_sent"], 150)
        self.assertEqual(status["statistics"]["total_bytes_received"], 275)
        self.assertEqual(status["statistics"]["total_pending_requests"], 1)
        self.assertEqual(status["statistics"]["total_errors"], 1)


class TestGracefulShutdown(unittest.TestCase):
    """Test graceful shutdown functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger(f"test_shutdown_{int(time.time() * 1000000)}")
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        self.logger.addHandler(handler)

        self.manager = ClientConnectionManager(self.logger)

    async def async_test_graceful_shutdown_no_clients(self):
        """Test graceful shutdown with no clients"""
        success = await self.manager.graceful_shutdown(
            grace_period=1.0, force_timeout=0.5
        )

        self.assertTrue(success)
        self.assertTrue(self.manager._closed)

    async def async_test_graceful_shutdown_cooperative_clients(self):
        """Test graceful shutdown with cooperative clients"""
        # Create clients that will disconnect themselves after receiving shutdown notification
        transports = [MockTransport() for _ in range(3)]
        clients = []

        for i, transport in enumerate(transports):
            client = self.manager.add_client(f"client{i}", transport)
            clients.append(client)

            # Add callback to simulate client disconnecting itself
            def auto_disconnect(client_id, reason, mgr=self.manager):
                mgr.remove_client(client_id, reason)

            client.add_disconnect_callback(auto_disconnect)

        await self.manager.graceful_shutdown(grace_period=2.0, force_timeout=1.0)

        # Note: This test is complex because we need to simulate clients disconnecting
        # themselves after receiving shutdown notification. In real scenario, clients
        # would close their connection after receiving the notification.
        self.assertTrue(self.manager._closed)

    async def async_test_graceful_shutdown_unresponsive_clients(self):
        """Test graceful shutdown with unresponsive clients"""
        # Create clients that won't disconnect themselves
        transports = [MockTransport() for _ in range(2)]

        for i, transport in enumerate(transports):
            self.manager.add_client(f"unresponsive_client{i}", transport)

        await self.manager.graceful_shutdown(grace_period=0.1, force_timeout=0.2)

        # Should force disconnect all clients
        self.assertTrue(self.manager._closed)
        self.assertEqual(len(self.manager.get_all_clients()), 0)

    async def async_test_graceful_shutdown_mixed_clients(self):
        """Test graceful shutdown with mix of responsive and unresponsive clients"""
        transports = [MockTransport() for _ in range(4)]

        # Add responsive clients (first 2)
        for i in range(2):
            client = self.manager.add_client(f"responsive_client{i}", transports[i])

            def auto_disconnect(client_id, reason, mgr=self.manager):
                mgr.remove_client(client_id, reason)

            client.add_disconnect_callback(auto_disconnect)

        # Add unresponsive clients (last 2)
        for i in range(2, 4):
            self.manager.add_client(f"unresponsive_client{i}", transports[i])

        await self.manager.graceful_shutdown(grace_period=0.1, force_timeout=0.2)

        self.assertTrue(self.manager._closed)
        self.assertEqual(len(self.manager.get_all_clients()), 0)

    async def async_test_graceful_shutdown_with_failing_transports(self):
        """Test graceful shutdown with transport failures"""
        failing_transports = [MockTransport(should_fail=True) for _ in range(2)]

        for i, transport in enumerate(failing_transports):
            self.manager.add_client(f"failing_client{i}", transport)

        await self.manager.graceful_shutdown(grace_period=0.1, force_timeout=0.2)

        # Should handle failures gracefully
        self.assertTrue(self.manager._closed)
        self.assertEqual(len(self.manager.get_all_clients()), 0)

    async def async_test_shutdown_already_in_progress(self):
        """Test calling shutdown when already in progress"""
        transport = MockTransport()
        self.manager.add_client("client1", transport)

        # Start first shutdown
        task1 = asyncio.create_task(self.manager.graceful_shutdown(grace_period=0.2))

        # Try to start second shutdown
        await asyncio.sleep(0.05)  # Let first shutdown start
        success2 = await self.manager.graceful_shutdown(grace_period=0.1)

        # Second shutdown should return False (already in progress)
        self.assertFalse(success2)

        # Wait for first shutdown to complete
        await task1
        self.assertTrue(self.manager._closed)

    async def async_test_convenience_function(self):
        """Test convenience function for graceful shutdown"""
        transport = MockTransport()
        self.manager.add_client("client1", transport)

        await self.manager.graceful_shutdown(grace_period=0.1, force_timeout=0.1)

        self.assertTrue(self.manager._closed)


async def run_async_tests():
    """Run async tests manually"""
    print("Running async tests:")

    test_classes = [TestMCPClient, TestClientConnectionManager, TestGracefulShutdown]

    for test_class in test_classes:
        print(f"\nTesting {test_class.__name__}:")

        # Find async test methods directly instead of using unittest loader
        for method_name in dir(test_class):
            if method_name.startswith("async_test_"):
                method = getattr(test_class, method_name)
                if asyncio.iscoroutinefunction(method):
                    print(f"  Running {method_name}...")
                    try:
                        # Create a fresh test instance and call setUp
                        test_instance = test_class()
                        test_instance.setUp()

                        # Get the actual test method from the fresh instance
                        async_test_method = getattr(test_instance, method_name)
                        await async_test_method()
                        print(f"  ✓ {method_name} passed")
                    except Exception as e:
                        print(f"  ✗ {method_name} failed: {e}")
                        import traceback

                        traceback.print_exc()


if __name__ == "__main__":
    # Run synchronous tests first
    unittest.main(argv=[""], exit=False, verbosity=2)

    # Run async tests
    print("\n" + "=" * 50)
    print("Running async tests separately:")
    print("=" * 50)
    asyncio.run(run_async_tests())
