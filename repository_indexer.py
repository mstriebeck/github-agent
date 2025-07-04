"""
Repository indexing engine for MCP codebase server.

This module provides functionality to index Python repositories by scanning
for Python files, extracting symbols, and storing them in the database.
"""

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

from python_symbol_extractor import AbstractSymbolExtractor
from symbol_storage import AbstractSymbolStorage

logger = logging.getLogger(__name__)


class IndexingResult:
    """Result of a repository indexing operation."""

    def __init__(self):
        """Initialize indexing result."""
        self.processed_files: list[str] = []
        self.failed_files: list[tuple[str, str]] = []  # (file_path, error_message)
        self.total_symbols: int = 0
        self.skipped_files: list[str] = []

    def add_processed_file(self, file_path: str, symbol_count: int) -> None:
        """Add a successfully processed file."""
        self.processed_files.append(file_path)
        self.total_symbols += symbol_count

    def add_failed_file(self, file_path: str, error_message: str) -> None:
        """Add a file that failed to process."""
        self.failed_files.append((file_path, error_message))

    def add_skipped_file(self, file_path: str) -> None:
        """Add a file that was skipped."""
        self.skipped_files.append(file_path)

    @property
    def success_rate(self) -> float:
        """Calculate the success rate of file processing."""
        total_attempted = len(self.processed_files) + len(self.failed_files)
        if total_attempted == 0:
            return 1.0
        return len(self.processed_files) / total_attempted

    def __str__(self) -> str:
        """String representation of indexing result."""
        return (
            f"IndexingResult(processed={len(self.processed_files)}, "
            f"failed={len(self.failed_files)}, "
            f"skipped={len(self.skipped_files)}, "
            f"symbols={self.total_symbols}, "
            f"success_rate={self.success_rate:.2%})"
        )


class AbstractRepositoryIndexer(ABC):
    """Abstract base class for repository indexers."""

    @abstractmethod
    def index_repository(
        self, repository_path: str, repository_id: str
    ) -> IndexingResult:
        """Index a repository and return the result."""
        pass

    @abstractmethod
    def clear_repository_index(self, repository_id: str) -> None:
        """Clear all indexed data for a repository."""
        pass


class PythonRepositoryIndexer(AbstractRepositoryIndexer):
    """Repository indexer for Python codebases."""

    def __init__(
        self,
        symbol_extractor: AbstractSymbolExtractor,
        symbol_storage: AbstractSymbolStorage,
        exclude_patterns: set[str] | None = None,
        max_file_size_mb: float = 10.0,
    ):
        """Initialize the Python repository indexer.

        Args:
            symbol_extractor: Symbol extractor for parsing Python files
            symbol_storage: Storage backend for symbols
            exclude_patterns: Set of directory/file patterns to exclude
            max_file_size_mb: Maximum file size in MB to process
        """
        self.symbol_extractor = symbol_extractor
        self.symbol_storage = symbol_storage
        self.exclude_patterns = exclude_patterns or {
            "__pycache__",
            ".git",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".venv",
            "venv",
            "env",
            ".env",
            "node_modules",
            ".DS_Store",
            "*.pyc",
            "*.pyo",
            "*.pyd",
        }
        self.max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)

    def index_repository(
        self, repository_path: str, repository_id: str
    ) -> IndexingResult:
        """Index a Python repository.

        Args:
            repository_path: Path to the repository root
            repository_id: Unique identifier for the repository

        Returns:
            IndexingResult with details about the indexing operation

        Raises:
            ValueError: If repository path doesn't exist
            PermissionError: If repository path is not accessible
        """
        repo_path = Path(repository_path)
        if not repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repository_path}")

        if not repo_path.is_dir():
            raise ValueError(f"Repository path is not a directory: {repository_path}")

        logger.info(
            f"Starting indexing of repository: {repository_id} at {repository_path}"
        )

        # Clear existing data for this repository
        self.clear_repository_index(repository_id)

        result = IndexingResult()

        # Find all Python files
        python_files = self._find_python_files(repo_path)
        logger.info(f"Found {len(python_files)} Python files to process")

        # Process each Python file
        for python_file in python_files:
            try:
                self._process_file(python_file, repository_id, result)
            except Exception as e:
                error_msg = f"Unexpected error processing {python_file}: {e}"
                logger.error(error_msg)
                result.add_failed_file(str(python_file), error_msg)

        logger.info(f"Indexing completed: {result}")
        return result

    def clear_repository_index(self, repository_id: str) -> None:
        """Clear all indexed symbols for a repository.

        Args:
            repository_id: Repository identifier to clear
        """
        logger.info(f"Clearing index for repository: {repository_id}")
        self.symbol_storage.delete_symbols_by_repository(repository_id)

    def _find_python_files(self, repo_path: Path) -> list[Path]:
        """Find all Python files in the repository.

        Args:
            repo_path: Path to repository root

        Returns:
            List of Python file paths
        """
        python_files = []

        for root, dirs, files in os.walk(repo_path):
            root_path = Path(root)

            # Skip excluded directories
            dirs[:] = [d for d in dirs if not self._should_exclude_path(root_path / d)]

            # Process Python files
            for file in files:
                file_path = root_path / file
                if self._is_python_file(file_path) and not self._should_exclude_path(
                    file_path
                ):
                    python_files.append(file_path)

        return sorted(python_files)

    def _is_python_file(self, file_path: Path) -> bool:
        """Check if a file is a Python file.

        Args:
            file_path: Path to the file

        Returns:
            True if the file is a Python file
        """
        return file_path.suffix == ".py"

    def _should_exclude_path(self, path: Path) -> bool:
        """Check if a path should be excluded from processing.

        Args:
            path: Path to check

        Returns:
            True if the path should be excluded
        """
        path_str = str(path)
        path_name = path.name

        for pattern in self.exclude_patterns:
            if pattern.startswith("*"):
                # Handle wildcard patterns
                if path_name.endswith(pattern[1:]):
                    return True
            elif pattern in path_str or path_name == pattern:
                return True

        return False

    def _process_file(
        self, file_path: Path, repository_id: str, result: IndexingResult
    ) -> None:
        """Process a single Python file.

        Args:
            file_path: Path to the Python file
            repository_id: Repository identifier
            result: Result object to update
        """
        file_str = str(file_path)

        # Check file size
        try:
            file_size = file_path.stat().st_size
            if file_size > self.max_file_size_bytes:
                logger.warning(
                    f"Skipping large file {file_str} "
                    f"({file_size / 1024 / 1024:.1f}MB > "
                    f"{self.max_file_size_bytes / 1024 / 1024:.1f}MB)"
                )
                result.add_skipped_file(file_str)
                return
        except OSError as e:
            logger.warning(f"Cannot stat file {file_str}: {e}")
            result.add_failed_file(file_str, f"Cannot access file: {e}")
            return

        # Extract symbols from the file
        try:
            logger.debug(f"Processing file: {file_str}")
            symbols = self.symbol_extractor.extract_from_file(file_str, repository_id)

            # Store symbols in database
            if symbols:
                self.symbol_storage.insert_symbols(symbols)
                logger.debug(f"Extracted {len(symbols)} symbols from {file_str}")
            else:
                logger.debug(f"No symbols found in {file_str}")

            result.add_processed_file(file_str, len(symbols))

        except FileNotFoundError:
            error_msg = f"File not found: {file_str}"
            logger.error(error_msg)
            result.add_failed_file(file_str, error_msg)
        except UnicodeDecodeError as e:
            error_msg = f"Encoding error: {e}"
            logger.warning(f"Skipping {file_str} due to encoding error: {e}")
            result.add_failed_file(file_str, error_msg)
        except SyntaxError as e:
            error_msg = f"Syntax error: {e}"
            logger.warning(f"Skipping {file_str} due to syntax error: {e}")
            result.add_failed_file(file_str, error_msg)
        except Exception as e:
            error_msg = f"Processing error: {e}"
            logger.error(f"Error processing {file_str}: {e}")
            result.add_failed_file(file_str, error_msg)


class MockRepositoryIndexer(AbstractRepositoryIndexer):
    """Mock repository indexer for testing."""

    def __init__(self, predefined_result: IndexingResult | None = None):
        """Initialize mock indexer with optional predefined result."""
        self.predefined_result = predefined_result or IndexingResult()
        self.last_repository_path = ""
        self.last_repository_id = ""
        self.clear_calls: list[str] = []

    def index_repository(
        self, repository_path: str, repository_id: str
    ) -> IndexingResult:
        """Return predefined result and track call parameters."""
        self.last_repository_path = repository_path
        self.last_repository_id = repository_id
        return self.predefined_result

    def clear_repository_index(self, repository_id: str) -> None:
        """Track clear repository calls."""
        self.clear_calls.append(repository_id)
