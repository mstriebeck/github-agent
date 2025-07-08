"""
Unit tests for LSP JSON-RPC protocol implementation.
"""

import json
import logging
from unittest.mock import Mock

import pytest

from lsp_constants import LSPErrorCode
from lsp_jsonrpc import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCProtocol,
    JSONRPCRequest,
    JSONRPCResponse,
)


class TestJSONRPCRequest:
    """Test JSON-RPC request message handling."""

    def test_request_creation(self):
        """Test creating a JSON-RPC request."""
        request = JSONRPCRequest(
            method="test_method", params={"param1": "value1"}, id="test_id"
        )

        assert request.method == "test_method"
        assert request.params == {"param1": "value1"}
        assert request.id == "test_id"
        assert request.jsonrpc == "2.0"

    def test_request_to_dict(self):
        """Test converting request to dictionary."""
        request = JSONRPCRequest(
            method="test_method", params={"param1": "value1"}, id="test_id"
        )
        result = request.to_dict()

        expected = {
            "jsonrpc": "2.0",
            "method": "test_method",
            "params": {"param1": "value1"},
            "id": "test_id",
        }
        assert result == expected

    def test_request_to_json(self):
        """Test converting request to JSON string."""
        request = JSONRPCRequest(
            method="test_method", params={"param1": "value1"}, id="test_id"
        )
        json_str = request.to_json()

        parsed = json.loads(json_str)
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["method"] == "test_method"
        assert parsed["params"] == {"param1": "value1"}
        assert parsed["id"] == "test_id"

    def test_request_without_params(self):
        """Test request without parameters."""
        request = JSONRPCRequest(method="test_method")
        result = request.to_dict()

        assert "method" in result
        assert result["method"] == "test_method"
        assert "id" in result
        # Empty params should not be included in the dict
        assert "params" not in result or result["params"] == {}

    def test_request_auto_id(self):
        """Test request with auto-generated ID."""
        request = JSONRPCRequest(method="test_method")
        assert request.id is not None
        assert isinstance(request.id, str)


class TestJSONRPCResponse:
    """Test JSON-RPC response message handling."""

    def test_response_creation(self):
        """Test creating a JSON-RPC response."""
        response = JSONRPCResponse(id="test_id", result={"result": "success"})

        assert response.id == "test_id"
        assert response.result == {"result": "success"}
        assert response.error is None
        assert response.jsonrpc == "2.0"

    def test_response_to_dict(self):
        """Test converting response to dictionary."""
        response = JSONRPCResponse(id="test_id", result={"result": "success"})
        result = response.to_dict()

        expected = {"jsonrpc": "2.0", "id": "test_id", "result": {"result": "success"}}
        assert result == expected

    def test_error_response_creation(self):
        """Test creating error response."""
        response = JSONRPCResponse.create_error(
            id="test_id",
            code=LSPErrorCode.INVALID_REQUEST,
            message="Invalid request",
            data={"details": "test"},
        )

        assert response.id == "test_id"
        assert response.result is None
        assert response.error is not None
        assert response.error["code"] == LSPErrorCode.INVALID_REQUEST.value
        assert response.error["message"] == "Invalid request"
        assert response.error["data"] == {"details": "test"}

    def test_error_response_without_data(self):
        """Test creating error response without data."""
        response = JSONRPCResponse.create_error(
            id="test_id", code=LSPErrorCode.INVALID_REQUEST, message="Invalid request"
        )

        assert response.error["code"] == LSPErrorCode.INVALID_REQUEST.value
        assert response.error["message"] == "Invalid request"
        assert "data" not in response.error


class TestJSONRPCNotification:
    """Test JSON-RPC notification message handling."""

    def test_notification_creation(self):
        """Test creating a JSON-RPC notification."""
        notification = JSONRPCNotification(
            method="test_method", params={"param1": "value1"}
        )

        assert notification.method == "test_method"
        assert notification.params == {"param1": "value1"}
        assert notification.jsonrpc == "2.0"

    def test_notification_to_dict(self):
        """Test converting notification to dictionary."""
        notification = JSONRPCNotification(
            method="test_method", params={"param1": "value1"}
        )
        result = notification.to_dict()

        expected = {
            "jsonrpc": "2.0",
            "method": "test_method",
            "params": {"param1": "value1"},
        }
        assert result == expected

    def test_notification_without_params(self):
        """Test notification without parameters."""
        notification = JSONRPCNotification(method="test_method")
        result = notification.to_dict()

        assert "method" in result
        assert result["method"] == "test_method"
        # Empty params should not be included in the dict
        assert "params" not in result or result["params"] == {}


class TestJSONRPCProtocol:
    """Test JSON-RPC protocol handler."""

    def setup_method(self):
        """Set up test fixtures."""
        self.logger = Mock(spec=logging.Logger)
        self.protocol = JSONRPCProtocol(logger=self.logger)

    def test_create_request(self):
        """Test creating a request through protocol."""
        request = self.protocol.create_request("test_method", {"param1": "value1"})

        assert isinstance(request, JSONRPCRequest)
        assert request.method == "test_method"
        assert request.params == {"param1": "value1"}
        assert request.id in self.protocol._pending_requests

    def test_create_notification(self):
        """Test creating a notification through protocol."""
        notification = self.protocol.create_notification(
            "test_method", {"param1": "value1"}
        )

        assert isinstance(notification, JSONRPCNotification)
        assert notification.method == "test_method"
        assert notification.params == {"param1": "value1"}

    def test_create_response(self):
        """Test creating a response through protocol."""
        # First create a request to have a pending request
        request = self.protocol.create_request("test_method")
        request_id = request.id

        # Create response
        response = self.protocol.create_response(request_id, {"result": "success"})

        assert isinstance(response, JSONRPCResponse)
        assert response.id == request_id
        assert response.result == {"result": "success"}
        # Request should be removed from pending
        assert request_id not in self.protocol._pending_requests

    def test_create_error_response(self):
        """Test creating an error response through protocol."""
        request = self.protocol.create_request("test_method")
        request_id = request.id

        response = self.protocol.create_error_response(
            request_id, LSPErrorCode.INVALID_REQUEST, "Invalid request"
        )

        assert isinstance(response, JSONRPCResponse)
        assert response.id == request_id
        assert response.error is not None
        assert response.error["code"] == LSPErrorCode.INVALID_REQUEST.value
        # Request should be removed from pending
        assert request_id not in self.protocol._pending_requests

    def test_serialize_message(self):
        """Test message serialization with LSP header."""
        request = JSONRPCRequest(method="test_method", id="test_id")
        serialized = self.protocol.serialize_message(request)

        assert isinstance(serialized, bytes)
        assert serialized.startswith(b"Content-Length:")
        assert b"\r\n\r\n" in serialized

        # Extract and verify content
        header_end = serialized.find(b"\r\n\r\n")
        header = serialized[:header_end].decode("utf-8")
        content = serialized[header_end + 4 :].decode("utf-8")

        assert "Content-Length:" in header
        parsed_content = json.loads(content)
        assert parsed_content["method"] == "test_method"
        assert parsed_content["id"] == "test_id"

    def test_deserialize_message(self):
        """Test message deserialization."""
        message_data = '{"jsonrpc": "2.0", "method": "test_method", "id": "test_id"}'
        deserialized = self.protocol.deserialize_message(message_data)

        assert deserialized["jsonrpc"] == "2.0"
        assert deserialized["method"] == "test_method"
        assert deserialized["id"] == "test_id"

    def test_deserialize_invalid_json(self):
        """Test deserialization with invalid JSON."""
        with pytest.raises(JSONRPCError) as exc_info:
            self.protocol.deserialize_message("invalid json")

        assert exc_info.value.code == LSPErrorCode.PARSE_ERROR

    def test_deserialize_invalid_jsonrpc_version(self):
        """Test deserialization with invalid JSON-RPC version."""
        message_data = '{"jsonrpc": "1.0", "method": "test_method"}'

        with pytest.raises(JSONRPCError) as exc_info:
            self.protocol.deserialize_message(message_data)

        assert exc_info.value.code == LSPErrorCode.INVALID_REQUEST

    def test_parse_lsp_message(self):
        """Test parsing LSP message with header."""
        content = '{"jsonrpc": "2.0", "method": "test_method"}'
        content_bytes = content.encode("utf-8")
        message = f"Content-Length: {len(content_bytes)}\r\n\r\n{content}".encode()

        headers, parsed_content = self.protocol.parse_lsp_message(message)

        assert headers["Content-Length"] == str(len(content_bytes))
        assert parsed_content == content

    def test_parse_lsp_message_with_content_type(self):
        """Test parsing LSP message with Content-Type header."""
        content = '{"jsonrpc": "2.0", "method": "test_method"}'
        content_bytes = content.encode("utf-8")
        message = f"Content-Length: {len(content_bytes)}\r\nContent-Type: application/json\r\n\r\n{content}".encode()

        headers, parsed_content = self.protocol.parse_lsp_message(message)

        assert headers["Content-Length"] == str(len(content_bytes))
        assert headers["Content-Type"] == "application/json"
        assert parsed_content == content

    def test_parse_lsp_message_invalid_format(self):
        """Test parsing LSP message with invalid format."""
        with pytest.raises(JSONRPCError) as exc_info:
            self.protocol.parse_lsp_message(b"invalid message format")

        assert exc_info.value.code == LSPErrorCode.PARSE_ERROR

    def test_parse_lsp_message_missing_content_length(self):
        """Test parsing LSP message without Content-Length header."""
        message = b"Content-Type: application/json\r\n\r\n{}"

        with pytest.raises(JSONRPCError) as exc_info:
            self.protocol.parse_lsp_message(message)

        assert exc_info.value.code == LSPErrorCode.PARSE_ERROR

    def test_parse_lsp_message_length_mismatch(self):
        """Test parsing LSP message with content length mismatch."""
        content = '{"jsonrpc": "2.0"}'
        message = f"Content-Length: 100\r\n\r\n{content}".encode()

        with pytest.raises(JSONRPCError) as exc_info:
            self.protocol.parse_lsp_message(message)

        assert exc_info.value.code == LSPErrorCode.PARSE_ERROR

    def test_message_type_detection(self):
        """Test message type detection."""
        request = {"jsonrpc": "2.0", "method": "test", "id": "1"}
        response = {"jsonrpc": "2.0", "id": "1", "result": {}}
        notification = {"jsonrpc": "2.0", "method": "test"}

        assert self.protocol.is_request(request)
        assert not self.protocol.is_response(request)
        assert not self.protocol.is_notification(request)

        assert not self.protocol.is_request(response)
        assert self.protocol.is_response(response)
        assert not self.protocol.is_notification(response)

        assert not self.protocol.is_request(notification)
        assert not self.protocol.is_response(notification)
        assert self.protocol.is_notification(notification)

    def test_pending_request_management(self):
        """Test pending request management."""
        request = self.protocol.create_request("test_method")
        request_id = request.id

        # Request should be in pending
        assert self.protocol.get_pending_request(request_id) == request
        assert self.protocol.get_pending_request_count() == 1

        # Cancel request
        cancelled = self.protocol.cancel_request(request_id)
        assert cancelled == request
        assert self.protocol.get_pending_request(request_id) is None
        assert self.protocol.get_pending_request_count() == 0

    def test_clear_pending_requests(self):
        """Test clearing all pending requests."""
        self.protocol.create_request("test_method1")
        self.protocol.create_request("test_method2")

        assert self.protocol.get_pending_request_count() == 2

        self.protocol.clear_pending_requests()
        assert self.protocol.get_pending_request_count() == 0

    def test_validate_request(self):
        """Test request validation."""
        valid_request = {"jsonrpc": "2.0", "method": "test", "id": "1"}
        valid_notification = {
            "jsonrpc": "2.0",
            "method": "test",
        }  # Notification without ID is valid
        invalid_request1 = {
            "jsonrpc": "1.0",
            "method": "test",
            "id": "1",
        }  # Wrong version
        invalid_request2 = {"jsonrpc": "2.0", "id": "1"}  # Missing method

        assert self.protocol.validate_request(valid_request)
        assert self.protocol.validate_request(valid_notification)
        assert not self.protocol.validate_request(invalid_request1)
        assert not self.protocol.validate_request(invalid_request2)

    def test_validate_response(self):
        """Test response validation."""
        valid_response1 = {"jsonrpc": "2.0", "id": "1", "result": {}}
        valid_response2 = {
            "jsonrpc": "2.0",
            "id": "1",
            "error": {"code": -1, "message": "error"},
        }
        invalid_response1 = {"jsonrpc": "1.0", "id": "1", "result": {}}  # Wrong version
        invalid_response2 = {"jsonrpc": "2.0", "result": {}}  # Missing id
        invalid_response3 = {"jsonrpc": "2.0", "id": "1"}  # Missing result and error
        invalid_response4 = {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {},
            "error": {},
        }  # Both result and error

        assert self.protocol.validate_response(valid_response1)
        assert self.protocol.validate_response(valid_response2)
        assert not self.protocol.validate_response(invalid_response1)
        assert not self.protocol.validate_response(invalid_response2)
        assert not self.protocol.validate_response(invalid_response3)
        assert not self.protocol.validate_response(invalid_response4)


class TestJSONRPCError:
    """Test JSON-RPC error handling."""

    def test_error_creation(self):
        """Test creating JSON-RPC error."""
        error = JSONRPCError(
            code=LSPErrorCode.INVALID_REQUEST,
            message="Invalid request",
            data={"details": "test"},
        )

        assert error.code == LSPErrorCode.INVALID_REQUEST
        assert error.message == "Invalid request"
        assert error.data == {"details": "test"}
        assert "JSON-RPC Error -32600" in str(error)

    def test_error_without_data(self):
        """Test creating JSON-RPC error without data."""
        error = JSONRPCError(
            code=LSPErrorCode.INVALID_REQUEST, message="Invalid request"
        )

        assert error.code == LSPErrorCode.INVALID_REQUEST
        assert error.message == "Invalid request"
        assert error.data is None
