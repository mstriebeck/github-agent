#!/usr/bin/env python3

"""
Tests for Simple Validation Functions

This module contains tests for the simple validation approach using
direct function calls in github_tools.py and codebase_tools.py.
"""

import logging
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import github_tools
import codebase_tools
from constants import Language


class TestGitHubValidation(unittest.TestCase):
    """Test cases for GitHub validation function."""

    def setUp(self):
        """Set up test environment."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

    def test_github_validate_empty_repos(self):
        """Test GitHub validation with empty repositories."""
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test_token'}), \
             patch('subprocess.run') as mock_run:
            
            # Mock git --version command
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "git version 2.39.0"
            
            # Should pass with empty repositories
            github_tools.validate(self.logger, {})

    def test_github_validate_missing_token(self):
        """Test GitHub validation with missing token."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as context:
                github_tools.validate(self.logger, {})
            
            self.assertIn("GITHUB_TOKEN environment variable not set", str(context.exception))

    def test_github_validate_empty_token(self):
        """Test GitHub validation with empty token."""
        with patch.dict(os.environ, {'GITHUB_TOKEN': '  '}):
            with self.assertRaises(RuntimeError) as context:
                github_tools.validate(self.logger, {})
            
            self.assertIn("GITHUB_TOKEN environment variable is empty", str(context.exception))

    def test_github_validate_git_not_available(self):
        """Test GitHub validation when git is not available."""
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test_token'}), \
             patch('subprocess.run') as mock_run:
            
            # Mock git command failure
            mock_run.side_effect = FileNotFoundError("git not found")
            
            with self.assertRaises(RuntimeError) as context:
                github_tools.validate(self.logger, {})
            
            self.assertIn("Git command not available", str(context.exception))

    def test_github_validate_with_valid_repo(self):
        """Test GitHub validation with a valid repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock git repository
            git_dir = os.path.join(temp_dir, ".git")
            os.makedirs(git_dir)
            
            # Mock repository config
            mock_repo_config = Mock()
            mock_repo_config.path = temp_dir
            repositories = {"test_repo": mock_repo_config}
            
            with patch.dict(os.environ, {'GITHUB_TOKEN': 'test_token'}), \
                 patch('subprocess.run') as mock_run:
                
                # Mock git commands
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "git version 2.39.0"
                
                # Should pass
                github_tools.validate(self.logger, repositories)

    def test_github_validate_with_invalid_repo(self):
        """Test GitHub validation with invalid repository."""
        # Mock repository config with non-existent path
        mock_repo_config = Mock()
        mock_repo_config.path = "/nonexistent/path"
        repositories = {"test_repo": mock_repo_config}
        
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test_token'}), \
             patch('subprocess.run') as mock_run:
            
            # Mock git --version command
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "git version 2.39.0"
            
            with self.assertRaises(RuntimeError) as context:
                github_tools.validate(self.logger, repositories)
            
            self.assertIn("Repository workspace does not exist", str(context.exception))


class TestCodebaseValidation(unittest.TestCase):
    """Test cases for codebase validation function."""

    def setUp(self):
        """Set up test environment."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

    def test_codebase_validate_empty_repos(self):
        """Test codebase validation with empty repositories."""
        # Should pass with empty repositories
        codebase_tools.validate(self.logger, {})

    def test_codebase_validate_with_valid_repo(self):
        """Test codebase validation with a valid repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock repository config
            mock_repo_config = Mock()
            mock_repo_config.path = temp_dir
            mock_repo_config.language = Language.PYTHON
            repositories = {"test_repo": mock_repo_config}
            
            with patch('subprocess.run') as mock_run:
                # Mock pyright command
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "pyright 1.1.0"
                
                # Should pass
                codebase_tools.validate(self.logger, repositories)

    def test_codebase_validate_workspace_not_accessible(self):
        """Test codebase validation with inaccessible workspace."""
        # Mock repository config with non-existent path
        mock_repo_config = Mock()
        mock_repo_config.path = "/nonexistent/path"
        mock_repo_config.language = Language.PYTHON
        repositories = {"test_repo": mock_repo_config}
        
        with self.assertRaises(RuntimeError) as context:
            codebase_tools.validate(self.logger, repositories)
        
        self.assertIn("Repository workspace does not exist", str(context.exception))

    def test_codebase_validate_pyright_not_available(self):
        """Test codebase validation when pyright is not available."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock repository config
            mock_repo_config = Mock()
            mock_repo_config.path = temp_dir
            mock_repo_config.language = Language.PYTHON
            repositories = {"test_repo": mock_repo_config}
            
            with patch('subprocess.run') as mock_run:
                # Mock pyright command failure
                mock_run.side_effect = FileNotFoundError("pyright not found")
                
                with self.assertRaises(RuntimeError) as context:
                    codebase_tools.validate(self.logger, repositories)
                
                self.assertIn("Python LSP tools not available", str(context.exception))


class TestValidationIntegration(unittest.TestCase):
    """Integration tests for validation functions."""

    def setUp(self):
        """Set up test environment."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

    def test_validation_integration_success(self):
        """Test successful validation of both GitHub and codebase services."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock git repository
            git_dir = os.path.join(temp_dir, ".git")
            os.makedirs(git_dir)
            
            # Mock repository config
            mock_repo_config = Mock()
            mock_repo_config.path = temp_dir
            mock_repo_config.language = Language.PYTHON
            repositories = {"test_repo": mock_repo_config}
            
            with patch.dict(os.environ, {'GITHUB_TOKEN': 'test_token'}), \
                 patch('subprocess.run') as mock_run:
                
                # Mock all subprocess calls
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "git version 2.39.0"
                
                # Test GitHub validation
                github_tools.validate(self.logger, repositories)
                
                # Test codebase validation  
                codebase_tools.validate(self.logger, repositories)

    def test_validation_order_independence(self):
        """Test that validation order doesn't matter."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock git repository
            git_dir = os.path.join(temp_dir, ".git")
            os.makedirs(git_dir)
            
            # Mock repository config
            mock_repo_config = Mock()
            mock_repo_config.path = temp_dir
            mock_repo_config.language = Language.PYTHON
            repositories = {"test_repo": mock_repo_config}
            
            with patch.dict(os.environ, {'GITHUB_TOKEN': 'test_token'}), \
                 patch('subprocess.run') as mock_run:
                
                # Mock all subprocess calls
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "git version 2.39.0"
                
                # Test different order
                codebase_tools.validate(self.logger, repositories)
                github_tools.validate(self.logger, repositories)


if __name__ == '__main__':
    unittest.main()
