"""
JSON-RPC 2.0 Protocol Implementation for LSP

This module implements the JSON-RPC 2.0 protocol as required by LSP,
handling message serialization, deserialization, and protocol compliance.
"""

import json
import logging
import uuid
from typing import Any

from lsp_constants import (
    JsonRPCMessage,
    LSPErrorCode,
)


class JSONRPCError(Exception):
    """Exception for JSON-RPC protocol errors."""

    def __init__(self, code: LSPErrorCode, message: str, data: Any | None = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC Error {code.value}: {message}")


class JSONRPCMessage:
    """Base class for JSON-RPC messages."""

    def __init__(self, jsonrpc: str = "2.0"):
        self.jsonrpc = jsonrpc

    def to_dict(self) -> dict[str, Any]:
        """Convert message to dictionary."""
        raise NotImplementedError

    def to_json(self) -> str:
        """Convert message to JSON string."""
        return json.dumps(self.to_dict(), separators=(",", ":"))


class JSONRPCRequest(JSONRPCMessage):
    """JSON-RPC request message."""

    def __init__(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        message_id: str | int | None = None,
    ):
        super().__init__()
        self.method = method
        self.params = params or {}
        self.id = message_id or str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        """Convert request to dictionary."""
        result: dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
            "id": self.id,
        }
        if self.params:
            result["params"] = self.params
        return result


class JSONRPCNotification(JSONRPCMessage):
    """JSON-RPC notification message (no response expected)."""

    def __init__(self, method: str, params: dict[str, Any] | None = None):
        super().__init__()
        self.method = method
        self.params = params or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert notification to dictionary."""
        result: dict[str, Any] = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params:
            result["params"] = self.params
        return result


class JSONRPCResponse(JSONRPCMessage):
    """JSON-RPC response message."""

    def __init__(
        self,
        message_id: str | int,
        result: Any | None = None,
        error: dict[str, Any] | None = None,
    ):
        super().__init__()
        self.id = message_id
        self.result = result
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Convert response to dictionary."""
        result: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            result["error"] = self.error
        else:
            result["result"] = self.result
        return result

    @classmethod
    def create_error(
        cls,
        message_id: str | int,
        code: LSPErrorCode,
        message: str,
        data: Any | None = None,
    ) -> "JSONRPCResponse":
        """Create an error response."""
        error = {"code": code.value, "message": message}
        if data is not None:
            error["data"] = data
        return cls(message_id=message_id, error=error)


class JSONRPCProtocol:
    """JSON-RPC 2.0 protocol handler for LSP communication."""

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(__name__)
        self._pending_requests: dict[str | int, JSONRPCRequest] = {}

    def create_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> JSONRPCRequest:
        """Create a new JSON-RPC request."""
        request = JSONRPCRequest(method=method, params=params)
        self._pending_requests[request.id] = request
        return request

    def create_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> JSONRPCNotification:
        """Create a new JSON-RPC notification."""
        return JSONRPCNotification(method=method, params=params)

    def create_response(self, message_id: str | int, result: Any) -> JSONRPCResponse:
        """Create a successful JSON-RPC response."""
        # Remove from pending requests if it exists
        self._pending_requests.pop(message_id, None)
        return JSONRPCResponse(message_id=message_id, result=result)

    def create_error_response(
        self,
        message_id: str | int,
        code: LSPErrorCode,
        message: str,
        data: Any | None = None,
    ) -> JSONRPCResponse:
        """Create an error JSON-RPC response."""
        # Remove from pending requests if it exists
        self._pending_requests.pop(message_id, None)
        return JSONRPCResponse.create_error(
            message_id=message_id, code=code, message=message, data=data
        )

    def serialize_message(self, message: JSONRPCMessage) -> bytes:
        """Serialize a JSON-RPC message to bytes with LSP header."""
        content = message.to_json()
        content_bytes = content.encode("utf-8")
        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
        return header.encode("utf-8") + content_bytes

    def deserialize_message(self, data: str) -> JsonRPCMessage:
        """Deserialize JSON-RPC message from string."""
        try:
            message = json.loads(data)
        except json.JSONDecodeError as e:
            raise JSONRPCError(LSPErrorCode.PARSE_ERROR, f"Invalid JSON: {e}") from e

        # Validate JSON-RPC version
        if message.get("jsonrpc") != "2.0":
            raise JSONRPCError(LSPErrorCode.INVALID_REQUEST, "Invalid JSON-RPC version")

        return message

    def parse_lsp_message(self, raw_data: bytes) -> tuple[dict[str, str], str]:
        """Parse LSP message with header and content."""
        try:
            # Split header and content
            header_end = raw_data.find(b"\r\n\r\n")
            if header_end == -1:
                raise JSONRPCError(
                    LSPErrorCode.PARSE_ERROR, "Invalid LSP message format"
                )

            header_data = raw_data[:header_end].decode("utf-8")
            content_data = raw_data[header_end + 4 :].decode("utf-8")

            # Parse header
            headers = {}
            for line in header_data.split("\r\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip()] = value.strip()

            # Validate content length
            if "Content-Length" not in headers:
                raise JSONRPCError(
                    LSPErrorCode.PARSE_ERROR, "Missing Content-Length header"
                )

            expected_length = int(headers["Content-Length"])
            if len(content_data.encode("utf-8")) != expected_length:
                raise JSONRPCError(LSPErrorCode.PARSE_ERROR, "Content length mismatch")

            return headers, content_data

        except (UnicodeDecodeError, ValueError) as e:
            raise JSONRPCError(
                LSPErrorCode.PARSE_ERROR, f"Message parsing error: {e}"
            ) from e

    def is_request(self, message: JsonRPCMessage) -> bool:
        """Check if message is a request."""
        return "id" in message and "method" in message

    def is_response(self, message: JsonRPCMessage) -> bool:
        """Check if message is a response."""
        return "id" in message and ("result" in message or "error" in message)

    def is_notification(self, message: JsonRPCMessage) -> bool:
        """Check if message is a notification."""
        return "method" in message and "id" not in message

    def get_pending_request(self, message_id: str | int) -> JSONRPCRequest | None:
        """Get a pending request by ID."""
        return self._pending_requests.get(message_id)

    def cancel_request(self, message_id: str | int) -> JSONRPCRequest | None:
        """Cancel a pending request."""
        return self._pending_requests.pop(message_id, None)

    def get_pending_request_count(self) -> int:
        """Get the number of pending requests."""
        return len(self._pending_requests)

    def clear_pending_requests(self) -> None:
        """Clear all pending requests."""
        self._pending_requests.clear()

    def validate_request(self, message: JsonRPCMessage) -> bool:
        """Validate a JSON-RPC request or notification message."""
        if not isinstance(message, dict):
            return False

        required_fields = ["jsonrpc", "method"]
        # Only requests need an ID, notifications don't
        if "id" in message:
            # This is a request
            required_fields.append("id")

        for field in required_fields:
            if field not in message:
                return False

        if message.get("jsonrpc") != "2.0":
            return False

        if not isinstance(message.get("method"), str):
            return False

        return True

    def validate_response(self, message: JsonRPCMessage) -> bool:
        """Validate a JSON-RPC response message."""
        if not isinstance(message, dict):
            return False

        required_fields = ["jsonrpc", "id"]
        for field in required_fields:
            if field not in message:
                return False

        if message.get("jsonrpc") != "2.0":
            return False

        # Must have either result or error, but not both
        has_result = "result" in message
        has_error = "error" in message

        if has_result and has_error:
            return False

        if not has_result and not has_error:
            return False

        return True
