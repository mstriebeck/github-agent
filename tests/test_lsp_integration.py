"""
Integration tests for LSP client with mock server.
"""

import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import Mock

import pytest

from lsp_client import (
    AbstractLSPClient,
    LSPClientState,
    LSPCommunicationMode,
    LSPServerManager,
)
from lsp_constants import LSPMethod


class MockLSPServer:
    """Mock LSP server for integration testing."""

    def __init__(self):
        self.process = None
        self.responses = {}
        self.notifications = []
        self.requests = []
        self.initialized = False
        self.shutdown_received = False

    def set_response(self, method, response):
        """Set a response for a specific method."""
        self.responses[method] = response

    def run_server(self):
        """Run the mock LSP server."""
        try:
            while True:
                # Read message from stdin
                line = sys.stdin.readline()
                if not line:
                    break

                if line.startswith("Content-Length:"):
                    content_length = int(line.split(":")[1].strip())
                    # Read the empty line
                    sys.stdin.readline()
                    # Read the content
                    content = sys.stdin.read(content_length)

                    try:
                        message = json.loads(content)
                        response = self.handle_message(message)
                        if response:
                            self.send_response(response)
                    except json.JSONDecodeError:
                        pass

        except KeyboardInterrupt:
            pass
        except EOFError:
            pass

    def handle_message(self, message):
        """Handle incoming message."""
        method = message.get("method")
        message_id = message.get("id")

        if method == "initialize":
            self.initialized = True
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "capabilities": {
                        "textDocumentSync": 2,
                        "definitionProvider": True,
                        "referencesProvider": True,
                        "hoverProvider": True,
                        "documentSymbolProvider": True,
                    },
                    "serverInfo": {"name": "mock-lsp-server", "version": "1.0.0"},
                },
            }

        elif method == "initialized":
            # Just acknowledge
            return None

        elif method == "shutdown":
            self.shutdown_received = True
            return {"jsonrpc": "2.0", "id": message_id, "result": None}

        elif method == "exit":
            sys.exit(0)

        elif method in self.responses:
            response = self.responses[method]
            if callable(response):
                return response(message)
            else:
                return {"jsonrpc": "2.0", "id": message_id, "result": response}

        else:
            # Unknown method
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

    def send_response(self, response):
        """Send response to client."""
        content = json.dumps(response)
        content_bytes = content.encode("utf-8")
        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
        sys.stdout.write(header)
        sys.stdout.write(content)
        sys.stdout.flush()


class MockLSPServerManager(LSPServerManager):
    """Mock LSP server manager for integration testing."""

    def __init__(self, server_script_path):
        self.server_script_path = server_script_path

    def get_server_command(self):
        return [sys.executable, self.server_script_path]

    def get_server_args(self):
        return []

    def get_communication_mode(self):
        return LSPCommunicationMode.STDIO

    def get_server_capabilities(self):
        return {}

    def get_initialization_options(self):
        return None

    def validate_server_response(self, response):
        return "capabilities" in response


class IntegrationTestLSPClient(AbstractLSPClient):
    """LSP client implementation for integration testing."""

    async def get_definition(self, uri, line, character):
        """Get definition using LSP."""
        request = self.protocol.create_request(
            LSPMethod.DEFINITION,
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        )

        response = await self._send_request(request)
        if response and "result" in response:
            return response["result"]
        return None

    async def get_references(self, uri, line, character, include_declaration=True):
        """Get references using LSP."""
        request = self.protocol.create_request(
            LSPMethod.REFERENCES,
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration},
            },
        )

        response = await self._send_request(request)
        if response and "result" in response:
            return response["result"]
        return None

    async def get_hover(self, uri, line, character):
        """Get hover information using LSP."""
        request = self.protocol.create_request(
            LSPMethod.HOVER,
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        )

        response = await self._send_request(request)
        if response and "result" in response:
            return response["result"]
        return None

    async def get_document_symbols(self, uri):
        """Get document symbols using LSP."""
        request = self.protocol.create_request(
            LSPMethod.DOCUMENT_SYMBOLS, {"textDocument": {"uri": uri}}
        )

        response = await self._send_request(request)
        if response and "result" in response:
            return response["result"]
        return None


@pytest.fixture
def mock_server_script():
    """Create a mock LSP server script."""
    script_content = """
import sys
import json

class MockLSPServer:
    def __init__(self):
        self.initialized = False
        self.shutdown_received = False

    def run_server(self):
        try:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break

                if line.startswith("Content-Length:"):
                    content_length = int(line.split(":")[1].strip())
                    sys.stdin.readline()  # Empty line
                    content = sys.stdin.read(content_length)

                    try:
                        message = json.loads(content)
                        response = self.handle_message(message)
                        if response:
                            self.send_response(response)
                    except json.JSONDecodeError:
                        pass
        except (KeyboardInterrupt, EOFError):
            pass

    def handle_message(self, message):
        method = message.get("method")
        message_id = message.get("id")

        if method == "initialize":
            self.initialized = True
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "capabilities": {
                        "textDocumentSync": 2,
                        "definitionProvider": True,
                        "referencesProvider": True,
                        "hoverProvider": True,
                        "documentSymbolProvider": True
                    },
                    "serverInfo": {
                        "name": "mock-lsp-server",
                        "version": "1.0.0"
                    }
                }
            }
        elif method == "initialized":
            return None
        elif method == "shutdown":
            self.shutdown_received = True
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": None
            }
        elif method == "exit":
            sys.exit(0)
        elif method == "textDocument/definition":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": [{
                    "uri": "file:///test.py",
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 10}
                    }
                }]
            }
        elif method == "textDocument/references":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": [{
                    "uri": "file:///test.py",
                    "range": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 1, "character": 10}
                    }
                }]
            }
        elif method == "textDocument/hover":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "contents": {
                        "kind": "markdown",
                        "value": "Mock hover information"
                    }
                }
            }
        elif method == "textDocument/documentSymbol":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": [{
                    "name": "mock_function",
                    "kind": 12,
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 5, "character": 0}
                    },
                    "selectionRange": {
                        "start": {"line": 0, "character": 4},
                        "end": {"line": 0, "character": 17}
                    }
                }]
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

    def send_response(self, response):
        content = json.dumps(response)
        content_bytes = content.encode('utf-8')
        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
        sys.stdout.buffer.write(header.encode('utf-8'))
        sys.stdout.buffer.write(content_bytes)
        sys.stdout.buffer.flush()

if __name__ == "__main__":
    server = MockLSPServer()
    server.run_server()
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script_content)
        f.flush()
        yield f.name

    os.unlink(f.name)


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def lsp_client(mock_server_script, temp_workspace):
    """Create an LSP client with mock server."""
    server_manager = MockLSPServerManager(mock_server_script)
    logger = Mock()
    client = IntegrationTestLSPClient(
        server_manager=server_manager, workspace_root=temp_workspace, logger=logger
    )
    return client


class TestLSPIntegration:
    """Integration tests for LSP client with mock server."""

    @pytest.mark.asyncio
    async def test_full_initialization_sequence(self, lsp_client):
        """Test complete initialization sequence."""
        # Start the client
        success = await lsp_client.start()

        assert success is True
        assert lsp_client.is_initialized() is True
        assert lsp_client.state == LSPClientState.INITIALIZED

        # Check server capabilities
        capabilities = lsp_client.get_server_capabilities()
        assert "definitionProvider" in capabilities
        assert "referencesProvider" in capabilities
        assert "hoverProvider" in capabilities
        assert "documentSymbolProvider" in capabilities

        # Clean up
        await lsp_client.stop()
        assert lsp_client.state == LSPClientState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_definition_request(self, lsp_client):
        """Test definition request."""
        await lsp_client.start()

        result = await lsp_client.get_definition("file:///test.py", 10, 5)

        assert result is not None
        assert len(result) == 1
        assert result[0]["uri"] == "file:///test.py"
        assert "range" in result[0]

        await lsp_client.stop()

    @pytest.mark.asyncio
    async def test_references_request(self, lsp_client):
        """Test references request."""
        await lsp_client.start()

        result = await lsp_client.get_references("file:///test.py", 10, 5)

        assert result is not None
        assert len(result) == 1
        assert result[0]["uri"] == "file:///test.py"
        assert "range" in result[0]

        await lsp_client.stop()

    @pytest.mark.asyncio
    async def test_hover_request(self, lsp_client):
        """Test hover request."""
        await lsp_client.start()

        result = await lsp_client.get_hover("file:///test.py", 10, 5)

        assert result is not None
        assert "contents" in result
        assert result["contents"]["kind"] == "markdown"
        assert "Mock hover information" in result["contents"]["value"]

        await lsp_client.stop()

    @pytest.mark.asyncio
    async def test_document_symbols_request(self, lsp_client):
        """Test document symbols request."""
        await lsp_client.start()

        result = await lsp_client.get_document_symbols("file:///test.py")

        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "mock_function"
        assert result[0]["kind"] == 12
        assert "range" in result[0]

        await lsp_client.stop()

    @pytest.mark.asyncio
    async def test_server_start_failure(self, temp_workspace):
        """Test handling of server start failure."""

        # Create a server manager with non-existent command
        class FailingServerManager(LSPServerManager):
            def get_server_command(self):
                return ["non_existent_command"]

            def get_server_args(self):
                return []

            def get_communication_mode(self):
                return LSPCommunicationMode.STDIO

            def get_server_capabilities(self):
                return {}

            def get_initialization_options(self):
                return None

            def validate_server_response(self, response):
                return True

        server_manager = FailingServerManager()
        logger = Mock()
        client = IntegrationTestLSPClient(
            server_manager=server_manager, workspace_root=temp_workspace, logger=logger
        )

        success = await client.start()

        assert success is False
        assert client.state == LSPClientState.ERROR
        logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_request_timeout(self, lsp_client):
        """Test request timeout handling."""
        await lsp_client.start()

        # Send a request that the mock server doesn't handle
        request = lsp_client.protocol.create_request("unknown/method", {})
        result = await lsp_client._send_request(request, timeout=0.1)

        # Should timeout since server will send error, not result
        assert result is not None  # Will get error response
        assert "error" in result

        await lsp_client.stop()

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, lsp_client):
        """Test handling concurrent requests."""
        await lsp_client.start()

        # Send multiple requests concurrently
        tasks = [
            lsp_client.get_definition("file:///test.py", 10, 5),
            lsp_client.get_references("file:///test.py", 10, 5),
            lsp_client.get_hover("file:///test.py", 10, 5),
            lsp_client.get_document_symbols("file:///test.py"),
        ]

        results = await asyncio.gather(*tasks)

        # All requests should succeed
        assert all(result is not None for result in results)

        await lsp_client.stop()

    @pytest.mark.asyncio
    async def test_notification_handling(self, lsp_client):
        """Test handling server notifications."""
        notifications_received = []

        async def notification_handler(message):
            notifications_received.append(message)

        lsp_client.add_notification_handler("test/notification", notification_handler)

        await lsp_client.start()

        # Simulate processing a notification
        notification_message = {
            "jsonrpc": "2.0",
            "method": "test/notification",
            "params": {"message": "test"},
        }

        await lsp_client._handle_notification(notification_message)

        assert len(notifications_received) == 1
        assert notifications_received[0]["params"]["message"] == "test"

        await lsp_client.stop()

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, lsp_client):
        """Test graceful shutdown sequence."""
        await lsp_client.start()

        assert lsp_client.state == LSPClientState.INITIALIZED
        assert lsp_client.server_process is not None

        await lsp_client.stop()

        assert lsp_client.state == LSPClientState.DISCONNECTED
        assert lsp_client.server_process is None

    @pytest.mark.asyncio
    async def test_error_recovery(self, lsp_client):
        """Test error recovery mechanisms."""
        await lsp_client.start()

        # Test that client can handle malformed responses
        malformed_content = "invalid json"

        # This should not crash the client
        await lsp_client._process_message(malformed_content)

        # Client should still be functional
        assert lsp_client.is_initialized()

        # Should still be able to make requests
        result = await lsp_client.get_definition("file:///test.py", 10, 5)
        assert result is not None

        await lsp_client.stop()

    @pytest.mark.asyncio
    async def test_message_reader_thread(self, lsp_client):
        """Test message reader thread functionality."""
        await lsp_client.start()

        # The reader thread should be running
        assert lsp_client._reader_thread is not None
        assert lsp_client._reader_thread.is_alive()

        # Make a request to ensure thread is processing messages
        result = await lsp_client.get_definition("file:///test.py", 10, 5)
        assert result is not None

        await lsp_client.stop()

        # Thread should have stopped
        assert not lsp_client._reader_thread.is_alive()
