"""
JSON-RPC 2.0 Protocol Implementation for LSP

This module leverages python-lsp-jsonrpc package for all core functionality
and provides only minimal compatibility wrappers where needed.
"""

import io
import json
import logging
import uuid
from typing import Any

from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter

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


# Simple compatibility classes that just wrap dictionaries
class JSONRPCMessage:
    """Base class for JSON-RPC messages - minimal wrapper around dict."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        """Convert message to dictionary."""
        return self._data.copy()

    def to_json(self) -> str:
        """Convert message to JSON string."""
        return json.dumps(self._data, separators=(",", ":"))

    @property
    def jsonrpc(self) -> str:
        return self._data.get("jsonrpc", "2.0")


class JSONRPCRequest(JSONRPCMessage):
    """JSON-RPC request message."""

    def __init__(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        message_id: str | int | None = None,
    ):
        data = {
            "jsonrpc": "2.0",
            "method": method,
            "id": message_id or str(uuid.uuid4()),
        }
        if params:
            data["params"] = params
        super().__init__(data)

    @property
    def method(self) -> str:
        return self._data["method"]

    @property
    def params(self) -> dict[str, Any]:
        return self._data.get("params", {})

    @property
    def id(self) -> str | int:
        return self._data["id"]


class JSONRPCNotification(JSONRPCMessage):
    """JSON-RPC notification message."""

    def __init__(self, method: str, params: dict[str, Any] | None = None):
        data = {"jsonrpc": "2.0", "method": method}
        if params:
            data["params"] = params
        super().__init__(data)

    @property
    def method(self) -> str:
        return self._data["method"]

    @property
    def params(self) -> dict[str, Any]:
        return self._data.get("params", {})


class JSONRPCResponse(JSONRPCMessage):
    """JSON-RPC response message."""

    def __init__(
        self,
        message_id: str | int,
        result: Any | None = None,
        error: dict[str, Any] | None = None,
    ):
        data = {"jsonrpc": "2.0", "id": message_id}
        if error is not None:
            data["error"] = error
        else:
            data["result"] = result
        super().__init__(data)

    @property
    def id(self) -> str | int:
        return self._data["id"]

    @property
    def result(self) -> Any:
        return self._data.get("result")

    @property
    def error(self) -> dict[str, Any] | None:
        return self._data.get("error")

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
    """JSON-RPC 2.0 protocol handler leveraging python-lsp-jsonrpc."""

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(__name__)

        # Create stream writer for serialization
        self._stream_buffer = io.BytesIO()
        self._stream_writer = JsonRpcStreamWriter(self._stream_buffer)

        # Simple pending request tracking (we can't fully use Endpoint because we need the wrapper classes)
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
        self._pending_requests.pop(message_id, None)
        return JSONRPCResponse.create_error(
            message_id=message_id, code=code, message=message, data=data
        )

    def serialize_message(self, message: JSONRPCMessage) -> bytes:
        """Serialize a JSON-RPC message using python-lsp-jsonrpc."""
        self._stream_buffer.seek(0)
        self._stream_buffer.truncate()
        self._stream_writer.write(message.to_dict())
        self._stream_buffer.seek(0)
        return self._stream_buffer.read()

    def parse_lsp_message(self, raw_data: bytes) -> tuple[dict[str, str], str]:
        """Parse LSP message using python-lsp-jsonrpc with validation."""
        try:
            # First validate the basic structure before using the reader
            header_end = raw_data.find(b"\r\n\r\n")
            if header_end == -1:
                raise JSONRPCError(
                    LSPErrorCode.PARSE_ERROR, "Invalid LSP message format"
                )

            header_data = raw_data[:header_end].decode("utf-8")
            content_data = raw_data[header_end + 4 :].decode("utf-8")

            # Parse and validate headers
            headers = {}
            for line in header_data.split("\r\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip()] = value.strip()

            # Validate content length (tests expect this validation)
            if "Content-Length" not in headers:
                raise JSONRPCError(
                    LSPErrorCode.PARSE_ERROR, "Missing Content-Length header"
                )

            expected_length = int(headers["Content-Length"])
            if len(content_data.encode("utf-8")) != expected_length:
                raise JSONRPCError(LSPErrorCode.PARSE_ERROR, "Content length mismatch")

            # Now use JsonRpcStreamReader for actual parsing
            stream = io.BytesIO(raw_data)
            reader = JsonRpcStreamReader(stream)

            messages = []

            def consume_message(msg):
                messages.append(msg)

            reader.listen(consume_message)

            if not messages:
                raise JSONRPCError(
                    LSPErrorCode.PARSE_ERROR, "No valid JSON-RPC message found"
                )

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
        if "id" in message:
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

        has_result = "result" in message
        has_error = "error" in message

        if has_result and has_error:
            return False

        if not has_result and not has_error:
            return False

        return True
