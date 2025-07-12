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
        # Create a Python file to satisfy repository validation
        os.system(f"cd {repo_path} && echo 'print(\"Hello World\")' > main.py")
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
                    "workspace": str(self.repo_path),
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
        # Create a Python file to satisfy repository validation
        os.system(f"cd {repo_path} && echo 'print(\"Hello World\")' > main.py")
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
                    "workspace": str(self.repo_path),
                    "description": "Initial repository",
                    "language": "python",
                    "port": 8083,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "initial-repo",
                },
                "new-repo": {
                    "workspace": str(self.repo_path),
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
                    "workspace": str(self.repo_path),
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
                    "workspace": str(self.repo_path),
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


if __name__ == "__main__":
    unittest.main()
