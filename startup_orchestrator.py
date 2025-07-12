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
from enum import Enum

from constants import Language
from python_symbol_extractor import AbstractSymbolExtractor
from repository_indexer import (
    AbstractRepositoryIndexer,
    IndexingResult,
)
from repository_manager import RepositoryConfig
from symbol_storage import AbstractSymbolStorage

logger = logging.getLogger(__name__)


class IndexingStatusEnum(Enum):
    """Enumeration for indexing status values."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IndexingStatus:
    """Status of repository indexing operation."""

    repository_id: str
    repository_path: str
    status: IndexingStatusEnum
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

    def __init__(
        self,
        symbol_storage: AbstractSymbolStorage,
        symbol_extractor: AbstractSymbolExtractor,
        indexer: AbstractRepositoryIndexer,
    ):
        """Initialize the startup orchestrator.

        Args:
            symbol_storage: Symbol storage backend for database operations
            symbol_extractor: Symbol extractor for parsing code files
            indexer: Repository indexer for processing repositories
        """
        self.symbol_storage = symbol_storage
        self.symbol_extractor = symbol_extractor
        self.indexer = indexer

        logger.info(
            f"Initialized startup orchestrator with storage: {type(symbol_storage).__name__}"
        )
        logger.info(f"Using extractor: {type(symbol_extractor).__name__}")
        logger.info(f"Using indexer: {type(self.indexer).__name__}")

    async def initialize_database(self) -> None:
        """Initialize the symbol database.

        Note: In production, the database is initialized by the master process
        before creating the orchestrator. This method is mainly for testing.
        """
        logger.info("Initializing symbol database")

        try:
            # Initialize schema using the injected storage
            self.symbol_storage.create_schema()
            logger.info("Database schema initialized successfully")

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

        # Filter Python repositories
        python_repos = [
            repo for repo in repositories if repo.language == Language.PYTHON
        ]

        logger.info(f"Found {len(python_repos)} Python repositories to index")

        # Track indexing status for each repository
        indexing_statuses: list[IndexingStatus] = []

        for repo in python_repos:
            status = IndexingStatus(
                repository_id=repo.name,
                repository_path=repo.workspace,
                status=IndexingStatusEnum.PENDING,
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

                if status.status == IndexingStatusEnum.COMPLETED:
                    indexed_count += 1
                else:
                    failed_count += 1

            except Exception as e:
                logger.error(f"Unexpected error indexing {status.repository_id}: {e}")
                status.status = IndexingStatusEnum.FAILED
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

        status.status = IndexingStatusEnum.IN_PROGRESS
        status.start_time = time.time()

        try:
            # Clear existing data for this repository
            logger.debug(f"Clearing existing index for {repo_config.name}")
            self.indexer.clear_repository_index(repo_config.name)

            # Index the repository
            logger.debug(f"Indexing repository at {repo_config.workspace}")
            result = self.indexer.index_repository(
                repo_config.workspace, repo_config.name
            )

            # Update status
            status.status = IndexingStatusEnum.COMPLETED
            status.end_time = time.time()
            status.result = result

            logger.info(
                f"Completed indexing {repo_config.name}: "
                f"{result.total_symbols} symbols, "
                f"{len(result.processed_files)} files, "
                f"{status.duration:.2f}s"
            )

        except Exception as e:
            logger.error(f"Failed to index repository {repo_config.name}: {e}")
            status.status = IndexingStatusEnum.FAILED
            status.end_time = time.time()
            status.error_message = str(e)

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
