#!/usr/bin/env python3

"""
Test server initialization for Phase 1 Multi-Repository Support
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestServerInitialization(unittest.TestCase):
    """Test server initialization and basic functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "repositories.json"
        
        # Create test repository directories
        self.repo_path = Path(self.temp_dir) / "test-repo"
        self.repo_path.mkdir()
        self._init_git_repo(self.repo_path)
        
        # Create test configuration
        self.test_config = {
            "repositories": {
                "test-repo": {
                    "path": str(self.repo_path),
                    "description": "Test repository"
                }
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
        os.system(f"cd {repo_path} && git remote add origin https://github.com/test/test-repo.git")
        os.system(f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet")
    
    def _write_config_file(self, config_data):
        """Write configuration data to test config file"""
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f)
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_server_module_import(self):
        """Test that server module can be imported without errors"""
        # Mock the repository manager to avoid file system dependencies
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.load_configuration.return_value = True
            mock_repo_manager.list_repositories.return_value = ["test-repo"]
            mock_repo_manager.is_multi_repo_mode.return_value = True
            
            # Import should work without errors
            try:
                import github_mcp_server_multi_repo
                self.assertTrue(True, "Server module imported successfully")
            except Exception as e:
                self.fail(f"Failed to import server module: {e}")
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_github_api_context_creation(self):
        """Test GitHub API context can be created"""
        from repository_manager import RepositoryConfig
        from github_mcp_server_multi_repo import GitHubAPIContext
        
        repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        with patch('github_mcp_server_multi_repo.Github') as mock_github_class:
            mock_github = MagicMock()
            mock_github_class.return_value = mock_github
            
            # Create context
            context = GitHubAPIContext(repo_config)
            
            # Verify attributes
            self.assertEqual(context.repo_config, repo_config)
            self.assertEqual(context.github_token, "fake_token")
            self.assertIsNotNone(context.github)
    
    def test_repository_context_tools(self):
        """Test repository context tools can be called"""
        from repository_manager import RepositoryConfig
        from github_mcp_server_multi_repo import GitHubAPIContext
        
        repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        # Create context without GitHub (just for git commands)
        context = GitHubAPIContext(repo_config)
        
        # Test get_current_branch
        branch = context.get_current_branch()
        self.assertIn(branch, ['master', 'main'], "Should return valid branch name")
        
        # Test get_current_commit
        commit = context.get_current_commit()
        self.assertEqual(len(commit), 40, "Should return valid commit hash")
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_repository_manager_integration(self):
        """Test repository manager integration with server context"""
        from repository_manager import RepositoryManager
        from github_mcp_server_multi_repo import get_github_context
        
        # Create and configure repository manager
        manager = RepositoryManager(config_path=str(self.config_file))
        result = manager.load_configuration()
        self.assertTrue(result, "Should load configuration")
        
        # Mock the global repo_manager
        with patch('github_mcp_server_multi_repo.repo_manager', manager):
            with patch('github_mcp_server_multi_repo.Github') as mock_github_class:
                mock_github = MagicMock()
                mock_github_class.return_value = mock_github
                
                # Test getting GitHub context
                context = get_github_context("test-repo")
                self.assertIsNotNone(context, "Should create GitHub context")
                self.assertEqual(context.repo_config.name, "test-repo")
    
    def test_invalid_repository_handling(self):
        """Test handling of invalid repository requests"""
        from repository_manager import RepositoryManager
        from github_mcp_server_multi_repo import get_github_context
        
        # Create manager with empty configuration
        manager = RepositoryManager(config_path="/non/existent/config.json")
        
        with patch('github_mcp_server_multi_repo.repo_manager', manager):
            # Test invalid repository
            with self.assertRaises(ValueError) as context:
                get_github_context("invalid-repo")
            
            self.assertIn("Repository 'invalid-repo' not found", str(context.exception))


if __name__ == '__main__':
    unittest.main()
