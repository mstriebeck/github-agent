"""
Abstract LSP Client Infrastructure

This module provides the base infrastructure for Language Server Protocol clients,
including connection management, message handling, and capability negotiation.
"""

import asyncio
import logging
import os
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import Any

from lsp_constants import JsonRPCMessage, LSPCapabilities, LSPErrorCode, LSPMethod
from lsp_jsonrpc import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCProtocol,
    JSONRPCRequest,
    JSONRPCResponse,
)
from lsp_server_manager import LSPCommunicationMode, LSPServerManager


class LSPClientState(Enum):
    """States of the LSP client connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    SHUTTING_DOWN = "shutting_down"
    ERROR = "error"


class AbstractLSPClient(ABC):
    """Abstract base class for LSP client implementations."""

    def __init__(
        self,
        server_manager: LSPServerManager,
        workspace_root: str,
        logger: logging.Logger,
    ):
        self.server_manager = server_manager
        self.workspace_root = workspace_root
        self.logger = logger

        # Connection state
        self.state = LSPClientState.DISCONNECTED
        self.server_process: subprocess.Popen | None = None
        self.server_capabilities: dict[str, Any] = {}

        # Communication
        self.protocol = JSONRPCProtocol(logger=self.logger)
        self.communication_mode = server_manager.get_communication_mode()

        # Message handling
        self._message_handlers: dict[str, Callable] = {}
        self._response_handlers: dict[str | int, Callable] = {}
        self._notification_handlers: dict[str, Callable] = {}

        # Threading
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Initialize built-in handlers
        self._setup_builtin_handlers()

    def _setup_builtin_handlers(self) -> None:
        """Setup built-in message handlers."""
        # Server-to-client notifications
        self._notification_handlers[LSPMethod.PUBLISH_DIAGNOSTICS] = (
            self._handle_publish_diagnostics
        )
        self._notification_handlers[LSPMethod.SHOW_MESSAGE] = self._handle_show_message
        self._notification_handlers[LSPMethod.LOG_MESSAGE] = self._handle_log_message

        # Server-to-client requests
        self._message_handlers["workspace/configuration"] = (
            self._handle_workspace_configuration
        )
        self._message_handlers["window/showMessageRequest"] = (
            self._handle_show_message_request
        )

    def _set_state_connecting(self) -> None:
        """Set state to connecting and log the transition."""
        self.logger.info("LSP client connecting to server")
        self.state = LSPClientState.CONNECTING

    def _set_state_initializing(self) -> None:
        """Set state to initializing and log the transition."""
        self.logger.debug("LSP client initializing connection")
        self.state = LSPClientState.INITIALIZING

    def _set_state_initialized(self) -> None:
        """Set state to initialized and log the transition."""
        self.logger.info("LSP client successfully initialized")
        self.state = LSPClientState.INITIALIZED

    def _set_state_error(self, error_context: str) -> None:
        """Set state to error and log the error context."""
        self.logger.error(f"LSP client error: {error_context}")
        self.state = LSPClientState.ERROR

    def _set_state_shutting_down(self) -> None:
        """Set state to shutting down and log the transition."""
        self.logger.info("LSP client shutting down")
        self.state = LSPClientState.SHUTTING_DOWN

    def _set_state_disconnected(self) -> None:
        """Set state to disconnected and log the transition."""
        self.logger.info("LSP client disconnected")
        self.state = LSPClientState.DISCONNECTED

    async def start(self) -> bool:
        """Start the LSP server and initialize the connection."""
        try:
            self._set_state_connecting()

            # Start the server process
            if not await self._start_server():
                self._set_state_error("Failed to start LSP server process")
                return False

            # Start message reading thread
            self._start_reader_thread()

            # Initialize the connection
            if not await self._initialize_connection():
                self._set_state_error("Failed to initialize LSP connection")
                await self.stop()
                return False

            self._set_state_initialized()
            return True

        except Exception as e:
            self._set_state_error(f"Exception during startup: {e}")
            await self.stop()
            return False

    async def stop(self) -> None:
        """Stop the LSP server and clean up resources."""
        if self.state == LSPClientState.DISCONNECTED:
            return

        try:
            self._set_state_shutting_down()

            # Send shutdown request if still connected
            if self.state in [LSPClientState.INITIALIZED, LSPClientState.INITIALIZING]:
                await self._send_shutdown()

            # Stop reader thread
            self._stop_event.set()
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=5.0)

            # Terminate server process
            if self.server_process:
                try:
                    # Send exit notification
                    if self.server_process.poll() is None:
                        exit_notification = self.protocol.create_notification(
                            LSPMethod.EXIT
                        )
                        await self._send_message(exit_notification)

                    # Wait for graceful shutdown
                    try:
                        self.server_process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        self.logger.warning(
                            "Server didn't shut down gracefully, terminating"
                        )
                        self.server_process.terminate()
                        try:
                            self.server_process.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            self.logger.error("Server didn't terminate, killing")
                            self.server_process.kill()

                except Exception as e:
                    self.logger.error(f"Error during server shutdown: {e}")
                finally:
                    self.server_process = None

            self._set_state_disconnected()

        except Exception as e:
            self._set_state_error(f"Error during shutdown: {e}")

    async def _start_server(self) -> bool:
        """Start the LSP server process."""
        try:
            command = self.server_manager.get_server_command()
            args = self.server_manager.get_server_args()
            full_command = command + args

            self.logger.info(f"Starting LSP server: {' '.join(full_command)}")
            self.logger.debug(f"Communication mode: {self.communication_mode}")
            self.logger.debug(f"Workspace root: {self.workspace_root}")

            if self.communication_mode == LSPCommunicationMode.STDIO:
                self.server_process = subprocess.Popen(
                    full_command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,  # Binary mode for proper encoding handling
                    cwd=self.workspace_root,
                    env=os.environ.copy(),
                )
            else:
                raise NotImplementedError(
                    f"Communication mode {self.communication_mode} not implemented"
                )

            # Give the process a moment to start up
            await asyncio.sleep(0.1)

            # Check if process started successfully
            if self.server_process.poll() is not None:
                if self.server_process.stderr:
                    stderr = self.server_process.stderr.read().decode(
                        "utf-8", errors="replace"
                    )
                    self.logger.error(f"Server failed to start: {stderr}")
                else:
                    self.logger.error("Server failed to start: no stderr available")
                return False

            self.logger.info("LSP server process started successfully")
            self.logger.debug(f"Server process PID: {self.server_process.pid}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start LSP server: {e}")
            return False

    def _start_reader_thread(self) -> None:
        """Start the message reader thread."""
        self._reader_thread = threading.Thread(
            target=self._message_reader_loop, daemon=True
        )
        self._reader_thread.start()

    def _message_reader_loop(self) -> None:
        """Main message reading loop."""
        buffer = b""

        while not self._stop_event.is_set() and self.server_process:
            try:
                # Read data from server
                if self.server_process.stdout:
                    data = self.server_process.stdout.read(1024)
                else:
                    break
                if not data:
                    if self.server_process.poll() is not None:
                        self.logger.warning("Server process terminated")
                        break
                    continue

                buffer += data

                # Process complete messages
                while True:
                    try:
                        # Look for complete LSP message
                        header_end = buffer.find(b"\r\n\r\n")
                        if header_end == -1:
                            break

                        # Parse content length
                        header_data = buffer[:header_end].decode("utf-8")
                        content_length = None
                        for line in header_data.split("\r\n"):
                            if line.startswith("Content-Length:"):
                                content_length = int(line.split(":", 1)[1].strip())
                                break

                        if content_length is None:
                            self.logger.error("Invalid message: missing Content-Length")
                            buffer = buffer[header_end + 4 :]
                            continue

                        # Check if we have the complete message
                        message_end = header_end + 4 + content_length
                        if len(buffer) < message_end:
                            break

                        # Extract and process message
                        content = buffer[header_end + 4 : message_end].decode("utf-8")
                        buffer = buffer[message_end:]

                        # Process the message
                        try:
                            loop = asyncio.get_running_loop()
                            asyncio.run_coroutine_threadsafe(
                                self._process_message(content), loop
                            )
                        except RuntimeError:
                            # No event loop running, skip processing
                            self.logger.warning(
                                "No event loop running, skipping message processing"
                            )

                    except Exception as e:
                        self.logger.error(f"Error processing message: {e}")
                        break

            except Exception as e:
                if not self._stop_event.is_set():
                    self.logger.error(f"Error in message reader loop: {e}")
                break

    async def _process_message(self, content: str) -> None:
        """Process a received message."""
        try:
            # Parse JSON directly - the real parsing work is done by JsonRpcStreamReader in parse_lsp_message
            import json

            message = json.loads(content)

            # Basic validation
            if message.get("jsonrpc") != "2.0":
                raise JSONRPCError(
                    LSPErrorCode.INVALID_REQUEST, "Invalid JSON-RPC version"
                )

            if self.protocol.is_response(message):
                await self._handle_response(message)
            elif self.protocol.is_request(message):
                await self._handle_request(message)
            elif self.protocol.is_notification(message):
                await self._handle_notification(message)
            else:
                self.logger.warning(f"Unknown message type: {message}")

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON: {e}")
        except JSONRPCError as e:
            self.logger.error(f"JSON-RPC error: {e}")
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    async def _handle_response(self, message: JsonRPCMessage) -> None:
        """Handle a response message."""
        message_id = message.get("id")
        if message_id in self._response_handlers:
            handler = self._response_handlers.pop(message_id)
            try:
                await handler(message)
            except Exception as e:
                self.logger.error(f"Error in response handler: {e}")
        else:
            self.logger.warning(f"No handler for response ID: {message_id}")

    async def _handle_request(self, message: JsonRPCMessage) -> None:
        """Handle a request message."""
        method = message.get("method")
        if method in self._message_handlers:
            try:
                response = await self._message_handlers[method](message)
                if response:
                    await self._send_message(response)
            except Exception as e:
                self.logger.error(f"Error in request handler for {method}: {e}")
                message_id = message.get("id")
                if message_id is not None:
                    error_response = self.protocol.create_error_response(
                        message_id,
                        LSPErrorCode.INTERNAL_ERROR,
                        f"Handler error: {e}",
                    )
                    await self._send_message(error_response)
        else:
            self.logger.warning(f"No handler for request method: {method}")
            message_id = message.get("id")
            if message_id is not None:
                error_response = self.protocol.create_error_response(
                    message_id,
                    LSPErrorCode.METHOD_NOT_FOUND,
                    f"Method not found: {method}",
                )
                await self._send_message(error_response)

    async def _handle_notification(self, message: JsonRPCMessage) -> None:
        """Handle a notification message."""
        method = message.get("method")
        if method in self._notification_handlers:
            try:
                await self._notification_handlers[method](message)
            except Exception as e:
                self.logger.error(f"Error in notification handler for {method}: {e}")
        else:
            self.logger.debug(f"No handler for notification method: {method}")

    async def _send_message(
        self, message: JSONRPCRequest | JSONRPCResponse | JSONRPCNotification
    ) -> None:
        """Send a message to the server."""
        try:
            if self.server_process and self.server_process.stdin:
                serialized = self.protocol.serialize_message(message)
                self.server_process.stdin.write(serialized)
                self.server_process.stdin.flush()

                self.logger.debug(f"Sent message: {message.to_dict()}")
            else:
                self.logger.error("Cannot send message: no server connection")

        except Exception as e:
            self.logger.error(f"Error sending message: {e}")

    async def _initialize_connection(self) -> bool:
        """Initialize the LSP connection."""
        try:
            self._set_state_initializing()

            # Create initialize request
            init_params = {
                "processId": os.getpid(),
                "clientInfo": {"name": "github-agent-lsp-client", "version": "1.0.0"},
                "rootUri": f"file://{self.workspace_root}",
                "workspaceFolders": [
                    {
                        "uri": f"file://{self.workspace_root}",
                        "name": os.path.basename(self.workspace_root),
                    }
                ],
                "capabilities": LSPCapabilities.client_capabilities(),
                "initializationOptions": self.server_manager.get_initialization_options(),
            }

            self.logger.debug(f"Sending initialize request with params: {init_params}")
            self.logger.debug(
                f"Client capabilities: {LSPCapabilities.client_capabilities()}"
            )
            init_options = self.server_manager.get_initialization_options()
            if init_options:
                self.logger.debug(f"Initialization options: {init_options}")

            # Send initialize request
            init_request = self.protocol.create_request(
                LSPMethod.INITIALIZE, init_params
            )
            init_response = await self._send_request(init_request)

            if not init_response or "error" in init_response:
                self.logger.error(f"Initialize request failed: {init_response}")
                return False

            # Store server capabilities
            result = init_response.get("result", {})
            self.server_capabilities = result.get("capabilities", {})

            # Validate server response
            if not self.server_manager.validate_server_response(result):
                self.logger.error("Server initialization response validation failed")
                return False

            # Send initialized notification
            initialized_notification = self.protocol.create_notification(
                LSPMethod.INITIALIZED
            )
            await self._send_message(initialized_notification)

            self.logger.info("LSP connection initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize connection: {e}")
            return False

    async def _send_request(
        self, request: JSONRPCRequest, timeout: float = 30.0
    ) -> JsonRPCMessage | None:
        """Send a request and wait for response."""
        response_future: asyncio.Future[JsonRPCMessage] = asyncio.Future()

        async def response_handler(message: JsonRPCMessage) -> None:
            response_future.set_result(message)

        # Register response handler
        self._response_handlers[request.id] = response_handler

        try:
            # Send request
            await self._send_message(request)

            # Wait for response
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response

        except TimeoutError:
            self.logger.error(f"Request timeout: {request.method}")
            self._response_handlers.pop(request.id, None)
            return None
        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            self._response_handlers.pop(request.id, None)
            return None

    async def _send_shutdown(self) -> None:
        """Send shutdown request."""
        shutdown_request = self.protocol.create_request(LSPMethod.SHUTDOWN)
        await self._send_request(shutdown_request)

    # Built-in message handlers
    async def _handle_publish_diagnostics(self, message: JsonRPCMessage) -> None:
        """Handle publishDiagnostics notification."""
        params = message.get("params", {})
        uri = params.get("uri")
        diagnostics = params.get("diagnostics", [])
        self.logger.debug(f"Received diagnostics for {uri}: {len(diagnostics)} items")
        # Override in subclass for custom handling

    async def _handle_show_message(self, message: JsonRPCMessage) -> None:
        """Handle showMessage notification."""
        params = message.get("params", {})
        message_text = params.get("message", "")
        self.logger.info(f"Server message: {message_text}")
        # Override in subclass for custom handling

    async def _handle_log_message(self, message: JsonRPCMessage) -> None:
        """Handle logMessage notification."""
        params = message.get("params", {})
        message_text = params.get("message", "")
        self.logger.debug(f"Server log: {message_text}")
        # Override in subclass for custom handling

    async def _handle_workspace_configuration(
        self, message: JsonRPCMessage
    ) -> JSONRPCResponse | None:
        """Handle workspace/configuration request."""
        # Return empty configuration by default
        message_id = message.get("id")
        if message_id is not None:
            return self.protocol.create_response(message_id, {})
        return None

    async def _handle_show_message_request(
        self, message: JsonRPCMessage
    ) -> JSONRPCResponse | None:
        """Handle showMessageRequest."""
        # Return null by default (no action taken)
        message_id = message.get("id")
        if message_id is not None:
            return self.protocol.create_response(message_id, None)
        return None

    # Public API methods
    def is_initialized(self) -> bool:
        """Check if the client is initialized."""
        return self.state == LSPClientState.INITIALIZED

    def get_server_capabilities(self) -> dict[str, Any]:
        """Get the server's capabilities."""
        return self.server_capabilities.copy()

    def add_notification_handler(self, method: str, handler: Callable) -> None:
        """Add a notification handler."""
        self._notification_handlers[method] = handler

    def remove_notification_handler(self, method: str) -> None:
        """Remove a notification handler."""
        self._notification_handlers.pop(method, None)

    # Abstract methods for subclasses
    @abstractmethod
    async def get_definition(
        self, uri: str, line: int, character: int
    ) -> list[dict[str, Any]] | None:
        """Get definition for a symbol."""
        pass

    @abstractmethod
    async def get_references(
        self, uri: str, line: int, character: int, include_declaration: bool = True
    ) -> list[dict[str, Any]] | None:
        """Get references for a symbol."""
        pass

    @abstractmethod
    async def get_hover(
        self, uri: str, line: int, character: int
    ) -> dict[str, Any] | None:
        """Get hover information for a symbol."""
        pass

    @abstractmethod
    async def get_document_symbols(self, uri: str) -> list[dict[str, Any]] | None:
        """Get document symbols."""
        pass
