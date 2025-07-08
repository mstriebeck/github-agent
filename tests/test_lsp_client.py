"""
Unit tests for LSP client infrastructure.
"""

import json
import subprocess
import threading
from unittest.mock import AsyncMock, Mock, patch

import pytest

from lsp_client import (
    AbstractLSPClient,
    LSPClientState,
    LSPCommunicationMode,
    LSPServerManager,
)
from lsp_constants import LSPMethod


class MockLSPServerManager(LSPServerManager):
    """Mock LSP server manager for testing."""

    def __init__(self):
        self.server_command = ["python", "-m", "mock_server"]
        self.server_args = []
        self.communication_mode = LSPCommunicationMode.STDIO
        self.server_capabilities = {}
        self.initialization_options = None

    def get_server_command(self):
        return self.server_command

    def get_server_args(self):
        return self.server_args

    def get_communication_mode(self):
        return self.communication_mode

    def get_server_capabilities(self):
        return self.server_capabilities

    def get_initialization_options(self):
        return self.initialization_options

    def validate_server_response(self, response):
        return True


class TestLSPClient(AbstractLSPClient):
    """Test implementation of AbstractLSPClient."""

    async def get_definition(self, uri, line, character):
        """Mock implementation."""
        return [
            {"uri": uri, "range": {"start": {"line": line, "character": character}}}
        ]

    async def get_references(self, uri, line, character, include_declaration=True):
        """Mock implementation."""
        return [
            {"uri": uri, "range": {"start": {"line": line, "character": character}}}
        ]

    async def get_hover(self, uri, line, character):
        """Mock implementation."""
        return {"contents": {"value": "Mock hover info"}}

    async def get_document_symbols(self, uri):
        """Mock implementation."""
        return [{"name": "mock_symbol", "kind": 12}]


class TestLSPClientState:
    """Test LSP client state management."""

    def test_client_state_enum(self):
        """Test client state enum values."""
        assert LSPClientState.DISCONNECTED.value == "disconnected"
        assert LSPClientState.CONNECTING.value == "connecting"
        assert LSPClientState.INITIALIZING.value == "initializing"
        assert LSPClientState.INITIALIZED.value == "initialized"
        assert LSPClientState.SHUTTING_DOWN.value == "shutting_down"
        assert LSPClientState.ERROR.value == "error"


class TestLSPServerManager:
    """Test LSP server manager interface."""

    def test_mock_server_manager(self):
        """Test mock server manager implementation."""
        manager = MockLSPServerManager()

        assert manager.get_server_command() == ["python", "-m", "mock_server"]
        assert manager.get_server_args() == []
        assert manager.get_communication_mode() == LSPCommunicationMode.STDIO
        assert manager.get_server_capabilities() == {}
        assert manager.get_initialization_options() is None
        assert manager.validate_server_response({}) is True


class TestAbstractLSPClient:
    """Test abstract LSP client implementation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.server_manager = MockLSPServerManager()
        self.workspace_root = "/test/workspace"
        self.logger = Mock()
        self.client = TestLSPClient(
            server_manager=self.server_manager,
            workspace_root=self.workspace_root,
            logger=self.logger,
        )

    def test_client_initialization(self):
        """Test client initialization."""
        assert self.client.server_manager == self.server_manager
        assert self.client.workspace_root == self.workspace_root
        assert self.client.logger == self.logger
        assert self.client.state == LSPClientState.DISCONNECTED
        assert self.client.server_process is None
        assert self.client.server_capabilities == {}
        assert self.client.communication_mode == LSPCommunicationMode.STDIO

    def test_builtin_handlers_setup(self):
        """Test built-in handlers are set up."""
        assert LSPMethod.PUBLISH_DIAGNOSTICS in self.client._notification_handlers
        assert LSPMethod.SHOW_MESSAGE in self.client._notification_handlers
        assert LSPMethod.LOG_MESSAGE in self.client._notification_handlers
        assert "workspace/configuration" in self.client._message_handlers
        assert "window/showMessageRequest" in self.client._message_handlers

    def test_is_initialized(self):
        """Test is_initialized method."""
        assert not self.client.is_initialized()

        self.client.state = LSPClientState.INITIALIZED
        assert self.client.is_initialized()

    def test_get_server_capabilities(self):
        """Test get_server_capabilities method."""
        test_capabilities = {"textDocumentSync": 2}
        self.client.server_capabilities = test_capabilities

        capabilities = self.client.get_server_capabilities()
        assert capabilities == test_capabilities
        # Should return a copy, not the original
        assert capabilities is not self.client.server_capabilities

    def test_notification_handler_management(self):
        """Test adding and removing notification handlers."""
        handler = Mock()
        self.client.add_notification_handler("test/notification", handler)

        assert "test/notification" in self.client._notification_handlers
        assert self.client._notification_handlers["test/notification"] == handler

        self.client.remove_notification_handler("test/notification")
        assert "test/notification" not in self.client._notification_handlers

    @pytest.mark.asyncio
    @patch("subprocess.Popen")
    async def test_start_server_success(self, mock_popen):
        """Test successful server start."""
        mock_process = Mock()
        mock_process.poll.return_value = None  # Process is running
        mock_popen.return_value = mock_process

        result = await self.client._start_server()

        assert result is True
        assert self.client.server_process == mock_process
        mock_popen.assert_called_once()

    @pytest.mark.asyncio
    @patch("subprocess.Popen")
    async def test_start_server_failure(self, mock_popen):
        """Test server start failure."""
        mock_process = Mock()
        mock_process.poll.return_value = 1  # Process exited with error
        mock_process.stderr.read.return_value = b"Server error"
        mock_popen.return_value = mock_process

        result = await self.client._start_server()

        assert result is False
        self.logger.error.assert_called()

    @pytest.mark.asyncio
    @patch("subprocess.Popen")
    async def test_start_server_exception(self, mock_popen):
        """Test server start with exception."""
        mock_popen.side_effect = Exception("Failed to start")

        result = await self.client._start_server()

        assert result is False
        self.logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_send_message(self):
        """Test sending message to server."""
        mock_process = Mock()
        mock_stdin = Mock()
        mock_process.stdin = mock_stdin
        self.client.server_process = mock_process

        from lsp_jsonrpc import JSONRPCNotification

        notification = JSONRPCNotification("test/method", {"param": "value"})

        await self.client._send_message(notification)

        mock_stdin.write.assert_called_once()
        mock_stdin.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_no_server(self):
        """Test sending message when no server connection."""
        from lsp_jsonrpc import JSONRPCNotification

        notification = JSONRPCNotification("test/method")

        await self.client._send_message(notification)

        self.logger.error.assert_called_with(
            "Cannot send message: no server connection"
        )

    @pytest.mark.asyncio
    async def test_send_message_exception(self):
        """Test sending message with exception."""
        mock_process = Mock()
        mock_stdin = Mock()
        mock_stdin.write.side_effect = Exception("Write error")
        mock_process.stdin = mock_stdin
        self.client.server_process = mock_process

        from lsp_jsonrpc import JSONRPCNotification

        notification = JSONRPCNotification("test/method")

        await self.client._send_message(notification)

        self.logger.error.assert_called_with("Error sending message: Write error")

    @pytest.mark.asyncio
    async def test_send_request(self):
        """Test sending request and waiting for response."""
        # Mock successful response
        mock_response = {"jsonrpc": "2.0", "id": "test_id", "result": {"success": True}}

        from lsp_jsonrpc import JSONRPCRequest

        request = JSONRPCRequest("test/method", message_id="test_id")

        # Mock _send_message to simulate response
        async def mock_send_message(msg):
            # Simulate response handler being called
            handler = self.client._response_handlers.get("test_id")
            if handler:
                await handler(mock_response)

        self.client._send_message = mock_send_message  # type: ignore[method-assign]

        result = await self.client._send_request(request)

        assert result == mock_response

    @pytest.mark.asyncio
    async def test_send_request_timeout(self):
        """Test request timeout."""
        from lsp_jsonrpc import JSONRPCRequest

        request = JSONRPCRequest("test/method", message_id="test_id")

        # Mock _send_message to not call response handler
        self.client._send_message = AsyncMock()  # type: ignore[method-assign]

        result = await self.client._send_request(request, timeout=0.1)

        assert result is None
        self.logger.error.assert_called_with("Request timeout: test/method")

    @pytest.mark.asyncio
    async def test_process_message_response(self):
        """Test processing response message."""
        response_handler = AsyncMock()
        self.client._response_handlers["test_id"] = response_handler

        message_content = json.dumps(
            {"jsonrpc": "2.0", "id": "test_id", "result": {"success": True}}
        )

        await self.client._process_message(message_content)

        response_handler.assert_called_once()
        assert "test_id" not in self.client._response_handlers

    @pytest.mark.asyncio
    async def test_process_message_notification(self):
        """Test processing notification message."""
        notification_handler = AsyncMock()
        self.client._notification_handlers["test/notification"] = notification_handler

        message_content = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "test/notification",
                "params": {"message": "test"},
            }
        )

        await self.client._process_message(message_content)

        notification_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_request(self):
        """Test processing request message."""
        request_handler = AsyncMock()
        request_handler.return_value = None
        self.client._message_handlers["test/request"] = request_handler

        message_content = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "test/request",
                "id": "test_id",
                "params": {"param": "value"},
            }
        )

        await self.client._process_message(message_content)

        request_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_invalid_json(self):
        """Test processing invalid JSON message."""
        await self.client._process_message("invalid json")

        self.logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_handle_response_no_handler(self):
        """Test handling response with no registered handler."""
        message = {"jsonrpc": "2.0", "id": "unknown_id", "result": {"success": True}}

        await self.client._handle_response(message)

        self.logger.warning.assert_called_with("No handler for response ID: unknown_id")

    @pytest.mark.asyncio
    async def test_handle_request_no_handler(self):
        """Test handling request with no registered handler."""
        message = {"jsonrpc": "2.0", "method": "unknown/method", "id": "test_id"}

        # Mock _send_message to capture error response
        sent_messages = []

        async def mock_send_message(msg):
            sent_messages.append(msg)

        self.client._send_message = mock_send_message  # type: ignore[method-assign]

        await self.client._handle_request(message)

        assert len(sent_messages) == 1
        error_response = sent_messages[0]
        assert error_response.id == "test_id"
        assert error_response.error is not None
        assert error_response.error["code"] == -32601  # Method not found

    @pytest.mark.asyncio
    async def test_handle_notification_no_handler(self):
        """Test handling notification with no registered handler."""
        message = {
            "jsonrpc": "2.0",
            "method": "unknown/notification",
            "params": {"param": "value"},
        }

        await self.client._handle_notification(message)

        self.logger.debug.assert_called_with(
            "No handler for notification method: unknown/notification"
        )

    @pytest.mark.asyncio
    async def test_builtin_handlers(self):
        """Test built-in message handlers."""
        # Test publish diagnostics handler
        diagnostics_message = {
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": "file:///test.py",
                "diagnostics": [
                    {
                        "message": "Error",
                        "range": {"start": {"line": 0, "character": 0}},
                    }
                ],
            },
        }

        await self.client._handle_publish_diagnostics(diagnostics_message)
        self.logger.debug.assert_called()

        # Test show message handler
        show_message = {
            "jsonrpc": "2.0",
            "method": "window/showMessage",
            "params": {"type": 1, "message": "Test message"},
        }

        await self.client._handle_show_message(show_message)
        self.logger.info.assert_called_with("Server message: Test message")

        # Test log message handler
        log_message = {
            "jsonrpc": "2.0",
            "method": "window/logMessage",
            "params": {"type": 3, "message": "Test log"},
        }

        await self.client._handle_log_message(log_message)
        self.logger.debug.assert_called_with("Server log: Test log")

    @pytest.mark.asyncio
    async def test_workspace_configuration_handler(self):
        """Test workspace configuration request handler."""
        config_request = {
            "jsonrpc": "2.0",
            "method": "workspace/configuration",
            "id": "config_id",
            "params": {"items": [{"section": "python"}]},
        }

        response = await self.client._handle_workspace_configuration(config_request)

        assert response is not None
        assert response.id == "config_id"
        assert response.result == {}

    @pytest.mark.asyncio
    async def test_show_message_request_handler(self):
        """Test show message request handler."""
        show_request = {
            "jsonrpc": "2.0",
            "method": "window/showMessageRequest",
            "id": "show_id",
            "params": {"type": 1, "message": "Test", "actions": [{"title": "OK"}]},
        }

        response = await self.client._handle_show_message_request(show_request)

        assert response is not None
        assert response.id == "show_id"
        assert response.result is None

    @pytest.mark.asyncio
    @patch("subprocess.Popen")
    async def test_stop_with_graceful_shutdown(self, mock_popen):
        """Test stopping client with graceful shutdown."""
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = 0
        mock_process.stdin = Mock()
        mock_popen.return_value = mock_process

        # Set up client state
        self.client.server_process = mock_process
        self.client.state = LSPClientState.INITIALIZED
        self.client._stop_event = threading.Event()

        # Mock _send_message
        self.client._send_message = AsyncMock()  # type: ignore[method-assign]

        await self.client.stop()

        assert self.client.state == LSPClientState.DISCONNECTED
        assert self.client.server_process is None
        self.client._send_message.assert_called()  # Should send exit notification

    @pytest.mark.asyncio
    @patch("subprocess.Popen")
    async def test_stop_with_force_termination(self, mock_popen):
        """Test stopping client with force termination."""
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), 0]
        mock_process.stdin = Mock()
        mock_popen.return_value = mock_process

        # Set up client state
        self.client.server_process = mock_process
        self.client.state = LSPClientState.INITIALIZED
        self.client._stop_event = threading.Event()

        # Mock _send_message
        self.client._send_message = AsyncMock()  # type: ignore[method-assign]

        await self.client.stop()

        assert self.client.state == LSPClientState.DISCONNECTED
        assert self.client.server_process is None
        mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    @patch("subprocess.Popen")
    async def test_stop_with_kill(self, mock_popen):
        """Test stopping client with kill."""
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        mock_process.stdin = Mock()
        mock_popen.return_value = mock_process

        # Set up client state
        self.client.server_process = mock_process
        self.client.state = LSPClientState.INITIALIZED
        self.client._stop_event = threading.Event()

        # Mock _send_message
        self.client._send_message = AsyncMock()  # type: ignore[method-assign]

        await self.client.stop()

        assert self.client.state == LSPClientState.DISCONNECTED
        assert self.client.server_process is None
        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_abstract_methods_implemented(self):
        """Test that abstract methods are implemented in test client."""
        # Test that all abstract methods are implemented
        result = await self.client.get_definition("file:///test.py", 10, 5)
        assert result is not None

        result = await self.client.get_references("file:///test.py", 10, 5)
        assert result is not None

        result = await self.client.get_hover("file:///test.py", 10, 5)
        assert result is not None

        result = await self.client.get_document_symbols("file:///test.py")
        assert result is not None


class TestLSPCommunicationMode:
    """Test LSP communication mode enum."""

    def test_communication_mode_values(self):
        """Test communication mode enum values."""
        assert LSPCommunicationMode.STDIO.value == "stdio"
        assert LSPCommunicationMode.TCP.value == "tcp"
