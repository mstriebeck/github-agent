"""
Tests for Pyright LSP Manager

Tests the PyrightLSPManager class functionality including server management,
configuration, and workspace preparation.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from lsp_client import LSPCommunicationMode
from pyright_lsp_manager import PyrightLSPManager


class TestPyrightLSPManager(unittest.TestCase):
    """Test cases for PyrightLSPManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_path = Path(self.temp_dir) / "test_workspace"
        self.workspace_path.mkdir()

        # Create a sample Python file to make it a valid workspace
        (self.workspace_path / "main.py").write_text("print('Hello, World!')")

        self.python_path = "/usr/bin/python3"

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_init_with_available_pyright(self, mock_run):
        """Test initialization when pyright is available."""
        # Mock successful pyright version check
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)

        self.assertEqual(manager.workspace_path, self.workspace_path)
        self.assertEqual(manager.python_path, self.python_path)
        mock_run.assert_called_once_with(
            ["pyright", "--version"], capture_output=True, text=True, check=True
        )

    @patch("pyright_lsp_manager.subprocess.run")
    def test_init_with_unavailable_pyright(self, mock_run):
        """Test initialization when pyright is not available."""
        # Mock failed pyright version check
        mock_run.side_effect = FileNotFoundError()

        with self.assertRaises(RuntimeError) as context:
            PyrightLSPManager(str(self.workspace_path), self.python_path)

        self.assertIn("Pyright is not available", str(context.exception))

    @patch("pyright_lsp_manager.subprocess.run")
    def test_get_server_command(self, mock_run):
        """Test getting the server command."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)
        command = manager.get_server_command()

        self.assertEqual(command, ["pyright-langserver", "--stdio"])

    @patch("pyright_lsp_manager.subprocess.run")
    def test_get_communication_mode(self, mock_run):
        """Test getting the communication mode."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)
        mode = manager.get_communication_mode()

        self.assertEqual(mode, LSPCommunicationMode.STDIO)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_get_server_capabilities(self, mock_run):
        """Test getting server capabilities."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)
        capabilities = manager.get_server_capabilities()

        # Check key capabilities
        self.assertIn("textDocumentSync", capabilities)
        self.assertIn("completionProvider", capabilities)
        self.assertIn("hoverProvider", capabilities)
        self.assertIn("definitionProvider", capabilities)
        self.assertIn("referencesProvider", capabilities)
        self.assertTrue(capabilities["hoverProvider"])
        self.assertTrue(capabilities["definitionProvider"])

    @patch("pyright_lsp_manager.subprocess.run")
    def test_get_initialization_options(self, mock_run):
        """Test getting initialization options."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)
        options = manager.get_initialization_options()

        # Check structure
        self.assertIn("settings", options)
        self.assertIn("python", options["settings"])
        self.assertIn("pythonPath", options["settings"]["python"])
        self.assertEqual(options["settings"]["python"]["pythonPath"], self.python_path)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_get_initialization_options_no_python_path(self, mock_run):
        """Test getting initialization options without Python path."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path))
        options = manager.get_initialization_options()

        # Check structure
        self.assertIn("settings", options)
        self.assertIn("python", options["settings"])
        self.assertNotIn("pythonPath", options["settings"]["python"])

    @patch("pyright_lsp_manager.subprocess.run")
    def test_get_workspace_folders(self, mock_run):
        """Test getting workspace folders."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)
        folders = manager.get_workspace_folders()

        self.assertEqual(len(folders), 1)
        self.assertIn("uri", folders[0])
        self.assertIn("name", folders[0])
        self.assertEqual(folders[0]["name"], self.workspace_path.name)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_prepare_workspace(self, mock_run):
        """Test workspace preparation."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)
        manager.prepare_workspace()

        # Check that pyrightconfig.json was created
        config_path = self.workspace_path / "pyrightconfig.json"
        self.assertTrue(config_path.exists())

        # Check config content
        with open(config_path) as f:
            config = json.load(f)

        self.assertIn("include", config)
        self.assertIn("exclude", config)
        self.assertIn("pythonPath", config)
        self.assertEqual(config["pythonPath"], self.python_path)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_prepare_workspace_existing_config(self, mock_run):
        """Test workspace preparation when config already exists."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        # Create existing config
        config_path = self.workspace_path / "pyrightconfig.json"
        existing_config = {"custom": "config"}
        with open(config_path, "w") as f:
            json.dump(existing_config, f)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)
        manager.prepare_workspace()

        # Check that existing config was not overwritten
        with open(config_path) as f:
            config = json.load(f)

        self.assertEqual(config, existing_config)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_is_valid_python_workspace(self, mock_run):
        """Test Python workspace validation."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)

        # Already has main.py from setUp
        self.assertTrue(manager._is_valid_python_workspace())

        # Test with setup.py
        (self.workspace_path / "main.py").unlink()
        (self.workspace_path / "setup.py").write_text("from setuptools import setup")
        self.assertTrue(manager._is_valid_python_workspace())

        # Test with requirements.txt
        (self.workspace_path / "setup.py").unlink()
        (self.workspace_path / "requirements.txt").write_text("requests==2.25.1")
        self.assertTrue(manager._is_valid_python_workspace())

    @patch("pyright_lsp_manager.subprocess.run")
    def test_validate_configuration_success(self, mock_run):
        """Test configuration validation success."""
        mock_run.return_value = Mock(stdout="Python 3.8.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)

        # Mock Python path existence
        with patch("pathlib.Path.exists", return_value=True):
            result = manager.validate_configuration()

        self.assertTrue(result)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_validate_configuration_invalid_workspace(self, mock_run):
        """Test configuration validation with invalid workspace."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        # Use non-existent workspace
        manager = PyrightLSPManager("/non/existent/path", self.python_path)
        result = manager.validate_configuration()

        self.assertFalse(result)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_validate_configuration_invalid_python_path(self, mock_run):
        """Test configuration validation with invalid Python path."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), "/non/existent/python")
        result = manager.validate_configuration()

        self.assertFalse(result)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_get_server_info(self, mock_run):
        """Test getting server information."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)
        info = manager.get_server_info()

        self.assertIn("name", info)
        self.assertIn("version", info)
        self.assertIn("workspace", info)
        self.assertIn("python_path", info)
        self.assertEqual(info["name"], "pyright")
        self.assertEqual(info["workspace"], str(self.workspace_path))
        self.assertEqual(info["python_path"], self.python_path)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_cleanup(self, mock_run):
        """Test cleanup method."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path), self.python_path)

        # Should not raise any exceptions
        manager.cleanup()


class TestPyrightLSPManagerIntegration(unittest.TestCase):
    """Integration tests for PyrightLSPManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_path = Path(self.temp_dir) / "test_workspace"
        self.workspace_path.mkdir()

        # Create a realistic Python project structure
        (self.workspace_path / "main.py").write_text("""
def hello_world():
    print("Hello, World!")

if __name__ == "__main__":
    hello_world()
""")

        (self.workspace_path / "utils.py").write_text("""
def add_numbers(a, b):
    return a + b

class Calculator:
    def multiply(self, x, y):
        return x * y
""")

        (self.workspace_path / "requirements.txt").write_text("requests==2.25.1")

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir)

    @patch("pyright_lsp_manager.subprocess.run")
    def test_full_workspace_setup(self, mock_run):
        """Test full workspace setup process."""
        mock_run.return_value = Mock(stdout="pyright 1.1.0", returncode=0)

        manager = PyrightLSPManager(str(self.workspace_path))

        # Test workspace preparation
        manager.prepare_workspace()

        # Check that config was created
        config_path = self.workspace_path / "pyrightconfig.json"
        self.assertTrue(config_path.exists())

        # Test workspace folders
        folders = manager.get_workspace_folders()
        self.assertEqual(len(folders), 1)
        self.assertTrue(folders[0]["uri"].endswith("test_workspace"))

        # Test capabilities
        capabilities = manager.get_server_capabilities()
        self.assertIn("textDocumentSync", capabilities)
        self.assertIn("completionProvider", capabilities)


if __name__ == "__main__":
    unittest.main()
