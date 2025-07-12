#!/usr/bin/env python3

"""
Integration Tests for Multi-Repository Configuration and Management
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repository_manager import RepositoryManager, extract_repo_name_from_url


class TestMultiRepositoryIntegration(unittest.TestCase):
    """Integration tests for multi-repository configuration and management"""

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

        # Create test configuration
        self.test_config = {
            "repositories": {
                "project-a": {
                    "workspace": str(self.repo1_path),
                    "description": "Project A repository",
                    "language": "python",
                    "port": 8081,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "project-a",
                },
                "project-b": {
                    "workspace": str(self.repo2_path),
                    "description": "Project B repository",
                    "language": "swift",
                    "port": 8082,
                    "python_path": "/usr/bin/python3",
                    "github_owner": "test-owner",
                    "github_repo": "project-b",
                },
            }
        }

        self._write_config_file(self.test_config)

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

    def _write_config_file(self, config_data):
        """Write configuration data to test config file"""
        with open(self.config_file, "w") as f:
            json.dump(config_data, f)

    def test_repository_manager_multi_repo_workflow(self):
        """Test complete multi-repository workflow"""
        # 1. Initialize repository manager
        manager = RepositoryManager(config_path=str(self.config_file))

        # 2. Load configuration
        result = manager.load_configuration()
        self.assertTrue(result, "Should successfully load configuration")

        # 3. Check multi-repo mode
        self.assertTrue(manager.is_multi_repo_mode(), "Should be in multi-repo mode")

        # 4. List repositories
        repos = manager.list_repositories()
        self.assertEqual(
            set(repos), {"project-a", "project-b"}, "Should list all repositories"
        )

        # 5. Get repository configurations
        repo_a = manager.get_repository("project-a")
        self.assertIsNotNone(repo_a, "Should find project-a")
        assert repo_a
        self.assertEqual(repo_a.name, "project-a")
        self.assertEqual(repo_a.workspace, str(self.repo1_path))
        self.assertEqual(repo_a.description, "Project A repository")

        repo_b = manager.get_repository("project-b")
        self.assertIsNotNone(repo_b, "Should find project-b")
        assert repo_b
        self.assertEqual(repo_b.name, "project-b")
        self.assertEqual(repo_b.workspace, str(self.repo2_path))

        # 6. Test non-existent repository
        non_existent = manager.get_repository("non-existent")
        self.assertIsNone(non_existent, "Should not find non-existent repository")

        # 7. Get repository info
        info_a = manager.get_repository_info("project-a")
        self.assertIsNotNone(info_a, "Should get repository info")
        assert info_a
        self.assertTrue(info_a["exists"], "Repository should exist")
        self.assertEqual(info_a["name"], "project-a")

    def test_url_routing_extraction(self):
        """Test URL routing repository name extraction"""
        test_cases = [
            ("/mcp/project-a/", "project-a"),
            ("/mcp/my-work-repo/some/path", "my-work-repo"),
            ("mcp/test_repo/", "test_repo"),
            ("/mcp/project-123/", "project-123"),
            ("/api/other/", None),
            ("/mcp/", None),
            ("", None),
        ]

        for url_path, expected in test_cases:
            with self.subTest(url_path=url_path):
                result = extract_repo_name_from_url(url_path)
                self.assertEqual(result, expected, f"Failed for URL: {url_path}")

    def test_configuration_creation(self):
        """Test creating default configuration"""
        new_config_file = Path(self.temp_dir) / "new_config.json"
        manager = RepositoryManager(config_path=str(new_config_file))

        repo_configs = [
            {
                "name": "repo1",
                "workspace": str(self.repo1_path),
                "description": "Repository 1",
                "language": "python",
                "port": 8081,
                "python_path": "/usr/bin/python3",
                "github_owner": "test-owner",
                "github_repo": "repo1",
            },
            {
                "name": "repo2",
                "workspace": str(self.repo2_path),
                "description": "Repository 2",
                "language": "swift",
                "port": 8082,
                "python_path": "/usr/bin/python3",
                "github_owner": "test-owner",
                "github_repo": "repo2",
            },
        ]

        # Create configuration
        manager.create_default_config(repo_configs)

        # Verify file exists
        self.assertTrue(
            new_config_file.exists(), "Configuration file should be created"
        )

        # Load and verify content
        result = manager.load_configuration()
        self.assertTrue(result, "Should load created configuration")

        repos = manager.list_repositories()
        self.assertEqual(
            set(repos), {"repo1", "repo2"}, "Should have configured repositories"
        )

    def test_error_handling(self):
        """Test error handling scenarios"""
        # Test with clean environment (no fallback)
        with patch.dict(os.environ, {}, clear=True):
            manager = RepositoryManager(config_path="/non/existent/config.json")
            result = manager.load_configuration()
            self.assertFalse(result, "Should fail to load non-existent config")

            repos = manager.list_repositories()
            self.assertEqual(repos, [], "Should have no repositories")

            repo_info = manager.get_repository_info("any-repo")
            self.assertIsNone(repo_info, "Should return None for invalid repository")


if __name__ == "__main__":
    unittest.main()
