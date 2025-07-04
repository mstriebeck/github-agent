#!/usr/bin/env python3

"""
Tests for Configuration Management Features (CLI, Hot Reload, etc.)
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from repository_manager import RepositoryManager


class TestRepositoryCLI(unittest.TestCase):
    """Test repository management CLI functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "repositories.json"

        # Create test repository directories
        self.repo1_path = Path(self.temp_dir) / "repo1"
        self.repo2_path = Path(self.temp_dir) / "repo2"
        self.repo1_path.mkdir()
        self.repo2_path.mkdir()

        # Initialize as git repositories
        self._init_git_repo(self.repo1_path)
        self._init_git_repo(self.repo2_path)

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def _init_git_repo(self, repo_path):
        """Initialize a git repository for testing"""
        os.system(f"cd {repo_path} && git init --quiet")
        os.system(f"cd {repo_path} && git config user.email 'test@example.com'")
        os.system(f"cd {repo_path} && git config user.name 'Test User'")
        os.system(
            f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet"
        )

    def _run_cli_command(self, args):
        """Run CLI command and return result"""
        try:
            result = subprocess.run(
                [sys.executable, "repository_cli.py", *args],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
                env={**os.environ, "GITHUB_AGENT_REPO_CONFIG": str(self.config_file)},
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return 1, "", str(e)

    @unittest.skip("CLI removed in US001-2")
    def test_cli_init_example(self):
        """Test CLI init with example configuration"""
        returncode, stdout, stderr = self._run_cli_command(["init", "--example"])

        self.assertEqual(returncode, 0, f"CLI failed: {stderr}")
        self.assertIn("Created example configuration", stdout)
        self.assertTrue(self.config_file.exists())

        # Verify configuration content
        with open(self.config_file) as f:
            config = json.load(f)

        self.assertIn("repositories", config)
        self.assertIsInstance(config["repositories"], dict)

    @unittest.skip("CLI removed in US001-2")
    def test_cli_add_repository(self):
        """Test CLI add repository command"""
        # Initialize empty config first
        returncode, _, _ = self._run_cli_command(["init"])
        self.assertEqual(returncode, 0)

        # Add repository
        returncode, stdout, stderr = self._run_cli_command(
            [
                "add",
                "test-repo",
                str(self.repo1_path),
                "--description",
                "Test repository",
            ]
        )

        self.assertEqual(returncode, 0, f"CLI failed: {stderr}")
        self.assertIn("Added repository 'test-repo'", stdout)

        # Verify configuration was updated
        with open(self.config_file) as f:
            config = json.load(f)

        self.assertIn("test-repo", config["repositories"])

        # Handle macOS symlink resolution where /var may become /private/var
        expected_path = str(self.repo1_path)
        actual_path = config["repositories"]["test-repo"]["path"]

        # Check if paths match either as-is or with /private prefix resolved
        paths_match = (
            actual_path == expected_path
            or actual_path == expected_path.replace("/var/", "/private/var/")
            or expected_path == actual_path.replace("/var/", "/private/var/")
        )

        self.assertTrue(
            paths_match,
            f"Path mismatch: expected '{expected_path}', got '{actual_path}'",
        )

        self.assertEqual(
            config["repositories"]["test-repo"]["description"], "Test repository"
        )

    @unittest.skip("CLI removed in US001-2")
    def test_cli_list_repositories(self):
        """Test CLI list repositories command"""
        # Create test configuration
        config = {
            "repositories": {
                "repo1": {
                    "path": str(self.repo1_path),
                    "description": "Repository 1",
                    "language": "python",
                    "port": 8081,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "repo1",
                },
                "repo2": {
                    "path": str(self.repo2_path),
                    "description": "Repository 2",
                    "language": "swift",
                    "port": 8082,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "repo2",
                },
            }
        }

        with open(self.config_file, "w") as f:
            json.dump(config, f)

        # List repositories
        returncode, stdout, stderr = self._run_cli_command(["list"])

        self.assertEqual(returncode, 0, f"CLI failed: {stderr}")
        self.assertIn("repo1", stdout)
        self.assertIn("repo2", stdout)
        # Check that each repository has its own port and URL
        self.assertIn("Port:", stdout)
        self.assertIn("URL: http://localhost:", stdout)
        self.assertIn("/mcp/", stdout)

    @unittest.skip("CLI removed in US001-2")
    def test_cli_remove_repository(self):
        """Test CLI remove repository command"""
        # Create test configuration
        config = {
            "repositories": {
                "repo1": {
                    "path": str(self.repo1_path),
                    "description": "Repository 1",
                    "language": "python",
                    "port": 8081,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "repo1",
                },
                "repo2": {
                    "path": str(self.repo2_path),
                    "description": "Repository 2",
                    "language": "swift",
                    "port": 8082,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "repo2",
                },
            }
        }

        with open(self.config_file, "w") as f:
            json.dump(config, f)

        # Remove repository using --yes flag to skip confirmation
        returncode, stdout, stderr = self._run_cli_command(["remove", "repo1", "--yes"])

        self.assertEqual(returncode, 0, f"CLI failed: {stderr}")
        self.assertIn("Removed repository 'repo1'", stdout)

        # Verify configuration was updated
        with open(self.config_file) as f:
            config = json.load(f)

        self.assertNotIn("repo1", config["repositories"])
        self.assertIn("repo2", config["repositories"])

    @unittest.skip("CLI removed in US001-2")
    def test_cli_validate_configuration(self):
        """Test CLI validate configuration command"""
        # Create valid configuration
        config = {
            "repositories": {
                "repo1": {
                    "path": str(self.repo1_path),
                    "description": "Repository 1",
                    "language": "python",
                    "port": 8086,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "repo1",
                }
            }
        }

        with open(self.config_file, "w") as f:
            json.dump(config, f)

        # Validate configuration
        returncode, stdout, stderr = self._run_cli_command(["validate"])

        self.assertEqual(returncode, 0, f"CLI failed: {stderr}")
        self.assertIn("Configuration loaded successfully", stdout)
        self.assertIn("All repositories are valid", stdout)

    @unittest.skip("CLI removed in US001-2")
    def test_cli_error_handling(self):
        """Test CLI error handling for invalid operations"""
        # Test adding repository with invalid name
        returncode, stdout, stderr = self._run_cli_command(
            ["add", "invalid name with spaces", str(self.repo1_path)]
        )

        self.assertNotEqual(returncode, 0)

        # Test removing non-existent repository
        returncode, stdout, stderr = self._run_cli_command(["remove", "nonexistent"])

        self.assertNotEqual(returncode, 0)


class TestConfigurationHotReload(unittest.TestCase):
    """Test configuration hot reload functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "repositories.json"

        # Create test repository directory
        self.repo_path = Path(self.temp_dir) / "repo"
        self.repo_path.mkdir()
        self._init_git_repo(self.repo_path)

        # Create initial configuration
        self.initial_config = {
            "repositories": {
                "initial-repo": {
                    "path": str(self.repo_path),
                    "description": "Initial repository",
                    "language": "python",
                    "port": 8081,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "initial-repo",
                }
            }
        }

        with open(self.config_file, "w") as f:
            json.dump(self.initial_config, f)

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def _init_git_repo(self, repo_path):
        """Initialize a git repository for testing"""
        os.system(f"cd {repo_path} && git init --quiet")
        os.system(f"cd {repo_path} && git config user.email 'test@example.com'")
        os.system(f"cd {repo_path} && git config user.name 'Test User'")
        os.system(
            f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet"
        )

    def test_hot_reload_detection(self):
        """Test that configuration changes are detected"""
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()

        # Initial state
        self.assertEqual(len(manager.list_repositories()), 1)
        self.assertIn("initial-repo", manager.list_repositories())

        # Initialize the file change tracking by calling check_for_config_changes once
        manager.check_for_config_changes()

        # Modify configuration file
        # Force a longer delay to ensure filesystem timestamp resolution
        time.sleep(1.1)  # Ensure different modification time

        updated_config = {
            "repositories": {
                "initial-repo": {
                    "path": str(self.repo_path),
                    "description": "Initial repository",
                    "language": "python",
                    "port": 8083,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "initial-repo",
                },
                "new-repo": {
                    "path": str(self.repo_path),
                    "description": "New repository",
                    "language": "swift",
                    "port": 8084,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "new-repo",
                },
            }
        }

        with open(self.config_file, "w") as f:
            json.dump(updated_config, f)
            # Ensure file is flushed to disk
            f.flush()
            import os

            os.fsync(f.fileno())

        # Check for changes
        changed = manager.check_for_config_changes()
        self.assertTrue(changed, "Should detect configuration changes")

        # Verify new configuration is loaded
        self.assertEqual(len(manager.list_repositories()), 2)
        self.assertIn("initial-repo", manager.list_repositories())
        self.assertIn("new-repo", manager.list_repositories())

    def test_hot_reload_callbacks(self):
        """Test that reload callbacks are called"""
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()

        # Add callback
        callback_called = []

        def test_callback():
            callback_called.append(True)

        manager.add_reload_callback(test_callback)

        # Initialize the file change tracking by calling check_for_config_changes once
        manager.check_for_config_changes()

        # Modify configuration
        # Force a longer delay to ensure filesystem timestamp resolution
        time.sleep(1.1)

        updated_config = {
            "repositories": {
                "different-repo": {
                    "path": str(self.repo_path),
                    "description": "Different repository",
                    "language": "python",
                    "port": 8085,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "different-repo",
                }
            }
        }

        with open(self.config_file, "w") as f:
            json.dump(updated_config, f)
            # Ensure file is flushed to disk
            f.flush()
            import os

            os.fsync(f.fileno())

        # Check for changes
        manager.check_for_config_changes()

        # Verify callback was called
        self.assertTrue(callback_called, "Reload callback should have been called")

    def test_hot_reload_invalid_config(self):
        """Test hot reload with invalid configuration"""
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()

        original_repos = manager.list_repositories()

        # Write invalid JSON
        time.sleep(0.1)
        with open(self.config_file, "w") as f:
            f.write("{ invalid json }")

        # Check for changes
        changed = manager.check_for_config_changes()

        # Should not have changed (keeps previous valid config)
        self.assertFalse(changed, "Should not reload invalid configuration")
        self.assertEqual(manager.list_repositories(), original_repos)

    def test_config_watcher_thread(self):
        """Test configuration file watcher thread"""
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()

        # Start watching with short interval
        manager.start_watching_config(check_interval=0.1)

        # Give watcher time to start
        time.sleep(0.2)

        # Modify configuration
        updated_config = {
            "repositories": {
                "watched-repo": {
                    "path": str(self.repo_path),
                    "description": "Watched repository",
                    "language": "python",
                    "port": 8087,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "watched-repo",
                }
            }
        }

        with open(self.config_file, "w") as f:
            json.dump(updated_config, f)

        # Wait for watcher to detect changes
        time.sleep(0.5)

        # Verify configuration was reloaded
        self.assertIn("watched-repo", manager.list_repositories())


class TestSetupScript(unittest.TestCase):
    """Test setup script functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir) / "test-repo"
        self.repo_path.mkdir()
        self._init_git_repo(self.repo_path)

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def _init_git_repo(self, repo_path):
        """Initialize a git repository for testing"""
        os.system(f"cd {repo_path} && git init --quiet")
        os.system(f"cd {repo_path} && git config user.email 'test@example.com'")
        os.system(f"cd {repo_path} && git config user.name 'Test User'")
        os.system(
            f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet"
        )

    def test_setup_script_exists_and_executable(self):
        """Test that setup script exists and is executable"""
        setup_script = Path(__file__).parent.parent / "setup_multi_repo.py"
        self.assertTrue(setup_script.exists(), "Setup script should exist")
        self.assertTrue(
            os.access(setup_script, os.X_OK), "Setup script should be executable"
        )

    @unittest.skip("CLI removed in US001-2")
    def test_repository_cli_exists_and_executable(self):
        """Test that repository CLI exists and is executable"""
        cli_script = Path(__file__).parent.parent / "repository_cli.py"
        self.assertTrue(cli_script.exists(), "Repository CLI should exist")
        self.assertTrue(
            os.access(cli_script, os.X_OK), "Repository CLI should be executable"
        )


if __name__ == "__main__":
    unittest.main()
