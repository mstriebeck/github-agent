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
from python_symbol_extractor import PythonSymbolExtractor
from repository_indexer import PythonRepositoryIndexer
from repository_manager import RepositoryConfig
from startup_orchestrator import (
    CodebaseStartupOrchestrator,
    IndexingStatus,
    IndexingStatusEnum,
    StartupResult,
)
from symbol_storage import SQLiteSymbolStorage


class TestIndexingStatus:
    """Test the IndexingStatus dataclass."""

    def test_indexing_status_initialization(self):
        """Test IndexingStatus initialization."""
        status = IndexingStatus(
            repository_id="test-repo",
            repository_path="/path/to/repo",
            status=IndexingStatusEnum.PENDING,
        )

        assert status.repository_id == "test-repo"
        assert status.repository_path == "/path/to/repo"
        assert status.status == IndexingStatusEnum.PENDING
        assert status.start_time is None
        assert status.end_time is None
        assert status.result is None
        assert status.error_message is None

    def test_duration_calculation(self):
        """Test duration calculation."""
        status = IndexingStatus(
            repository_id="test-repo",
            repository_path="/path/to/repo",
            status=IndexingStatusEnum.PENDING,
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
            IndexingStatus("repo1", "/path1", IndexingStatusEnum.COMPLETED),
            IndexingStatus("repo2", "/path2", IndexingStatusEnum.FAILED),
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
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)

            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            assert orchestrator.symbol_storage == storage
            assert orchestrator.symbol_extractor == extractor
            assert orchestrator.indexer == indexer

            storage.close()

    @pytest.mark.asyncio
    async def test_initialize_database(self):
        """Test database initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)

            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            await orchestrator.initialize_database()

            # Database file should exist
            assert db_path.exists()

            storage.close()

    @pytest.mark.asyncio
    async def test_initialize_database_failure(self):
        """Test database initialization failure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create orchestrator but make the data directory read-only
            data_dir = Path(temp_dir) / "readonly"
            data_dir.mkdir()
            data_dir.chmod(0o444)  # Read-only

            db_path = data_dir / "subdir" / "symbols.db"  # This path can't be created

            # SQLiteSymbolStorage constructor will fail due to read-only directory
            with pytest.raises((OSError, PermissionError, sqlite3.OperationalError)):
                SQLiteSymbolStorage(str(db_path))

    @pytest.mark.asyncio
    async def test_initialize_repositories_empty_list(self):
        """Test initialization with empty repository list."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            result = await orchestrator.initialize_repositories([])

            assert result.total_repositories == 0
            assert result.indexed_repositories == 0
            assert result.failed_repositories == 0
            assert result.skipped_repositories == 0
            assert result.success_rate == 1.0
            assert len(result.indexing_statuses) == 0

            storage.close()

    @pytest.mark.asyncio
    async def test_initialize_repositories_no_python_repos(self):
        """Test initialization with no Python repositories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Create Swift repository config
            swift_repo = RepositoryConfig(
                name="swift-repo",
                workspace="/path/to/swift",
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
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)

            repo_dir = Path(temp_dir) / "test_repo"
            repo_dir.mkdir()

            # Create a simple Python file
            (repo_dir / "test.py").write_text("def hello(): pass")

            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Create Python repository config
            python_repo = RepositoryConfig(
                name="python-repo",
                workspace=str(repo_dir),
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
            assert status.status in [
                IndexingStatusEnum.COMPLETED,
                IndexingStatusEnum.FAILED,
            ]

    @pytest.mark.asyncio
    async def test_initialize_repositories_with_indexing_failure(self):
        """Test initialization with indexing failure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Create Python repository config with invalid path
            python_repo = RepositoryConfig(
                name="python-repo",
                workspace="/nonexistent/path",
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
            assert status.status == IndexingStatusEnum.FAILED
            assert status.error_message is not None

    @pytest.mark.asyncio
    async def test_initialize_repositories_mixed_repos(self):
        """Test initialization with mixed repository types."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)

            repo_dir = Path(temp_dir) / "test_repo"
            repo_dir.mkdir()

            # Create a simple Python file
            (repo_dir / "test.py").write_text("def hello(): pass")

            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Create mixed repository configs
            python_repo = RepositoryConfig(
                name="python-repo",
                workspace=str(repo_dir),
                description="Python repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="repo",
            )

            swift_repo = RepositoryConfig(
                name="swift-repo",
                workspace="/path/to/swift",
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
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            statuses = [
                IndexingStatus("repo1", "/path1", IndexingStatusEnum.COMPLETED),
                IndexingStatus("repo2", "/path2", IndexingStatusEnum.FAILED),
            ]

            # Find existing status
            status = orchestrator.get_indexing_status("repo1", statuses)
            assert status is not None
            assert status.repository_id == "repo1"
            assert status.status == IndexingStatusEnum.COMPLETED

            # Find non-existing status
            status = orchestrator.get_indexing_status("repo3", statuses)
            assert status is None

    @pytest.mark.asyncio
    async def test_index_repository_success(self):
        """Test successful repository indexing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)

            repo_dir = Path(temp_dir) / "test_repo"
            repo_dir.mkdir()

            # Create a simple Python file
            (repo_dir / "test.py").write_text("def hello(): pass")

            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Initialize database first
            await orchestrator.initialize_database()

            # Create repository config and status
            repo_config = RepositoryConfig(
                name="test-repo",
                workspace=str(repo_dir),
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
                status=IndexingStatusEnum.PENDING,
            )

            await orchestrator._index_repository(repo_config, status)

            assert status.status == IndexingStatusEnum.COMPLETED
            assert status.result is not None
            assert status.result.total_symbols > 0
            assert status.start_time is not None
            assert status.end_time is not None
            assert status.duration is not None

    @pytest.mark.asyncio
    async def test_index_repository_failure(self):
        """Test repository indexing failure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Initialize database first
            await orchestrator.initialize_database()

            # Create repository config with invalid path
            repo_config = RepositoryConfig(
                name="test-repo",
                workspace="/nonexistent/path",
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
                status=IndexingStatusEnum.PENDING,
            )

            await orchestrator._index_repository(repo_config, status)

            assert status.status == IndexingStatusEnum.FAILED
            assert status.error_message is not None
            assert status.start_time is not None
            assert status.end_time is not None
