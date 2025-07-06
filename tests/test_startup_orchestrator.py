#!/usr/bin/env python3

"""
Unit tests for the startup orchestrator module.
"""

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from constants import Language
from repository_manager import RepositoryConfig
from startup_orchestrator import (
    CodebaseStartupOrchestrator,
    IndexingStatus,
    StartupResult,
)


class TestIndexingStatus:
    """Test the IndexingStatus dataclass."""

    def test_indexing_status_initialization(self):
        """Test IndexingStatus initialization."""
        status = IndexingStatus(
            repository_id="test-repo",
            repository_path="/path/to/repo",
            status="pending",
        )

        assert status.repository_id == "test-repo"
        assert status.repository_path == "/path/to/repo"
        assert status.status == "pending"
        assert status.start_time is None
        assert status.end_time is None
        assert status.result is None
        assert status.error_message is None

    def test_duration_calculation(self):
        """Test duration calculation."""
        status = IndexingStatus(
            repository_id="test-repo",
            repository_path="/path/to/repo",
            status="pending",
        )

        # No start time
        assert status.duration is None

        # With start time only
        status.start_time = time.time() - 5.0
        duration = status.duration
        assert duration is not None
        assert 4.9 <= duration <= 5.1  # Allow small timing variations

        # With both start and end time
        status.end_time = status.start_time + 3.0
        assert status.duration == 3.0


class TestStartupResult:
    """Test the StartupResult dataclass."""

    def test_startup_result_initialization(self):
        """Test StartupResult initialization."""
        statuses = [
            IndexingStatus("repo1", "/path1", "completed"),
            IndexingStatus("repo2", "/path2", "failed"),
        ]

        result = StartupResult(
            total_repositories=5,
            indexed_repositories=3,
            failed_repositories=1,
            skipped_repositories=1,
            startup_duration=10.5,
            indexing_statuses=statuses,
        )

        assert result.total_repositories == 5
        assert result.indexed_repositories == 3
        assert result.failed_repositories == 1
        assert result.skipped_repositories == 1
        assert result.startup_duration == 10.5
        assert len(result.indexing_statuses) == 2

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        # Empty case (no attempts)
        result = StartupResult(0, 0, 0, 0, 0, [])
        assert result.success_rate == 1.0

        # Normal case (8 indexed + 2 failed = 10 attempted, 8/10 = 0.8)
        result = StartupResult(10, 8, 2, 0, 5.0, [])
        assert result.success_rate == 0.8

        # All successful (5 indexed + 0 failed = 5 attempted, 5/5 = 1.0)
        result = StartupResult(5, 5, 0, 0, 3.0, [])
        assert result.success_rate == 1.0

        # All skipped (0 indexed + 0 failed = 0 attempted, success rate = 1.0)
        result = StartupResult(3, 0, 0, 3, 1.0, [])
        assert result.success_rate == 1.0


class TestCodebaseStartupOrchestrator:
    """Test the CodebaseStartupOrchestrator class."""

    def test_initialization(self):
        """Test orchestrator initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            orchestrator = CodebaseStartupOrchestrator(data_dir)

            assert orchestrator.data_dir == data_dir
            assert orchestrator.db_path == data_dir / "symbols.db"
            assert data_dir.exists()

    @pytest.mark.asyncio
    async def test_initialize_database(self):
        """Test database initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            orchestrator = CodebaseStartupOrchestrator(data_dir)

            await orchestrator.initialize_database()

            # Database file should exist
            assert orchestrator.db_path.exists()

    @pytest.mark.asyncio
    async def test_initialize_database_failure(self):
        """Test database initialization failure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create orchestrator but make the data directory read-only
            data_dir = Path(temp_dir) / "readonly"
            data_dir.mkdir()
            data_dir.chmod(0o444)  # Read-only

            orchestrator = CodebaseStartupOrchestrator.__new__(
                CodebaseStartupOrchestrator
            )
            orchestrator.data_dir = data_dir
            orchestrator.db_path = data_dir / "symbols.db"

            with pytest.raises((OSError, PermissionError, sqlite3.OperationalError)):
                await orchestrator.initialize_database()

    @pytest.mark.asyncio
    async def test_initialize_repositories_empty_list(self):
        """Test initialization with empty repository list."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            orchestrator = CodebaseStartupOrchestrator(data_dir)

            result = await orchestrator.initialize_repositories([])

            assert result.total_repositories == 0
            assert result.indexed_repositories == 0
            assert result.failed_repositories == 0
            assert result.skipped_repositories == 0
            assert result.success_rate == 1.0
            assert len(result.indexing_statuses) == 0

    @pytest.mark.asyncio
    async def test_initialize_repositories_no_python_repos(self):
        """Test initialization with no Python repositories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            orchestrator = CodebaseStartupOrchestrator(data_dir)

            # Create Swift repository config
            swift_repo = RepositoryConfig(
                name="swift-repo",
                path="/path/to/swift",
                description="Swift repository",
                language=Language.SWIFT,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="repo",
            )

            result = await orchestrator.initialize_repositories([swift_repo])

            assert result.total_repositories == 1
            assert result.indexed_repositories == 0
            assert result.failed_repositories == 0
            assert result.skipped_repositories == 1
            assert result.success_rate == 1.0
            assert len(result.indexing_statuses) == 0

    @pytest.mark.asyncio
    async def test_initialize_repositories_with_python_repo(self):
        """Test initialization with Python repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            repo_dir = Path(temp_dir) / "test_repo"
            repo_dir.mkdir()

            # Create a simple Python file
            (repo_dir / "test.py").write_text("def hello(): pass")

            orchestrator = CodebaseStartupOrchestrator(data_dir)

            # Create Python repository config
            python_repo = RepositoryConfig(
                name="python-repo",
                path=str(repo_dir),
                description="Python repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="repo",
            )

            result = await orchestrator.initialize_repositories([python_repo])

            assert result.total_repositories == 1
            assert result.skipped_repositories == 0
            assert len(result.indexing_statuses) == 1

            status = result.indexing_statuses[0]
            assert status.repository_id == "python-repo"
            assert status.repository_path == str(repo_dir)
            assert status.status in ["completed", "failed"]

    @pytest.mark.asyncio
    async def test_initialize_repositories_with_indexing_failure(self):
        """Test initialization with indexing failure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            orchestrator = CodebaseStartupOrchestrator(data_dir)

            # Create Python repository config with invalid path
            python_repo = RepositoryConfig(
                name="python-repo",
                path="/nonexistent/path",
                description="Python repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="repo",
            )

            result = await orchestrator.initialize_repositories([python_repo])

            assert result.total_repositories == 1
            assert result.indexed_repositories == 0
            assert result.failed_repositories == 1
            assert result.skipped_repositories == 0
            assert result.success_rate == 0.0
            assert len(result.indexing_statuses) == 1

            status = result.indexing_statuses[0]
            assert status.repository_id == "python-repo"
            assert status.status == "failed"
            assert status.error_message is not None

    @pytest.mark.asyncio
    async def test_initialize_repositories_mixed_repos(self):
        """Test initialization with mixed repository types."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            repo_dir = Path(temp_dir) / "test_repo"
            repo_dir.mkdir()

            # Create a simple Python file
            (repo_dir / "test.py").write_text("def hello(): pass")

            orchestrator = CodebaseStartupOrchestrator(data_dir)

            # Create mixed repository configs
            python_repo = RepositoryConfig(
                name="python-repo",
                path=str(repo_dir),
                description="Python repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="repo",
            )

            swift_repo = RepositoryConfig(
                name="swift-repo",
                path="/path/to/swift",
                description="Swift repository",
                language=Language.SWIFT,
                port=8081,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="repo2",
            )

            result = await orchestrator.initialize_repositories(
                [python_repo, swift_repo]
            )

            assert result.total_repositories == 2
            assert result.skipped_repositories == 1  # Swift repo
            assert len(result.indexing_statuses) == 1  # Only Python repo

            status = result.indexing_statuses[0]
            assert status.repository_id == "python-repo"

    def test_get_indexing_status(self):
        """Test getting indexing status for a repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            orchestrator = CodebaseStartupOrchestrator(data_dir)

            statuses = [
                IndexingStatus("repo1", "/path1", "completed"),
                IndexingStatus("repo2", "/path2", "failed"),
            ]

            # Find existing status
            status = orchestrator.get_indexing_status("repo1", statuses)
            assert status is not None
            assert status.repository_id == "repo1"
            assert status.status == "completed"

            # Find non-existing status
            status = orchestrator.get_indexing_status("repo3", statuses)
            assert status is None

    @pytest.mark.asyncio
    async def test_index_repository_success(self):
        """Test successful repository indexing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            repo_dir = Path(temp_dir) / "test_repo"
            repo_dir.mkdir()

            # Create a simple Python file
            (repo_dir / "test.py").write_text("def hello(): pass")

            orchestrator = CodebaseStartupOrchestrator(data_dir)

            # Initialize database first
            await orchestrator.initialize_database()

            # Create repository config and status
            repo_config = RepositoryConfig(
                name="test-repo",
                path=str(repo_dir),
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="repo",
            )

            status = IndexingStatus(
                repository_id="test-repo",
                repository_path=str(repo_dir),
                status="pending",
            )

            await orchestrator._index_repository(repo_config, status)

            assert status.status == "completed"
            assert status.result is not None
            assert status.result.total_symbols > 0
            assert status.start_time is not None
            assert status.end_time is not None
            assert status.duration is not None

    @pytest.mark.asyncio
    async def test_index_repository_failure(self):
        """Test repository indexing failure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            orchestrator = CodebaseStartupOrchestrator(data_dir)

            # Initialize database first
            await orchestrator.initialize_database()

            # Create repository config with invalid path
            repo_config = RepositoryConfig(
                name="test-repo",
                path="/nonexistent/path",
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="repo",
            )

            status = IndexingStatus(
                repository_id="test-repo",
                repository_path="/nonexistent/path",
                status="pending",
            )

            await orchestrator._index_repository(repo_config, status)

            assert status.status == "failed"
            assert status.error_message is not None
            assert status.start_time is not None
            assert status.end_time is not None
