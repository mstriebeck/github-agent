#!/usr/bin/env python3

"""
Startup Orchestrator for MCP Codebase Server

This module handles the startup sequence for the MCP codebase server,
including database initialization, repository indexing, and status tracking.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from constants import DATA_DIR, Language
from python_symbol_extractor import PythonSymbolExtractor
from repository_indexer import IndexingResult, PythonRepositoryIndexer
from repository_manager import RepositoryConfig
from symbol_storage import SQLiteSymbolStorage

logger = logging.getLogger(__name__)


@dataclass
class IndexingStatus:
    """Status of repository indexing operation."""

    repository_id: str
    repository_path: str
    status: str  # "pending", "in_progress", "completed", "failed"
    start_time: float | None = None
    end_time: float | None = None
    result: IndexingResult | None = None
    error_message: str | None = None

    @property
    def duration(self) -> float | None:
        """Get indexing duration in seconds."""
        if self.start_time is None:
            return None
        end_time = self.end_time or time.time()
        return end_time - self.start_time


@dataclass
class StartupResult:
    """Result of startup orchestration."""

    total_repositories: int
    indexed_repositories: int
    failed_repositories: int
    skipped_repositories: int
    startup_duration: float
    indexing_statuses: list[IndexingStatus]

    @property
    def success_rate(self) -> float:
        """Calculate success rate of repository indexing."""
        attempted_repositories = self.indexed_repositories + self.failed_repositories
        if attempted_repositories == 0:
            return 1.0
        return self.indexed_repositories / attempted_repositories


class AbstractStartupOrchestrator(ABC):
    """Abstract base class for startup orchestrators."""

    @abstractmethod
    async def initialize_repositories(
        self, repositories: list[RepositoryConfig]
    ) -> StartupResult:
        """Initialize and index repositories."""
        pass

    @abstractmethod
    async def initialize_database(self) -> None:
        """Initialize the database."""
        pass


class CodebaseStartupOrchestrator(AbstractStartupOrchestrator):
    """Startup orchestrator for the codebase server."""

    def __init__(self, data_dir: Path = DATA_DIR):
        """Initialize the startup orchestrator.

        Args:
            data_dir: Directory for storing data files
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database path
        self.db_path = self.data_dir / "symbols.db"

        logger.info(f"Initialized startup orchestrator with data dir: {self.data_dir}")
        logger.info(f"Database path: {self.db_path}")

    async def initialize_database(self) -> None:
        """Initialize the symbol database."""
        logger.info("Initializing symbol database")

        try:
            # Create symbol storage and initialize schema
            storage = SQLiteSymbolStorage(str(self.db_path))
            storage.create_schema()
            storage.close()

            logger.info(f"Database initialized successfully at {self.db_path}")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    async def initialize_repositories(
        self, repositories: list[RepositoryConfig]
    ) -> StartupResult:
        """Initialize and index repositories.

        Args:
            repositories: List of repository configurations

        Returns:
            StartupResult with details about the startup process
        """
        start_time = time.time()

        logger.info(
            f"Starting repository initialization for {len(repositories)} repositories"
        )

        # Initialize database first
        await self.initialize_database()

        # Filter Python repositories
        python_repos = [
            repo for repo in repositories if repo.language == Language.PYTHON
        ]

        logger.info(f"Found {len(python_repos)} Python repositories to index")

        # Track indexing status for each repository
        indexing_statuses: list[IndexingStatus] = []

        for repo in python_repos:
            status = IndexingStatus(
                repository_id=repo.name, repository_path=repo.path, status="pending"
            )
            indexing_statuses.append(status)

        # Index repositories sequentially to avoid resource contention
        indexed_count = 0
        failed_count = 0

        for status in indexing_statuses:
            try:
                repo_config = next(
                    r for r in python_repos if r.name == status.repository_id
                )
                await self._index_repository(repo_config, status)

                if status.status == "completed":
                    indexed_count += 1
                else:
                    failed_count += 1

            except Exception as e:
                logger.error(f"Unexpected error indexing {status.repository_id}: {e}")
                status.status = "failed"
                status.error_message = str(e)
                status.end_time = time.time()
                failed_count += 1

        # Calculate results
        startup_duration = time.time() - start_time
        skipped_count = len(repositories) - len(python_repos)

        result = StartupResult(
            total_repositories=len(repositories),
            indexed_repositories=indexed_count,
            failed_repositories=failed_count,
            skipped_repositories=skipped_count,
            startup_duration=startup_duration,
            indexing_statuses=indexing_statuses,
        )

        # Log summary
        logger.info(f"Startup completed in {startup_duration:.2f}s")
        logger.info(
            f"Indexed: {indexed_count}, Failed: {failed_count}, Skipped: {skipped_count}"
        )
        logger.info(f"Success rate: {result.success_rate:.1%}")

        return result

    async def _index_repository(
        self, repo_config: RepositoryConfig, status: IndexingStatus
    ) -> None:
        """Index a single repository.

        Args:
            repo_config: Repository configuration
            status: Indexing status to update
        """
        logger.info(f"Starting indexing for repository: {repo_config.name}")

        status.status = "in_progress"
        status.start_time = time.time()

        try:
            # Create storage and indexer
            storage = SQLiteSymbolStorage(str(self.db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)

            # Clear existing data for this repository
            logger.debug(f"Clearing existing index for {repo_config.name}")
            indexer.clear_repository_index(repo_config.name)

            # Index the repository
            logger.debug(f"Indexing repository at {repo_config.path}")
            result = indexer.index_repository(repo_config.path, repo_config.name)

            # Update status
            status.status = "completed"
            status.end_time = time.time()
            status.result = result

            # Close storage
            storage.close()

            logger.info(
                f"Completed indexing {repo_config.name}: "
                f"{result.total_symbols} symbols, "
                f"{len(result.processed_files)} files, "
                f"{status.duration:.2f}s"
            )

        except Exception as e:
            logger.error(f"Failed to index repository {repo_config.name}: {e}")
            status.status = "failed"
            status.end_time = time.time()
            status.error_message = str(e)

            # Still close storage if it was created
            try:
                if "storage" in locals():
                    storage.close()
            except Exception:
                pass

    def get_indexing_status(
        self, repository_id: str, statuses: list[IndexingStatus]
    ) -> IndexingStatus | None:
        """Get indexing status for a specific repository.

        Args:
            repository_id: Repository identifier
            statuses: List of indexing statuses

        Returns:
            IndexingStatus if found, None otherwise
        """
        return next((s for s in statuses if s.repository_id == repository_id), None)
