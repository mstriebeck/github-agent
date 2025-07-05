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
            max_file_size_mb: Maximum file size in MB to process. Files larger than this
                are skipped to prevent memory issues during AST parsing and to avoid
                processing generated or minified files that typically don't contain
                meaningful symbols for code navigation.
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

        logger.info(
            f"Initialized PythonRepositoryIndexer with max_file_size_mb={max_file_size_mb}"
        )
        logger.debug(f"Exclude patterns: {self.exclude_patterns}")
        logger.debug(f"Max file size bytes: {self.max_file_size_bytes}")

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
        logger.debug(
            f"Indexing configuration: max_file_size_mb={self.max_file_size_bytes / 1024 / 1024:.1f}, exclude_patterns={self.exclude_patterns}"
        )

        # Clear existing data for this repository
        logger.info(f"Clearing existing index data for repository: {repository_id}")
        self.clear_repository_index(repository_id)

        result = IndexingResult()
        logger.debug("Initialized indexing result tracking")

        # Find all Python files
        python_files = self._find_python_files(repo_path)
        logger.info(f"Found {len(python_files)} Python files to process")

        # Process each Python file
        for python_file in python_files:
            logger.info(f"Processing file: {python_file}")
            try:
                self._process_file(python_file, repository_id, result)
            except (MemoryError, KeyboardInterrupt, SystemExit):
                # Critical system errors that should always propagate immediately
                raise
            except Exception as e:
                # All unexpected errors from _process_file are logged but don't fail entire indexing
                # This includes database errors, symbol extraction errors, etc.
                # File-level errors (permissions, syntax errors) are already handled in _process_file
                error_msg = f"Unexpected error processing {python_file}: {e}"
                logger.error(error_msg)
                result.add_failed_file(str(python_file), error_msg)

        logger.info(f"Indexing completed for repository {repository_id}")
        logger.info(
            f"Summary: {len(result.processed_files)} files processed, {len(result.failed_files)} failed, {len(result.skipped_files)} skipped"
        )
        logger.info(f"Total symbols extracted: {result.total_symbols}")
        logger.info(f"Success rate: {result.success_rate:.1%}")
        logger.debug(f"Full indexing result: {result}")
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
        logger.debug(f"Starting file discovery in: {repo_path}")
        python_files = []
        excluded_dirs = []

        for root, dirs, files in os.walk(repo_path):
            root_path = Path(root)

            # Skip excluded directories
            original_dirs = dirs[:]
            dirs[:] = [d for d in dirs if not self._should_exclude_path(root_path / d)]
            for excluded_dir in set(original_dirs) - set(dirs):
                excluded_dirs.append(root_path / excluded_dir)

            # Process Python files
            for file in files:
                file_path = root_path / file
                if self._is_python_file(file_path) and not self._should_exclude_path(
                    file_path
                ):
                    python_files.append(file_path)

        if excluded_dirs:
            logger.debug(
                f"Excluded {len(excluded_dirs)} directories: {excluded_dirs[:5]}{'...' if len(excluded_dirs) > 5 else ''}"
            )

        sorted_files = sorted(python_files)
        logger.debug(
            f"File discovery completed: found {len(sorted_files)} Python files"
        )
        return sorted_files

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

        # Check file size - large files are skipped to avoid performance and memory issues:
        # 1. Memory usage: AST parsing loads entire file into memory, large files can cause OOM
        # 2. Performance: Symbol extraction complexity increases significantly with file size
        # 3. Practical limits: Most legitimate Python source files are under 10MB
        # 4. Generated files: Very large files are typically auto-generated/minified code with minimal value
        # 5. User experience: Prevents indexing from hanging on pathological cases
        try:
            file_size = file_path.stat().st_size
            if file_size > self.max_file_size_bytes:
                logger.warning(
                    f"Skipping large file {file_str} "
                    f"({file_size / 1024 / 1024:.1f}MB > "
                    f"{self.max_file_size_bytes / 1024 / 1024:.1f}MB). "
                    f"Large files are skipped to prevent memory issues and improve performance."
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
            # File disappeared during processing - log as error since this is unexpected
            error_msg = f"File not found: {file_str}"
            logger.error(error_msg)
            result.add_failed_file(file_str, error_msg)
        except (UnicodeDecodeError, SyntaxError) as e:
            # Expected file-level issues that should be logged as warnings
            # These are common in real codebases and shouldn't fail the indexing
            error_msg = f"File parsing error: {e}"
            logger.warning(f"Skipping {file_str} due to parsing error: {e}")
            result.add_failed_file(file_str, error_msg)
        except (PermissionError, OSError) as e:
            # File system access errors - log as warnings since individual file failures
            # shouldn't stop the entire indexing process
            error_msg = f"File access error: {e}"
            logger.warning(f"Cannot access {file_str}: {e}")
            result.add_failed_file(file_str, error_msg)
        except (MemoryError, KeyboardInterrupt, SystemExit):
            # Critical errors that must propagate
            raise
        except Exception as e:
            # Unexpected errors in symbol extraction or storage - log but continue
            error_msg = f"Processing error: {e}"
            logger.error(f"Error processing {file_str}: {e}")
            result.add_failed_file(file_str, error_msg)
