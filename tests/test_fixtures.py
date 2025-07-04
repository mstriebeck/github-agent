"""
Test fixtures and mock objects for the GitHub Agent test suite.

This module provides mock implementations of internal objects using dependency injection
instead of unittest.mock patches, following the pattern described in AGENT.md.

Currently provides:
- MockRepositoryManager: Mock implementation for testing repository-dependent functions

Usage:
    from tests.test_fixtures import MockRepositoryManager

    def test_something():
        mock_repo_manager = MockRepositoryManager()
        mock_repo_manager.add_repository("test-repo", config)
        result = function_under_test("test-repo", mock_repo_manager)
"""

from typing import Any

from repository_manager import AbstractRepositoryManager


class MockRepositoryManager(AbstractRepositoryManager):
    """Mock implementation of repository manager for testing."""

    def __init__(self):
        self._repositories: dict[str, Any] = {}
        self._fail_on_access = False

    @property
    def repositories(self) -> dict[str, Any]:
        """Get dictionary of repositories."""
        if self._fail_on_access:
            raise Exception("Test exception")
        return self._repositories

    def get_repository(self, name: str) -> Any | None:
        """Get repository by name."""
        if self._fail_on_access:
            raise Exception("Test exception")
        return self._repositories.get(name)

    def add_repository(self, name: str, config: Any):
        """Add a repository configuration."""
        self._repositories[name] = config

    def remove_repository(self, name: str):
        """Remove a repository configuration."""
        self._repositories.pop(name, None)

    def clear_repositories(self):
        """Clear all repositories."""
        self._repositories.clear()

    def set_fail_on_access(self, fail: bool):
        """Set whether to fail when accessing repositories."""
        self._fail_on_access = fail
