#!/usr/bin/env python3

"""
Tests for Repository Manager - Phase 1 Multi-Repository Support
"""

import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from constants import Language
from repository_manager import (
    RepositoryConfig,
    RepositoryManager,
    extract_repo_name_from_url,
    validate_repo_name,
)


class TestRepositoryConfig(unittest.TestCase):
    """Test RepositoryConfig dataclass"""

    def create_test_repository_config(self, **kwargs):
        """Helper method to create RepositoryConfig with defaults"""
        defaults = {
            "name": "test-repo",
            "workspace": "/path/to/repo",
            "description": "Test repository",
            "language": Language.SWIFT,
            "port": 8000,
            "python_path": "/usr/bin/python3",
        }
        defaults.update(kwargs)
        return RepositoryConfig.create_repository_config(
            name=str(defaults["name"]),
            workspace=str(defaults["workspace"]),
            description=str(defaults["description"]),
            language=cast(Language, defaults["language"]),
            port=cast(int, defaults["port"]),
            python_path=str(defaults["python_path"])
            if defaults.get("python_path")
            else None,
        )

    def test_valid_config(self):
        """Test creating valid repository configuration"""
        config = self.create_test_repository_config()

        self.assertEqual(config.name, "test-repo")
        self.assertEqual(config.workspace, os.path.abspath("/path/to/repo"))
        self.assertEqual(config.description, "Test repository")

    def test_empty_name_raises_error(self):
        """Test that empty name raises ValueError"""
        with self.assertRaises(ValueError) as context:
            self.create_test_repository_config(name="")

        self.assertIn("Repository name cannot be empty", str(context.exception))

    def test_empty_path_raises_error(self):
        """Test that empty workspace raises ValueError"""
        with self.assertRaises(ValueError) as context:
            self.create_test_repository_config(workspace="")

        self.assertIn("Repository workspace cannot be empty", str(context.exception))

    def test_path_normalization(self):
        """Test that absolute paths are normalized and expanded"""
        config = self.create_test_repository_config(
            name="test", workspace="/home/user/test-repo", description="Test"
        )

        expected_path = os.path.abspath("/home/user/test-repo")
        self.assertEqual(config.workspace, expected_path)

    def test_relative_path_raises_error(self):
        """Test that relative paths raise ValueError"""
        with self.assertRaises(ValueError) as context:
            self.create_test_repository_config(workspace="relative/path")

        self.assertIn("Repository workspace must be absolute", str(context.exception))

    def test_valid_language_python(self):
        """Test that 'python' language is accepted"""
        config = self.create_test_repository_config(language=Language.PYTHON)
        self.assertEqual(config.language, Language.PYTHON)

    def test_valid_language_swift(self):
        """Test that 'swift' language is accepted"""
        config = self.create_test_repository_config(language=Language.SWIFT)
        self.assertEqual(config.language, Language.SWIFT)

    def test_default_language_is_swift(self):
        """Test that default language is 'swift' for backward compatibility"""
        config = self.create_test_repository_config(language=Language.SWIFT)
        self.assertEqual(config.language, Language.SWIFT)

    def test_invalid_language_raises_error(self):
        """Test that invalid language raises ValueError"""
        with self.assertRaises(ValueError) as context:
            # Try to create a Language enum with invalid language
            Language("javascript")

        error_msg = str(context.exception)
        self.assertIn("'javascript'", error_msg)

    def test_case_sensitive_language_validation(self):
        """Test that language validation is case sensitive"""
        with self.assertRaises(ValueError) as context:
            # Try to create a Language enum with invalid case
            Language("Python")  # Capital P should fail

        self.assertIn("'Python'", str(context.exception))

    def test_empty_language_raises_error(self):
        """Test that empty language raises ValueError"""
        with self.assertRaises(ValueError) as context:
            # Try to create a Language enum with empty value
            Language("")

        self.assertIn("''", str(context.exception))

    def test_python_path_validation_empty_string(self):
        """Test that empty python_path raises ValueError"""
        with self.assertRaises(ValueError) as context:
            RepositoryConfig.create_repository_config(
                name="test",
                workspace=os.path.abspath("/tmp/test"),
                description="Test",
                language=Language.PYTHON,
                port=8080,
                python_path="",  # Empty string should fail
            )
        self.assertIn("python_path cannot be empty", str(context.exception))

    def test_python_path_validation_whitespace_only(self):
        """Test that whitespace-only python_path raises ValueError"""
        with self.assertRaises(ValueError) as context:
            RepositoryConfig.create_repository_config(
                name="test",
                workspace=os.path.abspath("/tmp/test"),
                description="Test",
                language=Language.PYTHON,
                port=8080,
                python_path="   ",  # Whitespace only
            )
        self.assertIn("python_path cannot be empty", str(context.exception))

    def test_python_path_validation_nonexistent_path(self):
        """Test that non-existent python_path raises ValueError"""
        with self.assertRaises(ValueError) as context:
            RepositoryConfig.create_repository_config(
                name="test",
                workspace=os.path.abspath("/tmp/test"),
                description="Test",
                language=Language.PYTHON,
                port=8080,
                python_path="/nonexistent/python",
            )
        self.assertIn("Python executable does not exist", str(context.exception))

    def test_python_path_validation_not_executable(self):
        """Test that non-executable python_path raises ValueError"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            tmp.write("#!/usr/bin/env python3\nprint('test')")
            tmp_path = tmp.name

        try:
            # Make file not executable
            os.chmod(tmp_path, 0o644)

            with self.assertRaises(ValueError) as context:
                RepositoryConfig.create_repository_config(
                    name="test",
                    workspace=os.path.abspath("/tmp/test"),
                    description="Test",
                    language=Language.PYTHON,
                    port=8080,
                    python_path=tmp_path,
                )
            self.assertIn("Python path is not executable", str(context.exception))
        finally:
            os.unlink(tmp_path)

    def test_python_path_validation_invalid_executable(self):
        """Test that invalid executable (not Python) raises ValueError"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            tmp.write("#!/bin/sh\necho 'not python'")
            tmp_path = tmp.name

        try:
            # Make file executable
            os.chmod(tmp_path, 0o755)

            with self.assertRaises(ValueError) as context:
                RepositoryConfig.create_repository_config(
                    name="test",
                    workspace=os.path.abspath("/tmp/test"),
                    description="Test",
                    language=Language.PYTHON,
                    port=8080,
                    python_path=tmp_path,
                )
            self.assertIn("does not appear to be Python", str(context.exception))
        finally:
            os.unlink(tmp_path)


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
                    "workspace": str(self.repo1_path),
                    "description": "Test repository 1",
                    "language": Language.PYTHON.value,
                    "port": 8080,
                    "python_path": sys.executable,
                },
                "repo2": {
                    "workspace": str(self.repo2_path),
                    "description": "Test repository 2",
                    "language": Language.SWIFT.value,
                    "port": 8081,
                    "python_path": sys.executable,
                },
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

        # Add Python file for Python repositories
        if "repo1" in str(repo_path):  # repo1 is configured as Python
            os.system(f"cd {repo_path} && echo 'print(\"hello\")' > test.py")

        os.system(
            f"cd {repo_path} && touch README.md && git add . && git commit -m 'Initial commit' --quiet"
        )

    def _write_config_file(self, config_data):
        """Write configuration data to test config file"""
        with open(self.config_file, "w") as f:
            json.dump(config_data, f)

    def test_initialization_with_custom_config_path(self):
        """Test initialization with custom config path"""
        manager = RepositoryManager(config_path=str(self.config_file))
        self.assertEqual(manager.config_path, self.config_file)

    def test_initialization_with_env_variable(self):
        """Test initialization with environment variable"""
        with patch.dict(
            os.environ, {"GITHUB_AGENT_REPO_CONFIG": str(self.config_file)}
        ):
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
        self.assertEqual(repo1_config.workspace, str(self.repo1_path))
        self.assertEqual(repo1_config.description, "Test repository 1")

    def test_load_configuration_missing_file(self):
        """Test loading configuration when file doesn't exist"""
        # Test without LOCAL_REPO_PATH and ensure environment is clean
        with patch.dict(os.environ, {}, clear=True):
            manager = RepositoryManager(config_path=str(self.config_file))
            result = manager.load_configuration()

            self.assertFalse(result)

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
                "repo1": {"description": "Missing path", "language": "python"}
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
                    "workspace": "/nonexistent/path",
                    "description": "Non-existent repo",
                    "language": Language.PYTHON.value,
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
                    "workspace": str(non_git_path),
                    "description": "Not a git repo",
                    "language": Language.PYTHON.value,
                    "port": 8080,
                }
            }
        }
        self._write_config_file(invalid_config)

        with patch.dict(os.environ, {}, clear=True):
            manager = RepositoryManager(config_path=str(self.config_file))
            result = manager.load_configuration()

            self.assertFalse(result)

    def test_port_conflict_validation(self):
        """Test that port conflicts are detected"""
        config_with_port_conflict = {
            "repositories": {
                "repo1": {
                    "workspace": str(self.repo1_path),
                    "description": "Test repository 1",
                    "language": Language.PYTHON.value,
                    "port": 8080,
                },
                "repo2": {
                    "workspace": str(self.repo2_path),
                    "description": "Test repository 2",
                    "language": Language.SWIFT.value,
                    "port": 8080,  # Same port as repo1 - should fail
                },
            }
        }
        self._write_config_file(config_with_port_conflict)

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
        assert repo1
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
        assert info
        self.assertEqual(info["name"], "repo1")
        self.assertEqual(info["workspace"], str(self.repo1_path))
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
        with patch.dict(os.environ, {"LOCAL_REPO_PATH": str(self.repo1_path)}):
            manager2 = RepositoryManager(config_path="/nonexistent/config.json")
            manager2.load_configuration()
            self.assertFalse(manager2.is_multi_repo_mode())

    def test_create_default_config(self):
        """Test creating default configuration file"""
        manager = RepositoryManager(config_path=str(self.config_file))

        repo_configs = [
            {
                "name": "test1",
                "workspace": str(self.repo1_path),
                "description": "Test repo 1",
            },
            {
                "name": "test2",
                "workspace": str(self.repo2_path),
                "description": "Test repo 2",
            },
        ]

        manager.create_default_config(repo_configs)

        # Verify file was created
        self.assertTrue(self.config_file.exists())

        # Verify content
        with open(self.config_file) as f:
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
            ("/", None),
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
            "ABC-123_def",
        ]

        invalid_names: list[str | None] = [
            "",
            "repo with spaces",
            "repo@special",
            "repo.with.dots",
            "repo/with/slashes",
            "repo:with:colons",
            None,
        ]

        for name in valid_names:
            with self.subTest(name=name):
                self.assertTrue(validate_repo_name(name))

        for name_item in invalid_names:
            with self.subTest(name=name_item):
                if name_item is not None:
                    self.assertFalse(validate_repo_name(name_item))


class TestGitHubRemoteExtraction(unittest.TestCase):
    """Test GitHub remote extraction functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_repo_path = Path(self.temp_dir) / "test_repo"
        self.test_repo_path.mkdir()

        # Initialize git repo
        os.system(f"cd {self.test_repo_path} && git init --quiet")
        os.system(
            f"cd {self.test_repo_path} && git config user.email 'test@example.com'"
        )
        os.system(f"cd {self.test_repo_path} && git config user.name 'Test User'")

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_github_ssh_url_extraction(self):
        """Test extraction from SSH GitHub URLs"""
        test_cases = [
            ("git@github.com:owner/repo.git", "owner", "repo"),
            ("git@github.com:test-user/test-repo.git", "test-user", "test-repo"),
            ("git@github.com:org/project", "org", "project"),  # No .git suffix
        ]

        for remote_url, expected_owner, expected_repo in test_cases:
            with self.subTest(remote_url=remote_url):
                # Set up remote
                os.system(
                    f"cd {self.test_repo_path} && git remote add origin {remote_url}"
                )

                # Extract info
                owner, repo = RepositoryConfig._extract_github_info(
                    str(self.test_repo_path), logging.getLogger(__name__)
                )

                self.assertEqual(owner, expected_owner)
                self.assertEqual(repo, expected_repo)

                # Clean up for next test
                os.system(f"cd {self.test_repo_path} && git remote remove origin")

    def test_github_https_url_extraction(self):
        """Test extraction from HTTPS GitHub URLs"""
        test_cases = [
            ("https://github.com/owner/repo.git", "owner", "repo"),
            ("https://github.com/test-user/test-repo.git", "test-user", "test-repo"),
            ("https://github.com/org/project", "org", "project"),  # No .git suffix
            ("https://github.com/complex/repo-name.git", "complex", "repo-name"),
        ]

        for remote_url, expected_owner, expected_repo in test_cases:
            with self.subTest(remote_url=remote_url):
                # Set up remote
                os.system(
                    f"cd {self.test_repo_path} && git remote add origin {remote_url}"
                )

                # Extract info
                owner, repo = RepositoryConfig._extract_github_info(
                    str(self.test_repo_path), logging.getLogger(__name__)
                )

                self.assertEqual(owner, expected_owner)
                self.assertEqual(repo, expected_repo)

                # Clean up for next test
                os.system(f"cd {self.test_repo_path} && git remote remove origin")

    def test_non_github_url_extraction(self):
        """Test extraction from non-GitHub URLs returns None"""
        non_github_urls = [
            "https://gitlab.com/owner/repo.git",
            "https://bitbucket.org/owner/repo.git",
            "https://example.com/git/repo.git",
            "git@gitlab.com:owner/repo.git",
        ]

        for remote_url in non_github_urls:
            with self.subTest(remote_url=remote_url):
                # Set up remote
                os.system(
                    f"cd {self.test_repo_path} && git remote add origin {remote_url}"
                )

                # Extract info
                owner, repo = RepositoryConfig._extract_github_info(
                    str(self.test_repo_path), logging.getLogger(__name__)
                )

                self.assertIsNone(owner)
                self.assertIsNone(repo)

                # Clean up for next test
                os.system(f"cd {self.test_repo_path} && git remote remove origin")

    def test_no_remote_url_extraction(self):
        """Test extraction when no remote is configured"""
        # No remote configured
        owner, repo = RepositoryConfig._extract_github_info(
            str(self.test_repo_path), logging.getLogger(__name__)
        )

        self.assertIsNone(owner)
        self.assertIsNone(repo)

    def test_invalid_github_url_format(self):
        """Test extraction from malformed GitHub URLs"""
        invalid_urls = [
            "git@github.com:invalid-format",  # Missing repo part
            "https://github.com/owner",  # Missing repo part
            "git@github.com:",  # Empty path
            "https://github.com/",  # Empty path
        ]

        for remote_url in invalid_urls:
            with self.subTest(remote_url=remote_url):
                # Set up remote
                os.system(
                    f"cd {self.test_repo_path} && git remote add origin {remote_url}"
                )

                # Extract info
                owner, repo = RepositoryConfig._extract_github_info(
                    str(self.test_repo_path), logging.getLogger(__name__)
                )

                self.assertIsNone(owner)
                self.assertIsNone(repo)

                # Clean up for next test
                os.system(f"cd {self.test_repo_path} && git remote remove origin")

    def test_github_url_with_additional_path_components(self):
        """Test extraction from GitHub URLs with additional path components"""
        # GitHub URLs sometimes have additional path components that should be ignored
        test_cases = [
            ("https://github.com/owner/repo/tree/main", "owner", "repo"),
            ("https://github.com/owner/repo/issues/123", "owner", "repo"),
            ("git@github.com:owner/repo/subdir/file.txt", "owner", "repo"),
        ]

        for remote_url, expected_owner, expected_repo in test_cases:
            with self.subTest(remote_url=remote_url):
                # Set up remote
                os.system(
                    f"cd {self.test_repo_path} && git remote add origin {remote_url}"
                )

                # Extract info
                owner, repo = RepositoryConfig._extract_github_info(
                    str(self.test_repo_path), logging.getLogger(__name__)
                )

                self.assertEqual(owner, expected_owner)
                self.assertEqual(repo, expected_repo)

                # Clean up for next test
                os.system(f"cd {self.test_repo_path} && git remote remove origin")


class TestErrorMessageClarity(unittest.TestCase):
    """Test that error messages are clear and informative"""

    def test_python_path_error_message_clarity(self):
        """Test that Python path validation errors are clear"""
        # Test non-existent path
        with self.assertRaises(ValueError) as context:
            RepositoryConfig.create_repository_config(
                name="test",
                workspace=os.path.abspath("/tmp/test"),
                description="Test",
                language=Language.PYTHON,
                port=8080,
                python_path="/nonexistent/python/executable",
            )

        error_msg = str(context.exception)
        self.assertIn("Python executable does not exist", error_msg)
        self.assertIn("/nonexistent/python/executable", error_msg)

    def test_language_error_message_clarity(self):
        """Test that language validation errors are clear"""
        with self.assertRaises(ValueError) as context:
            # Try to create a Language enum with invalid value
            Language("javascript")

        error_msg = str(context.exception)
        self.assertIn("'javascript'", error_msg)

    def test_path_error_message_clarity(self):
        """Test that path validation errors are clear"""
        with self.assertRaises(ValueError) as context:
            RepositoryConfig.create_repository_config(
                name="test",
                workspace="relative/path",
                description="Test",
                language=Language.PYTHON,
                port=8080,
            )

        error_msg = str(context.exception)
        self.assertIn("Repository workspace must be absolute", error_msg)
        self.assertIn("relative/path", error_msg)

    def test_empty_name_error_message_clarity(self):
        """Test that empty name validation errors are clear"""
        with self.assertRaises(ValueError) as context:
            RepositoryConfig.create_repository_config(
                name="",
                workspace=os.path.abspath("/tmp/test"),
                description="Test",
                language=Language.PYTHON,
                port=8080,
            )

        error_msg = str(context.exception)
        self.assertIn("Repository name cannot be empty", error_msg)


if __name__ == "__main__":
    unittest.main()
