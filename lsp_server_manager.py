"""
LSP Server Manager Interface

This module provides the abstract interface for LSP server management,
enabling pluggable server implementations for different languages.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class LSPCommunicationMode(Enum):
    """Communication modes for LSP servers."""

    STDIO = "stdio"
    TCP = "tcp"


class LSPServerManager(ABC):
    """Abstract interface for LSP server management."""

    @abstractmethod
    def get_server_command(self) -> list[str]:
        """Get the command to start the LSP server."""
        pass

    @abstractmethod
    def get_server_args(self) -> list[str]:
        """Get additional arguments for the LSP server."""
        pass

    @abstractmethod
    def get_communication_mode(self) -> LSPCommunicationMode:
        """Get the communication mode for the server."""
        pass

    @abstractmethod
    def get_server_capabilities(self) -> dict[str, Any]:
        """Get server-specific capabilities to request."""
        pass

    @abstractmethod
    def get_initialization_options(self) -> dict[str, Any] | None:
        """Get initialization options for the server."""
        pass

    @abstractmethod
    def validate_server_response(self, response: dict[str, Any]) -> bool:
        """Validate server initialization response."""
        pass
