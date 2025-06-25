#!/usr/bin/env python3

"""
Tests for Multi-Repository Server - Phase 1 Multi-Repository Support
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import asyncio

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We need to import the server components
from fastapi.testclient import TestClient


class TestMultiRepoServerSetup(unittest.TestCase):
    """Test multi-repository server setup and configuration"""
    
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
                "test-repo1": {
                    "path": str(self.repo1_path),
                    "description": "Test repository 1"
                },
                "test-repo2": {
                    "path": str(self.repo2_path),
                    "description": "Test repository 2"
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
        os.system(f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet")
    
    def _write_config_file(self, config_data):
        """Write configuration data to test config file"""
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f)
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_server_initialization_with_config(self):
        """Test server initializes correctly with multi-repo config"""
        # We need to patch the repository manager to use our test config
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.load_configuration.return_value = True
            mock_repo_manager.list_repositories.return_value = ["test-repo1", "test-repo2"]
            mock_repo_manager.is_multi_repo_mode.return_value = True
            
            # Import and test the server
            from github_mcp_server_multi_repo import app
            
            with TestClient(app) as client:
                # Test root endpoint
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                
                data = response.json()
                self.assertEqual(data["name"], "GitHub PR Agent MCP Server - Multi-Repository")
                self.assertEqual(data["version"], "2.0.0")
                self.assertTrue(data["multi_repo_mode"])
                self.assertEqual(data["repositories"], ["test-repo1", "test-repo2"])
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_health_endpoint_multi_repo(self):
        """Test health endpoint with multi-repository configuration"""
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.list_repositories.return_value = ["test-repo1", "test-repo2"]
            mock_repo_manager.is_multi_repo_mode.return_value = True
            
            from github_mcp_server_multi_repo import app
            
            with TestClient(app) as client:
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
                
                data = response.json()
                self.assertEqual(data["status"], "healthy")
                self.assertTrue(data["github_configured"])
                self.assertTrue(data["multi_repo_mode"])
                self.assertEqual(data["repositories_count"], 2)
                self.assertEqual(data["repositories"], ["test-repo1", "test-repo2"])
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_status_endpoint_multi_repo(self):
        """Test status endpoint with repository details"""
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.list_repositories.return_value = ["test-repo1"]
            mock_repo_manager.is_multi_repo_mode.return_value = True
            mock_repo_manager.get_repository_info.return_value = {
                "name": "test-repo1",
                "path": str(self.repo1_path),
                "description": "Test repository 1",
                "exists": True
            }
            
            from github_mcp_server_multi_repo import app
            
            with TestClient(app) as client:
                response = client.get("/status")
                self.assertEqual(response.status_code, 200)
                
                data = response.json()
                self.assertTrue(data["server"]["github_configured"])
                self.assertTrue(data["server"]["multi_repo_mode"])
                self.assertIn("test-repo1", data["repositories"])
                self.assertEqual(data["repositories"]["test-repo1"]["name"], "test-repo1")


class TestRepositoryRouting(unittest.TestCase):
    """Test URL routing for different repositories"""
    
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
        os.system(f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet")
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_mcp_endpoint_valid_repository(self):
        """Test MCP endpoint with valid repository name"""
        from repository_manager import RepositoryConfig
        
        mock_repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = mock_repo_config
            
            from github_mcp_server_multi_repo import app
            
            with TestClient(app) as client:
                # Test GET (SSE) endpoint
                response = client.get("/mcp/test-repo/")
                # SSE endpoint should return 200 with event-stream
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/event-stream", response.headers.get("content-type", ""))
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_mcp_endpoint_invalid_repository(self):
        """Test MCP endpoint with invalid repository name"""
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = None
            mock_repo_manager.list_repositories.return_value = ["valid-repo1", "valid-repo2"]
            
            from github_mcp_server_multi_repo import app
            
            with TestClient(app) as client:
                # Test GET (SSE) endpoint
                response = client.get("/mcp/invalid-repo/")
                self.assertEqual(response.status_code, 404)
                
                data = response.json()
                self.assertIn("error", data)
                self.assertIn("Repository 'invalid-repo' not found", data["error"])
                self.assertEqual(data["available_repositories"], ["valid-repo1", "valid-repo2"])
                
                # Test POST endpoint
                response = client.post("/mcp/invalid-repo/", json={"method": "initialize"})
                self.assertEqual(response.status_code, 404)
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_mcp_post_initialize(self):
        """Test MCP POST initialize method with repository context"""
        from repository_manager import RepositoryConfig
        
        mock_repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = mock_repo_config
            
            from github_mcp_server_multi_repo import app
            
            with TestClient(app) as client:
                response = client.post("/mcp/test-repo/", json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {}
                })
                
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["status"], "queued")
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_mcp_post_tools_list(self):
        """Test MCP POST tools/list method with repository context"""
        from repository_manager import RepositoryConfig
        
        mock_repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = mock_repo_config
            
            from github_mcp_server_multi_repo import app
            
            with TestClient(app) as client:
                response = client.post("/mcp/test-repo/", json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {}
                })
                
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["status"], "queued")


class TestGitHubAPIContext(unittest.TestCase):
    """Test GitHub API context creation with repository information"""
    
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
        os.system(f"cd {repo_path} && git remote add origin https://github.com/test/test-repo.git")
        os.system(f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet")
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_github_context_creation(self):
        """Test creating GitHub API context with repository config"""
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
            
            context = GitHubAPIContext(repo_config)
            
            self.assertEqual(context.repo_config, repo_config)
            self.assertEqual(context.github_token, "fake_token")
            self.assertIsNotNone(context.github)
    
    def test_get_current_branch(self):
        """Test getting current branch from repository context"""
        from repository_manager import RepositoryConfig
        from github_mcp_server_multi_repo import GitHubAPIContext
        
        repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        context = GitHubAPIContext(repo_config)
        
        # This should work with our test git repo
        branch = context.get_current_branch()
        # Git repos initialized with git init use 'master' or 'main' as default branch
        self.assertIn(branch, ['master', 'main'])
    
    def test_get_current_commit(self):
        """Test getting current commit from repository context"""
        from repository_manager import RepositoryConfig
        from github_mcp_server_multi_repo import GitHubAPIContext
        
        repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        context = GitHubAPIContext(repo_config)
        
        commit = context.get_current_commit()
        # Should return a valid git commit hash
        self.assertEqual(len(commit), 40)  # Git SHA-1 hashes are 40 characters
        self.assertTrue(all(c in '0123456789abcdef' for c in commit.lower()))


class TestRepositoryContextTools(unittest.TestCase):
    """Test tools that use repository context"""
    
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
        os.system(f"cd {repo_path} && git remote add origin https://github.com/test/test-repo.git")
        os.system(f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet")
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_execute_get_current_branch(self):
        """Test execute_get_current_branch with repository context"""
        from repository_manager import RepositoryConfig
        from github_mcp_server_multi_repo import execute_get_current_branch
        
        repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = repo_config
            
            # Run the async function
            result = asyncio.run(execute_get_current_branch("test-repo"))
            
            # Parse the JSON result
            data = json.loads(result)
            self.assertIn("branch", data)
            self.assertEqual(data["repo_config"], "test-repo")
            # Branch should be master or main
            self.assertIn(data["branch"], ['master', 'main'])
    
    @patch.dict(os.environ, {'GITHUB_TOKEN': 'fake_token'})
    def test_execute_get_current_commit(self):
        """Test execute_get_current_commit with repository context"""
        from repository_manager import RepositoryConfig
        from github_mcp_server_multi_repo import execute_get_current_commit
        
        repo_config = RepositoryConfig(
            name="test-repo",
            path=str(self.repo_path),
            description="Test repository"
        )
        
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = repo_config
            
            # Run the async function
            result = asyncio.run(execute_get_current_commit("test-repo"))
            
            # Parse the JSON result
            data = json.loads(result)
            self.assertIn("commit", data)
            self.assertEqual(data["repo_config"], "test-repo")
            # Commit should be a valid SHA
            commit = data["commit"]
            self.assertEqual(len(commit), 40)
            self.assertTrue(all(c in '0123456789abcdef' for c in commit.lower()))
    
    def test_get_github_context_invalid_repo(self):
        """Test get_github_context with invalid repository name"""
        from github_mcp_server_multi_repo import get_github_context
        
        with patch('github_mcp_server_multi_repo.repo_manager') as mock_repo_manager:
            mock_repo_manager.get_repository.return_value = None
            
            with self.assertRaises(ValueError) as context:
                get_github_context("invalid-repo")
            
            self.assertIn("Repository 'invalid-repo' not found", str(context.exception))


if __name__ == '__main__':
    unittest.main()
