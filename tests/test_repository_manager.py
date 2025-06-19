#!/usr/bin/env python3

"""
Tests for Repository Manager - Phase 1 Multi-Repository Support
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repository_manager import (
    RepositoryManager, 
    RepositoryConfig, 
    extract_repo_name_from_url, 
    validate_repo_name
)


class TestRepositoryConfig(unittest.TestCase):
    """Test RepositoryConfig dataclass"""
    
    def test_valid_config(self):
        """Test creating valid repository configuration"""
        config = RepositoryConfig(
            name="test-repo",
            path="/path/to/repo",
            description="Test repository"
        )
        
        self.assertEqual(config.name, "test-repo")
        self.assertEqual(config.path, os.path.abspath("/path/to/repo"))
        self.assertEqual(config.description, "Test repository")
    
    def test_empty_name_raises_error(self):
        """Test that empty name raises ValueError"""
        with self.assertRaises(ValueError) as context:
            RepositoryConfig(name="", path="/path/to/repo", description="Test")
        
        self.assertIn("Repository name cannot be empty", str(context.exception))
    
    def test_empty_path_raises_error(self):
        """Test that empty path raises ValueError"""
        with self.assertRaises(ValueError) as context:
            RepositoryConfig(name="test", path="", description="Test")
        
        self.assertIn("Repository path cannot be empty", str(context.exception))
    
    def test_path_normalization(self):
        """Test that paths are normalized and expanded"""
        config = RepositoryConfig(
            name="test",
            path="~/test-repo",
            description="Test"
        )
        
        expected_path = os.path.abspath(os.path.expanduser("~/test-repo"))
        self.assertEqual(config.path, expected_path)


class TestRepositoryManager(unittest.TestCase):
    """Test RepositoryManager class"""
    
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
                "repo1": {
                    "path": str(self.repo1_path),
                    "description": "Test repository 1"
                },
                "repo2": {
                    "path": str(self.repo2_path),
                    "description": "Test repository 2"
                }
            }
        }
    
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
    
    def test_initialization_with_custom_config_path(self):
        """Test initialization with custom config path"""
        manager = RepositoryManager(config_path=str(self.config_file))
        self.assertEqual(manager.config_path, self.config_file)
    
    def test_initialization_with_env_variable(self):
        """Test initialization with environment variable"""
        with patch.dict(os.environ, {'GITHUB_AGENT_REPO_CONFIG': str(self.config_file)}):
            manager = RepositoryManager()
            self.assertEqual(manager.config_path, self.config_file)
    
    def test_load_valid_configuration(self):
        """Test loading valid configuration"""
        self._write_config_file(self.test_config)
        
        manager = RepositoryManager(config_path=str(self.config_file))
        result = manager.load_configuration()
        
        self.assertTrue(result)
        self.assertEqual(len(manager.repositories), 2)
        self.assertIn("repo1", manager.repositories)
        self.assertIn("repo2", manager.repositories)
        
        repo1_config = manager.repositories["repo1"]
        self.assertEqual(repo1_config.name, "repo1")
        self.assertEqual(repo1_config.path, str(self.repo1_path))
        self.assertEqual(repo1_config.description, "Test repository 1")
    
    def test_load_configuration_missing_file(self):
        """Test loading configuration when file doesn't exist"""
        # Test without LOCAL_REPO_PATH and ensure environment is clean
        with patch.dict(os.environ, {}, clear=True):
            manager = RepositoryManager(config_path=str(self.config_file))
            result = manager.load_configuration()
            
            self.assertFalse(result)
    
    def test_load_configuration_fallback_mode(self):
        """Test fallback to single repository mode"""
        with patch.dict(os.environ, {'LOCAL_REPO_PATH': str(self.repo1_path)}):
            manager = RepositoryManager(config_path=str(self.config_file))
            result = manager.load_configuration()
            
            self.assertTrue(result)
            self.assertFalse(manager.is_multi_repo_mode())
            self.assertEqual(manager.list_repositories(), ["default"])
            
            default_repo = manager.get_repository("default")
            self.assertIsNotNone(default_repo)
            self.assertEqual(default_repo.path, str(self.repo1_path))
    
    def test_invalid_configuration_missing_repositories_key(self):
        """Test handling of invalid configuration missing 'repositories' key"""
        invalid_config = {"other_key": "value"}
        self._write_config_file(invalid_config)
        
        with patch.dict(os.environ, {}, clear=True):
            manager = RepositoryManager(config_path=str(self.config_file))
            result = manager.load_configuration()
            
            self.assertFalse(result)
    
    def test_invalid_configuration_missing_path(self):
        """Test handling of repository config missing required 'path' field"""
        invalid_config = {
            "repositories": {
                "repo1": {
                    "description": "Missing path"
                }
            }
        }
        self._write_config_file(invalid_config)
        
        with patch.dict(os.environ, {}, clear=True):
            manager = RepositoryManager(config_path=str(self.config_file))
            result = manager.load_configuration()
            
            self.assertFalse(result)
    
    def test_repository_validation_nonexistent_path(self):
        """Test validation fails for non-existent repository path"""
        invalid_config = {
            "repositories": {
                "repo1": {
                    "path": "/nonexistent/path",
                    "description": "Non-existent repo"
                }
            }
        }
        self._write_config_file(invalid_config)
        
        with patch.dict(os.environ, {}, clear=True):
            manager = RepositoryManager(config_path=str(self.config_file))
            result = manager.load_configuration()
            
            self.assertFalse(result)
    
    def test_repository_validation_not_git_repo(self):
        """Test validation fails for path that's not a git repository"""
        non_git_path = Path(self.temp_dir) / "not_git"
        non_git_path.mkdir()
        
        invalid_config = {
            "repositories": {
                "not_git": {
                    "path": str(non_git_path),
                    "description": "Not a git repo"
                }
            }
        }
        self._write_config_file(invalid_config)
        
        with patch.dict(os.environ, {}, clear=True):
            manager = RepositoryManager(config_path=str(self.config_file))
            result = manager.load_configuration()
            
            self.assertFalse(result)
    
    def test_get_repository(self):
        """Test getting repository configuration by name"""
        self._write_config_file(self.test_config)
        
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()
        
        repo1 = manager.get_repository("repo1")
        self.assertIsNotNone(repo1)
        self.assertEqual(repo1.name, "repo1")
        
        nonexistent = manager.get_repository("nonexistent")
        self.assertIsNone(nonexistent)
    
    def test_list_repositories(self):
        """Test listing all repository names"""
        self._write_config_file(self.test_config)
        
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()
        
        repos = manager.list_repositories()
        self.assertEqual(set(repos), {"repo1", "repo2"})
    
    def test_get_repository_info(self):
        """Test getting repository information dictionary"""
        self._write_config_file(self.test_config)
        
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()
        
        info = manager.get_repository_info("repo1")
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "repo1")
        self.assertEqual(info["path"], str(self.repo1_path))
        self.assertEqual(info["description"], "Test repository 1")
        self.assertTrue(info["exists"])
        
        nonexistent_info = manager.get_repository_info("nonexistent")
        self.assertIsNone(nonexistent_info)
    
    def test_is_multi_repo_mode(self):
        """Test checking if running in multi-repository mode"""
        # Test multi-repo mode
        self._write_config_file(self.test_config)
        manager = RepositoryManager(config_path=str(self.config_file))
        manager.load_configuration()
        self.assertTrue(manager.is_multi_repo_mode())
        
        # Test single-repo fallback mode
        with patch.dict(os.environ, {'LOCAL_REPO_PATH': str(self.repo1_path)}):
            manager2 = RepositoryManager(config_path="/nonexistent/config.json")
            manager2.load_configuration()
            self.assertFalse(manager2.is_multi_repo_mode())
    
    def test_create_default_config(self):
        """Test creating default configuration file"""
        manager = RepositoryManager(config_path=str(self.config_file))
        
        repo_configs = [
            {
                "name": "test1",
                "path": str(self.repo1_path),
                "description": "Test repo 1"
            },
            {
                "name": "test2",
                "path": str(self.repo2_path),
                "description": "Test repo 2"
            }
        ]
        
        manager.create_default_config(repo_configs)
        
        # Verify file was created
        self.assertTrue(self.config_file.exists())
        
        # Verify content
        with open(self.config_file, 'r') as f:
            config_data = json.load(f)
        
        self.assertIn("repositories", config_data)
        self.assertEqual(len(config_data["repositories"]), 2)
        self.assertIn("test1", config_data["repositories"])
        self.assertIn("test2", config_data["repositories"])


class TestUtilityFunctions(unittest.TestCase):
    """Test utility functions"""
    
    def test_extract_repo_name_from_url(self):
        """Test URL repository name extraction"""
        test_cases = [
            ("/mcp/my-project/", "my-project"),
            ("/mcp/work-stuff", "work-stuff"),
            ("/mcp/github-agent/some/path", "github-agent"),
            ("mcp/test-repo/", "test-repo"),
            ("/api/other/", None),
            ("/mcp/", None),
            ("", None),
            ("/", None)
        ]
        
        for url_path, expected in test_cases:
            with self.subTest(url_path=url_path):
                result = extract_repo_name_from_url(url_path)
                self.assertEqual(result, expected)
    
    def test_validate_repo_name(self):
        """Test repository name validation"""
        valid_names = [
            "my-project",
            "work_stuff",
            "repo123",
            "test-repo-1",
            "a",
            "ABC-123_def"
        ]
        
        invalid_names = [
            "",
            "repo with spaces",
            "repo@special",
            "repo.with.dots",
            "repo/with/slashes",
            "repo:with:colons",
            None
        ]
        
        for name in valid_names:
            with self.subTest(name=name):
                self.assertTrue(validate_repo_name(name))
        
        for name in invalid_names:
            with self.subTest(name=name):
                self.assertFalse(validate_repo_name(name))


if __name__ == '__main__':
    unittest.main()
