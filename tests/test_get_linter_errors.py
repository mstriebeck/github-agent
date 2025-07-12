#!/usr/bin/env python3

"""
Tests for get_linter_errors function in github_tools.py

Tests parsing of linter errors based on repository language configuration.
"""

import asyncio
import json
import unittest
from typing import cast
from unittest.mock import Mock, patch

from constants import Language
from github_tools import get_linter_errors
from repository_manager import AbstractRepositoryManager, RepositoryConfig
from tests.test_fixtures import MockRepositoryManager


class TestGetLinterErrors(unittest.TestCase):
    """Test get_linter_errors function"""

    def _create_test_config(self, **kwargs):
        """Helper method to create RepositoryConfig with defaults"""
        defaults = {
            "name": "test-repo",
            "workspace": "/path/to/repo",
            "description": "Test repository",
            "language": Language.PYTHON,
            "port": 8081,
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

    def setUp(self):
        """Set up test fixtures"""
        # Sample error outputs for testing
        self.python_ruff_output = """::error title=Ruff (UP045),file=/Volumes/Code/github-agent/github_tools.py,line=503,col=49,endLine=503,endColumn=62::github_tools.py:503:49: UP045 Use `X | None` for type annotations
::error title=Ruff (E501),file=/path/to/project/src/main.py,line=42,col=80,endLine=42,endColumn=120::main.py:42:80: E501 line too long (120 > 79 characters)"""

        self.python_mypy_output = """tests/test_resource_manager.py:391: error: Cannot assign to a method  [method-assign]
src/main.py:25: error: Incompatible types in assignment (expression has type "str", variable has type "int")  [assignment]"""

        self.mixed_python_output = """::error title=Ruff (UP045),file=/Volumes/Code/github-agent/github_tools.py,line=503,col=49,endLine=503,endColumn=62::github_tools.py:503:49: UP045 Use `X | None` for type annotations
tests/test_resource_manager.py:391: error: Cannot assign to a method  [method-assign]"""

        self.swift_output = """/Users/dev/MyProject/Sources/MyApp/ContentView.swift:25:1: warning: Line should be 120 characters or less: currently 135 characters (line_length)
/Users/dev/MyProject/Sources/MyApp/Models/User.swift:15:23: error: Variable name should start with a lowercase character (identifier_name)"""

        # Mock repository configurations
        self.python_repo_config = self._create_test_config(
            name="python-repo",
            workspace="/path/to/python/repo",
            description="Python repository",
            language=Language.PYTHON,
            port=8081,
            github_repo="python-repo",
        )

        self.swift_repo_config = self._create_test_config(
            name="swift-repo",
            workspace="/path/to/swift/repo",
            description="Swift repository",
            language=Language.SWIFT,
            port=8082,
            github_repo="swift-repo",
        )

    def test_python_ruff_errors_parsing(self):
        """Test parsing of ruff errors for Python repository"""
        mock_repo_manager = MockRepositoryManager()
        mock_repo_manager.add_repository("python-repo", self.python_repo_config)

        result_json = asyncio.run(
            get_linter_errors(
                "python-repo", self.python_ruff_output, "python", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        self.assertEqual(result["repository"], "python-repo")
        self.assertEqual(result["language"], "python")
        self.assertEqual(result["total_errors"], 2)

        # Check first error
        error1 = result["errors"][0]
        self.assertEqual(error1["type"], "ruff")
        self.assertEqual(error1["file"], "/Volumes/Code/github-agent/github_tools.py")
        self.assertEqual(error1["line"], 503)
        self.assertEqual(error1["column"], 49)
        self.assertEqual(error1["rule"], "UP045")
        self.assertEqual(error1["severity"], "error")
        self.assertIn("Use `X | None` for type annotations", error1["message"])

        # Check second error
        error2 = result["errors"][1]
        self.assertEqual(error2["type"], "ruff")
        self.assertEqual(error2["file"], "/path/to/project/src/main.py")
        self.assertEqual(error2["line"], 42)
        self.assertEqual(error2["column"], 80)
        self.assertEqual(error2["rule"], "E501")

    @patch("github_tools.repo_manager")
    def test_python_mypy_errors_parsing(self, mock_repo_manager):
        """Test parsing of mypy errors for Python repository"""
        mock_repo_manager.repositories = {"python-repo": self.python_repo_config}

        result_json = asyncio.run(
            get_linter_errors(
                "python-repo", self.python_mypy_output, "python", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        self.assertEqual(result["repository"], "python-repo")
        self.assertEqual(result["language"], "python")
        self.assertEqual(result["total_errors"], 2)

        # Check first error
        error1 = result["errors"][0]
        self.assertEqual(error1["type"], "mypy")
        self.assertEqual(error1["file"], "tests/test_resource_manager.py")
        self.assertEqual(error1["line"], 391)
        self.assertEqual(error1["message"], "Cannot assign to a method")
        self.assertEqual(error1["error_code"], "method-assign")
        self.assertEqual(error1["severity"], "error")

        # Check second error
        error2 = result["errors"][1]
        self.assertEqual(error2["type"], "mypy")
        self.assertEqual(error2["file"], "src/main.py")
        self.assertEqual(error2["line"], 25)
        self.assertEqual(error2["error_code"], "assignment")

    @patch("github_tools.repo_manager")
    def test_mixed_python_errors_parsing(self, mock_repo_manager):
        """Test parsing of mixed ruff and mypy errors for Python repository"""
        mock_repo_manager.repositories = {"python-repo": self.python_repo_config}

        result_json = asyncio.run(
            get_linter_errors(
                "python-repo", self.mixed_python_output, "python", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        self.assertEqual(result["repository"], "python-repo")
        self.assertEqual(result["language"], "python")
        self.assertEqual(result["total_errors"], 2)

        # Should have one ruff error and one mypy error
        error_types = [error["type"] for error in result["errors"]]
        self.assertIn("ruff", error_types)
        self.assertIn("mypy", error_types)

    @patch("github_tools.repo_manager")
    def test_swift_errors_parsing(self, mock_repo_manager):
        """Test parsing of Swift errors for Swift repository"""
        mock_repo_manager.repositories = {"swift-repo": self.swift_repo_config}

        result_json = asyncio.run(
            get_linter_errors(
                "swift-repo", self.swift_output, "swift", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        self.assertEqual(result["repository"], "swift-repo")
        self.assertEqual(result["language"], "swift")
        self.assertEqual(result["total_errors"], 2)

        # Check first error (warning)
        error1 = result["errors"][0]
        self.assertEqual(error1["type"], "swiftlint")
        self.assertEqual(
            error1["file"], "/Users/dev/MyProject/Sources/MyApp/ContentView.swift"
        )
        self.assertEqual(error1["line"], 25)
        self.assertEqual(error1["severity"], "warning")
        self.assertEqual(error1["rule"], "line_length")

        # Check second error (error)
        error2 = result["errors"][1]
        self.assertEqual(error2["type"], "swiftlint")
        self.assertEqual(
            error2["file"], "/Users/dev/MyProject/Sources/MyApp/Models/User.swift"
        )
        self.assertEqual(error2["line"], 15)
        self.assertEqual(error2["severity"], "error")
        self.assertEqual(error2["rule"], "identifier_name")

    @patch("github_tools.repo_manager")
    def test_empty_error_output(self, mock_repo_manager):
        """Test handling of empty error output"""
        mock_repo_manager.repositories = {"python-repo": self.python_repo_config}

        result_json = asyncio.run(
            get_linter_errors("python-repo", "", "python", mock_repo_manager)
        )
        result = json.loads(result_json)

        self.assertEqual(result["repository"], "python-repo")
        self.assertEqual(result["language"], "python")
        self.assertEqual(result["total_errors"], 0)
        self.assertEqual(result["errors"], [])

    @patch("github_tools.repo_manager")
    def test_whitespace_only_output(self, mock_repo_manager):
        """Test handling of whitespace-only output"""
        mock_repo_manager.repositories = {"python-repo": self.python_repo_config}

        result_json = asyncio.run(
            get_linter_errors(
                "python-repo", "   \n  \n   ", "python", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        self.assertEqual(result["total_errors"], 0)
        self.assertEqual(result["errors"], [])

    @patch("github_tools.repo_manager")
    def test_repository_not_found(self, mock_repo_manager):
        """Test handling of non-existent repository"""
        mock_repo_manager.repositories = {}

        result_json = asyncio.run(
            get_linter_errors(
                "nonexistent-repo", self.python_ruff_output, "python", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        self.assertIn("error", result)
        self.assertIn("Repository nonexistent-repo not found", result["error"])

    def test_no_repo_manager(self):
        """Test handling when repo_manager is None"""
        # Test what happens when None is passed as repo_manager
        result_json = asyncio.run(
            get_linter_errors(
                "any-repo",
                self.python_ruff_output,
                "python",
                cast(AbstractRepositoryManager, None),
            )
        )
        result = json.loads(result_json)

        self.assertIn("error", result)
        self.assertIn("Failed to parse linter errors", result["error"])

    @patch("github_tools.repo_manager")
    def test_unsupported_language_error(self, mock_repo_manager):
        """Test handling of unsupported language (should not happen due to validation, but test anyway)"""
        # Create a mock config with an invalid language (bypassing validation)
        invalid_config = Mock()
        invalid_config.language = "javascript"
        mock_repo_manager.repositories = {"invalid-repo": invalid_config}

        result_json = asyncio.run(
            get_linter_errors(
                "invalid-repo", self.python_ruff_output, "javascript", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        self.assertIn("error", result)
        self.assertIn("Unsupported language: javascript", result["error"])

    @patch("github_tools.repo_manager")
    def test_malformed_error_lines_ignored(self, mock_repo_manager):
        """Test that malformed error lines are ignored gracefully"""
        mock_repo_manager.repositories = {"python-repo": self.python_repo_config}

        malformed_output = """::error title=Ruff (UP045),file=/valid/file.py,line=503,col=49,endLine=503,endColumn=62::valid error
This is not a valid error line
Another invalid line
::error title=Ruff (E501),file=/another/valid/file.py,line=42,col=80,endLine=42,endColumn=120::another valid error"""

        result_json = asyncio.run(
            get_linter_errors(
                "python-repo", malformed_output, "python", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        # Should only parse the two valid lines
        self.assertEqual(result["total_errors"], 2)
        self.assertEqual(len(result["errors"]), 2)

        # Verify the valid errors were parsed correctly
        self.assertEqual(result["errors"][0]["file"], "/valid/file.py")
        self.assertEqual(result["errors"][1]["file"], "/another/valid/file.py")

    @patch("github_tools.repo_manager")
    def test_exception_handling(self, mock_repo_manager):
        """Test that exceptions are handled gracefully"""
        # Mock repo_manager to raise an exception when accessing repositories
        mock_repo_manager.repositories = Mock()
        mock_repo_manager.repositories.__getitem__ = Mock(
            side_effect=Exception("Test exception")
        )

        result_json = asyncio.run(
            get_linter_errors(
                "python-repo", self.python_ruff_output, "python", mock_repo_manager
            )
        )
        result = json.loads(result_json)

        self.assertIn("error", result)
        self.assertIn("Failed to parse linter errors", result["error"])


if __name__ == "__main__":
    unittest.main()
