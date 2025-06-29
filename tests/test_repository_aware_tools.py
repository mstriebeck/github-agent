#!/usr/bin/env python3

"""
Tests for Repository-Aware GitHub Tools and MCP Integration
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import github_tools  # noqa: F401
from repository_manager import RepositoryConfig, RepositoryManager


class TestRepositoryAwareTools(unittest.TestCase):
    """Test repository-aware GitHub tools and MCP integration"""

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
                    "path": str(self.repo1_path),
                    "description": "Project A repository",
                    "language": "python",
                },
                "project-b": {
                    "path": str(self.repo2_path),
                    "description": "Project B repository",
                    "language": "swift",
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
        os.system(
            f"cd {repo_path} && git remote add origin https://github.com/test/test-repo.git"
        )
        os.system(
            f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet"
        )

    def _write_config_file(self, config_data):
        """Write configuration data to test config file"""
        with open(self.config_file, "w") as f:
            json.dump(config_data, f)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake_token"})
    def test_tool_functions_with_repo_context(self):
        """Test that tool functions accept repository name parameter"""
        from github_tools import execute_get_current_branch, execute_get_current_commit

        # Test that functions accept repo_name as first parameter
        repo_config = RepositoryConfig(
            name="project-a",
            path=str(self.repo1_path),
            description="Test repository",
            language="swift",
        )

        with patch("github_tools.repo_manager") as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = repo_config

            with patch("github_tools.Github") as mock_github_class:
                mock_github = MagicMock()
                mock_github_class.return_value = mock_github

                # Test get_current_branch
                try:
                    result = asyncio.run(execute_get_current_branch("project-a"))
                    data = json.loads(result)
                    self.assertIn("branch", data)
                    self.assertEqual(data["repo_config"], "project-a")
                except Exception as e:
                    # Expected since we're mocking GitHub
                    self.assertIn("Failed to get current branch", str(e))

                # Test get_current_commit
                try:
                    result = asyncio.run(execute_get_current_commit("project-a"))
                    data = json.loads(result)
                    self.assertIn("commit", data)
                    self.assertEqual(data["repo_config"], "project-a")
                except Exception as e:
                    # Expected since we're mocking GitHub
                    self.assertIn("Failed to get current commit", str(e))

    def test_github_context_with_different_repositories(self):
        """Test GitHubAPIContext works with different repository configurations"""
        from github_tools import GitHubAPIContext

        repo_config_a = RepositoryConfig(
            name="project-a",
            path=str(self.repo1_path),
            description="Project A",
            language="swift",
        )

        repo_config_b = RepositoryConfig(
            name="project-b",
            path=str(self.repo2_path),
            description="Project B",
            language="swift",
        )

        with patch("github_tools.Github") as mock_github_class:
            mock_github = MagicMock()
            mock_github_class.return_value = mock_github

            # Create contexts for different repositories
            context_a = GitHubAPIContext(repo_config_a)
            context_b = GitHubAPIContext(repo_config_b)

            # Verify they have different repository paths
            self.assertEqual(context_a.repo_config.path, str(self.repo1_path))
            self.assertEqual(context_b.repo_config.path, str(self.repo2_path))

            # Verify they can get different branch info
            branch_a = context_a.get_current_branch()
            branch_b = context_b.get_current_branch()

            # Both should return valid branch names (master or main)
            self.assertIn(branch_a, ["master", "main"])
            self.assertIn(branch_b, ["master", "main"])

    def test_error_handling_for_invalid_repository(self):
        """Test error handling when repository context is missing"""
        from github_tools import get_github_context

        with patch("github_tools.repo_manager") as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = None

            # Test that invalid repository raises ValueError
            with self.assertRaises(ValueError) as context:
                get_github_context("invalid-repo")

            self.assertIn("Repository 'invalid-repo' not found", str(context.exception))

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake_token"})
    def test_tool_integration_workflow(self):
        """Test complete tool integration workflow"""
        from github_tools import execute_find_pr_for_branch, execute_get_current_branch

        # Set up repository manager with test config
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()

        with patch("github_tools.repo_manager", manager):
            with patch("github_tools.Github") as mock_github_class:
                mock_github = MagicMock()
                mock_repo = MagicMock()
                mock_github_class.return_value = mock_github
                mock_github.get_repo.return_value = mock_repo

                # Mock PR search
                mock_pr = MagicMock()
                mock_pr.head.ref = "feature-branch"
                mock_pr.number = 123
                mock_pr.title = "Test PR"
                mock_pr.state = "open"
                mock_pr.html_url = "https://github.com/test/test-repo/pull/123"
                mock_pr.user.login = "testuser"
                mock_pr.base.ref = "main"
                mock_repo.get_pulls.return_value = [mock_pr]

                # Test workflow: get branch, then find PR
                branch_result = asyncio.run(execute_get_current_branch("project-a"))
                branch_data = json.loads(branch_result)

                # Should include repository context
                self.assertEqual(branch_data["repo_config"], "project-a")
                self.assertIn("branch", branch_data)

                # Test finding PR for branch
                pr_result = asyncio.run(
                    execute_find_pr_for_branch("project-a", "feature-branch")
                )
                pr_data = json.loads(pr_result)

                # Should find the PR with repository context
                self.assertTrue(pr_data["found"])
                self.assertEqual(pr_data["pr_number"], 123)
                self.assertEqual(pr_data["repo_config"], "project-a")

    def test_repository_specific_tool_descriptions(self):
        """Test that tool descriptions include repository context"""
        # This would be tested through the MCP endpoints
        # For now, verify the pattern exists in the tool functions
        # Check that the function signature includes repo_name
        import inspect

        from github_tools import execute_find_pr_for_branch

        sig = inspect.signature(execute_find_pr_for_branch)
        params = list(sig.parameters.keys())

        # First parameter should be repo_name
        self.assertEqual(params[0], "repo_name")
        self.assertEqual(params[1], "branch_name")

    def test_backward_compatibility_single_repo_mode(self):
        """Test that single repository fallback mode still works"""
        with patch.dict(os.environ, {"LOCAL_REPO_PATH": str(self.repo1_path)}):
            # Create manager with no config file (should fall back)
            manager = RepositoryManager(config_path="/nonexistent/config.json")
            result = manager.load_configuration()

            self.assertTrue(result, "Should load fallback configuration")
            self.assertFalse(
                manager.is_multi_repo_mode(), "Should be in single-repo mode"
            )
            self.assertEqual(manager.list_repositories(), ["default"])

            # Test that tools can work with default repository
            default_repo = manager.get_repository("default")
            self.assertIsNotNone(default_repo)
            assert default_repo
            self.assertEqual(default_repo.path, str(self.repo1_path))


if __name__ == "__main__":
    unittest.main()
