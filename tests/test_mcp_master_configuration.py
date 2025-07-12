#!/usr/bin/env python3

"""
Tests for MCP Master Configuration Validation

Tests to ensure the master process correctly validates repository configuration
and fails to start if required fields are missing.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from repository_manager import RepositoryManager


class TestRepositoryManagerConfigurationValidation(unittest.TestCase):
    """Test RepositoryManager configuration validation"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test_repositories.json"

        # Create a valid test repository path
        self.test_repo_path = Path(self.temp_dir) / "test_repo"
        self.test_repo_path.mkdir()
        # Make it a proper git repo
        subprocess.run(
            ["git", "init"], cwd=self.test_repo_path, check=True, capture_output=True
        )
        # Create a Python file to satisfy repository validation
        (self.test_repo_path / "main.py").write_text('print("Hello World")')

        # Valid complete configuration for reference
        # Use sys.executable to get a valid Python path that works in any environment

        self.valid_config = {
            "repositories": {
                "test-repo": {
                    "workspace": str(self.test_repo_path),
                    "port": 8081,
                    "description": "Test repository",
                    "language": "python",
                    "python_path": sys.executable,
                }
            }
        }

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def _write_config_file(self, config):
        """Write configuration data to test config file"""
        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

    def test_valid_configuration_loads_successfully(self):
        """Test that a valid configuration loads successfully"""
        self._write_config_file(self.valid_config)

        # Test RepositoryManager directly - this is what actually validates configuration
        manager = RepositoryManager.create_from_config(str(self.config_file))

        self.assertEqual(len(manager.repositories), 1)
        self.assertIn("test-repo", manager.repositories)

    def test_missing_port_field_fails_validation(self):
        """Test that missing 'port' field causes configuration load to fail"""
        config_missing_port = {
            "repositories": {
                "test-repo": {
                    "workspace": str(self.test_repo_path),
                    "description": "Test repository",
                    "language": "python",
                    "python_path": "/Volumes/Code/github-agent/.venv/bin/python",
                    # Missing port field
                }
            }
        }
        self._write_config_file(config_missing_port)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))

    def test_missing_path_field_fails_validation(self):
        """Test that missing 'path' field causes configuration load to fail"""
        config_missing_path = {
            "repositories": {
                "test-repo": {
                    "port": 8081,
                    "description": "Test repository",
                    "language": "python",
                    "python_path": "/Volumes/Code/github-agent/.venv/bin/python",
                    # Missing path field
                }
            }
        }
        self._write_config_file(config_missing_path)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))

    def test_missing_language_field_fails_validation(self):
        """Test that missing 'language' field causes configuration load to fail"""
        config_missing_language = {
            "repositories": {
                "test-repo": {
                    "workspace": str(self.test_repo_path),
                    "port": 8081,
                    "description": "Test repository",
                    "python_path": "/Volumes/Code/github-agent/.venv/bin/python",
                    # Missing language field
                }
            }
        }
        self._write_config_file(config_missing_language)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))

    def test_missing_python_path_field_fails_validation(self):
        """Test that missing 'python_path' field causes configuration load to fail"""
        config_missing_python_path = {
            "repositories": {
                "test-repo": {
                    "workspace": str(self.test_repo_path),
                    "port": 8081,
                    "description": "Test repository",
                    "language": "python",
                    # Missing python_path field
                }
            }
        }
        self._write_config_file(config_missing_python_path)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))

    def test_multiple_missing_fields_fails_validation(self):
        """Test that configuration with multiple missing fields fails validation"""
        config_multiple_missing = {
            "repositories": {
                "test-repo": {
                    "workspace": str(self.test_repo_path),
                    "description": "Test repository",
                    # Missing port, language, and python_path fields
                }
            }
        }
        self._write_config_file(config_multiple_missing)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))

    def test_all_required_fields_must_be_present(self):
        """Test that all required fields must be present for successful validation"""
        # Test each field individually by removing it from otherwise valid config
        required_fields = ["port", "workspace", "language", "python_path"]

        for field_to_remove in required_fields:
            with self.subTest(missing_field=field_to_remove):
                config = self.valid_config.copy()
                # Remove the specific field
                del config["repositories"]["test-repo"][field_to_remove]

                self._write_config_file(config)

                with self.assertRaises(RuntimeError):
                    RepositoryManager.create_from_config(str(self.config_file))

    def test_no_auto_assignment_of_missing_fields(self):
        """Test that missing fields are not auto-assigned"""
        config_missing_port = {
            "repositories": {
                "test-repo": {
                    "workspace": str(self.test_repo_path),
                    "description": "Test repository",
                    "language": "python",
                    "python_path": "/Volumes/Code/github-agent/.venv/bin/python",
                    # Missing port - should not be auto-assigned
                }
            }
        }
        self._write_config_file(config_missing_port)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))

    def test_configuration_file_not_modified(self):
        """Test that the configuration file is never modified during load"""
        self._write_config_file(self.valid_config)

        # Read original file content
        with open(self.config_file) as f:
            original_content = f.read()

        # Test that RepositoryManager.create_from_config doesn't modify the file
        RepositoryManager.create_from_config(str(self.config_file))

        # Read file content after load
        with open(self.config_file) as f:
            after_load_content = f.read()

        self.assertEqual(
            original_content,
            after_load_content,
            "Configuration file should never be modified during load",
        )

    def test_multiple_repositories_all_fields_required(self):
        """Test that all repositories must have all required fields"""
        config_with_multiple_repos = {
            "repositories": {
                "repo1": {
                    "workspace": str(self.test_repo_path),
                    "port": 8081,
                    "description": "Test repository 1",
                    "language": "python",
                    "python_path": "/Volumes/Code/github-agent/.venv/bin/python",
                },
                "repo2": {
                    "workspace": str(self.test_repo_path),
                    "port": 8082,
                    "description": "Test repository 2",
                    "language": "swift",
                    # Missing python_path field for repo2
                },
            }
        }
        self._write_config_file(config_with_multiple_repos)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))

    def test_empty_repositories_section_fails(self):
        """Test that empty repositories section fails validation"""
        empty_config: dict[str, dict[str, dict]] = {"repositories": {}}
        self._write_config_file(empty_config)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))

    def test_missing_repositories_key_fails(self):
        """Test that missing repositories key fails validation"""
        invalid_config = {"some_other_key": "value"}
        self._write_config_file(invalid_config)

        with self.assertRaises(RuntimeError):
            RepositoryManager.create_from_config(str(self.config_file))


if __name__ == "__main__":
    unittest.main()
