"""
Simple smoke tests for LSP integration.

These tests verify that the LSP components can be created and wired together
correctly without requiring a full mock server setup.
"""

import tempfile
from unittest.mock import Mock

import pytest

from lsp_client import AbstractLSPClient, LSPClientState
from lsp_server_manager import LSPCommunicationMode, LSPServerManager
from pyright_lsp_manager import PyrightLSPManager


class SimpleLSPClient(AbstractLSPClient):
    """Minimal LSP client implementation for smoke testing."""

    async def get_definition(self, uri, line, character):
        return None

    async def get_references(self, uri, line, character, include_declaration=True):
        return None

    async def get_hover(self, uri, line, character):
        return None

    async def get_document_symbols(self, uri):
        return None


class MockServerManager(LSPServerManager):
    """Simple mock server manager for smoke testing."""

    def get_server_command(self):
        return ["echo", "mock-server"]

    def get_server_args(self):
        return []

    def get_communication_mode(self):
        return LSPCommunicationMode.STDIO

    def get_server_capabilities(self):
        return {"textDocumentSync": 2, "definitionProvider": True}

    def get_initialization_options(self):
        return None

    def validate_server_response(self, response):
        return "capabilities" in response


class TestLSPIntegration:
    """Simple smoke tests for LSP integration."""

    def test_lsp_client_creation(self):
        """Test that LSP client can be created with server manager."""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_manager = MockServerManager()
            logger = Mock()

            client = SimpleLSPClient(
                server_manager=server_manager, workspace_root=temp_dir, logger=logger
            )

            assert client.server_manager is server_manager
            assert client.workspace_root == temp_dir
            assert client.logger is logger
            assert client.state == LSPClientState.DISCONNECTED
            assert not client.is_initialized()

    def test_pyright_manager_creation(self):
        """Test that Pyright LSP manager can be created."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a simple Python file
            python_file = temp_dir + "/test.py"
            with open(python_file, "w") as f:
                f.write("def hello(): pass\n")

            try:
                manager = PyrightLSPManager(temp_dir)

                assert manager.workspace_path.name == temp_dir.split("/")[-1]
                assert manager.get_communication_mode() == LSPCommunicationMode.STDIO
                assert "pyright-langserver" in manager.get_server_command()
                assert manager.get_server_capabilities() == {}

            except RuntimeError as e:
                if "Pyright is not available" in str(e):
                    pytest.skip("Pyright not installed")
                else:
                    raise

    def test_lsp_client_with_pyright_manager(self):
        """Test that LSP client works with Pyright manager."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a simple Python file
            python_file = temp_dir + "/test.py"
            with open(python_file, "w") as f:
                f.write("def hello(): pass\n")

            try:
                server_manager = PyrightLSPManager(temp_dir)
                logger = Mock()

                client = SimpleLSPClient(
                    server_manager=server_manager,
                    workspace_root=temp_dir,
                    logger=logger,
                )

                # Test that components are properly wired
                assert client.server_manager is server_manager
                assert client.workspace_root == temp_dir
                assert client.communication_mode == LSPCommunicationMode.STDIO

                # Test that we can call server manager methods
                command = server_manager.get_server_command()
                assert isinstance(command, list)
                assert len(command) > 0

            except RuntimeError as e:
                if "Pyright is not available" in str(e):
                    pytest.skip("Pyright not installed")
                else:
                    raise

    def test_server_manager_interface_compliance(self):
        """Test that server managers implement the required interface."""
        server_manager = MockServerManager()

        # Test all required methods exist and return expected types
        assert isinstance(server_manager.get_server_command(), list)
        assert isinstance(server_manager.get_server_args(), list)
        assert isinstance(server_manager.get_communication_mode(), LSPCommunicationMode)
        assert isinstance(server_manager.get_server_capabilities(), dict)

        # get_initialization_options can return None or dict
        init_options = server_manager.get_initialization_options()
        assert init_options is None or isinstance(init_options, dict)

        # validate_server_response should accept a dict and return bool
        assert isinstance(
            server_manager.validate_server_response({"capabilities": {}}), bool
        )

    def test_lsp_client_state_management(self):
        """Test LSP client state management."""
        with tempfile.TemporaryDirectory() as temp_dir:
            server_manager = MockServerManager()
            logger = Mock()

            client = SimpleLSPClient(
                server_manager=server_manager, workspace_root=temp_dir, logger=logger
            )

            # Test initial state
            assert client.state == LSPClientState.DISCONNECTED
            assert not client.is_initialized()

            # Test state transitions (without actually starting server)
            client._set_state_connecting()
            assert client.state == LSPClientState.CONNECTING

            client._set_state_initialized()
            assert client.state == LSPClientState.INITIALIZED
            assert client.is_initialized()

            client._set_state_error("Test error")
            assert client.state == LSPClientState.ERROR
            assert not client.is_initialized()

            client._set_state_disconnected()
            assert client.state == LSPClientState.DISCONNECTED
            assert not client.is_initialized()
