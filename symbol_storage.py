"""
Symbol storage and database management for MCP codebase server.

This module provides the core database schema and operations for storing
and retrieving Python symbols from repositories.
"""

import logging
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from constants import DATA_DIR

logger = logging.getLogger(__name__)


class SymbolKind(Enum):
    """Enumeration of Python symbol types."""

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    CLASSMETHOD = "classmethod"
    STATICMETHOD = "staticmethod"
    SETTER = "setter"
    DELETER = "deleter"
    VARIABLE = "variable"
    CONSTANT = "constant"
    MODULE = "module"


@dataclass
class Symbol:
    """Represents a Python symbol with its location and metadata."""

    name: str
    kind: SymbolKind
    file_path: str
    line_number: int
    column_number: int
    repository_id: str
    docstring: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert symbol to dictionary representation."""
        return {
            "name": self.name,
            "kind": self.kind.value,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "column_number": self.column_number,
            "repository_id": self.repository_id,
            "docstring": self.docstring,
        }


class AbstractSymbolStorage(ABC):
    """Abstract base class for symbol storage operations."""

    @abstractmethod
    def create_schema(self) -> None:
        """Create the database schema for symbol storage."""
        pass

    @abstractmethod
    def insert_symbol(self, symbol: Symbol) -> None:
        """Insert a symbol into the database."""
        pass

    @abstractmethod
    def insert_symbols(self, symbols: list[Symbol]) -> None:
        """Insert multiple symbols into the database."""
        pass

    @abstractmethod
    def update_symbol(self, symbol: Symbol) -> None:
        """Update an existing symbol in the database."""
        pass

    @abstractmethod
    def delete_symbol(self, symbol_id: int) -> None:
        """Delete a symbol from the database."""
        pass

    @abstractmethod
    def delete_symbols_by_repository(self, repository_id: str) -> None:
        """Delete all symbols for a specific repository."""
        pass

    @abstractmethod
    def search_symbols(
        self,
        query: str,
        repository_id: str | None = None,
        symbol_kind: str | None = None,
        limit: int = 50,
    ) -> list[Symbol]:
        """Search for symbols by name."""
        pass

    @abstractmethod
    def get_symbol_by_id(self, symbol_id: int) -> Symbol | None:
        """Get a specific symbol by its ID."""
        pass

    @abstractmethod
    def get_symbols_by_file(self, file_path: str, repository_id: str) -> list[Symbol]:
        """Get all symbols from a specific file."""
        pass


class SQLiteSymbolStorage(AbstractSymbolStorage):
    """SQLite implementation of symbol storage with error handling and resilience."""

    def __init__(
        self, db_path: str | Path, max_retries: int = 3, retry_delay: float = 0.1
    ):
        """Initialize SQLite symbol storage.

        Args:
            db_path: Path to SQLite database file
            max_retries: Maximum number of retry attempts for database operations
            retry_delay: Delay between retry attempts in seconds
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: sqlite3.Connection | None = None
        self._connection_lock = threading.Lock()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.create_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with retry logic."""
        with self._connection_lock:
            if self._connection is None:
                self._connection = self._create_connection()
            return self._connection

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with error handling."""
        for attempt in range(self.max_retries + 1):
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=30.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                return conn
            except sqlite3.DatabaseError as e:
                if attempt < self.max_retries:
                    logger.warning(
                        f"Database connection attempt {attempt + 1} failed: {e}. Retrying in {self.retry_delay}s..."
                    )
                    time.sleep(self.retry_delay)
                else:
                    logger.error(
                        f"Failed to connect to database after {self.max_retries + 1} attempts: {e}"
                    )
                    raise
            except Exception as e:
                logger.error(f"Unexpected error creating database connection: {e}")
                raise

        # This should never be reached due to the raise in the else block above
        raise RuntimeError("Failed to create database connection after all retries")

    def close(self) -> None:
        """Close any persistent database connections."""
        with self._connection_lock:
            if self._connection:
                try:
                    self._connection.close()
                except sqlite3.Error as e:
                    logger.warning(f"Error closing database connection: {e}")
                finally:
                    self._connection = None

    def _execute_with_retry(self, operation_name: str, operation_func, *args, **kwargs):
        """Execute a database operation with retry logic."""
        for attempt in range(self.max_retries + 1):
            try:
                return operation_func(*args, **kwargs)
            except sqlite3.DatabaseError as e:
                if attempt < self.max_retries:
                    logger.warning(
                        f"{operation_name} attempt {attempt + 1} failed: {e}. Retrying in {self.retry_delay}s..."
                    )
                    time.sleep(self.retry_delay)
                    # Reset connection on database errors
                    self._connection = None
                else:
                    logger.error(
                        f"{operation_name} failed after {self.max_retries + 1} attempts: {e}"
                    )
                    raise
            except sqlite3.Error as e:
                logger.error(f"{operation_name} failed with SQLite error: {e}")
                raise
            except Exception as e:
                logger.error(f"{operation_name} failed with unexpected error: {e}")
                raise

    def _recover_from_corruption(self) -> None:
        """Attempt to recover from database corruption."""
        logger.error("Database corruption detected. Attempting recovery...")

        # Close existing connection
        self.close()

        # Try to backup the corrupt database
        backup_path = self.db_path.with_suffix(".db.corrupt")
        try:
            if self.db_path.exists():
                self.db_path.replace(backup_path)
                logger.info(f"Corrupt database backed up to {backup_path}")
        except Exception as e:
            logger.warning(f"Could not backup corrupt database: {e}")

        # Create new database with schema
        try:
            self.create_schema()
            logger.info("Database recovered successfully")
        except Exception as e:
            logger.error(f"Failed to recover database: {e}")
            raise

    def create_schema(self) -> None:
        """Create the database schema for symbol storage."""

        def _create_schema():
            conn = self._get_connection()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    line_number INTEGER NOT NULL,
                    column_number INTEGER NOT NULL,
                    repository_id TEXT NOT NULL,
                    docstring TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Create indexes for common query patterns
            conn.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_symbols_name
            ON symbols(name)
            """
            )

            conn.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_symbols_repository_id
            ON symbols(repository_id)
            """
            )

            conn.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_symbols_kind
            ON symbols(kind)
            """
            )

            conn.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_symbols_file_path
            ON symbols(file_path, repository_id)
            """
            )

            conn.execute(
                """
            CREATE INDEX IF NOT EXISTS idx_symbols_name_repo
            ON symbols(name, repository_id)
            """
            )

            conn.commit()
            logger.info(f"Created symbol storage schema in {self.db_path}")

        try:
            self._execute_with_retry("Schema creation", _create_schema)
        except sqlite3.DatabaseError as e:
            if "database disk image is malformed" in str(e).lower():
                logger.error("Database corruption detected during schema creation")
                self._recover_from_corruption()
            else:
                raise

    def insert_symbol(self, symbol: Symbol) -> None:
        """Insert a symbol into the database."""

        def _insert_symbol():
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO symbols (name, kind, file_path, line_number,
                                       column_number, repository_id, docstring)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        symbol.name,
                        symbol.kind.value,
                        symbol.file_path,
                        symbol.line_number,
                        symbol.column_number,
                        symbol.repository_id,
                        symbol.docstring,
                    ),
                )
                conn.commit()

        self._execute_with_retry("Insert symbol", _insert_symbol)

    def insert_symbols(self, symbols: list[Symbol]) -> None:
        """Insert multiple symbols into the database with memory management."""
        if not symbols:
            return

        # Process symbols in batches to avoid memory issues
        batch_size = 1000
        total_inserted = 0

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]

            def _insert_batch(batch_symbols=batch):
                nonlocal total_inserted
                with self._get_connection() as conn:
                    data = [
                        (
                            s.name,
                            s.kind.value,
                            s.file_path,
                            s.line_number,
                            s.column_number,
                            s.repository_id,
                            s.docstring,
                        )
                        for s in batch_symbols
                    ]
                    conn.executemany(
                        """
                        INSERT INTO symbols (name, kind, file_path, line_number,
                                           column_number, repository_id, docstring)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        data,
                    )
                    conn.commit()
                    total_inserted += len(batch_symbols)
                    logger.debug(
                        f"Inserted batch of {len(batch_symbols)} symbols into database"
                    )

            try:
                self._execute_with_retry(
                    f"Insert symbols batch {i // batch_size + 1}", _insert_batch
                )
            except Exception as e:
                logger.error(
                    f"Failed to insert symbols batch {i // batch_size + 1}: {e}"
                )
                raise

        logger.info(f"Inserted {total_inserted} symbols into database")

    def update_symbol(self, symbol: Symbol) -> None:
        """Update an existing symbol in the database."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE symbols
                SET name = ?, kind = ?, file_path = ?, line_number = ?,
                    column_number = ?, repository_id = ?, docstring = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE name = ? AND file_path = ? AND repository_id = ?
            """,
                (
                    symbol.name,
                    symbol.kind.value,
                    symbol.file_path,
                    symbol.line_number,
                    symbol.column_number,
                    symbol.repository_id,
                    symbol.docstring,
                    symbol.name,
                    symbol.file_path,
                    symbol.repository_id,
                ),
            )
            conn.commit()

    def delete_symbol(self, symbol_id: int) -> None:
        """Delete a symbol from the database."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM symbols WHERE id = ?", (symbol_id,))
            conn.commit()

    def delete_symbols_by_repository(self, repository_id: str) -> None:
        """Delete all symbols for a specific repository."""
        with self._get_connection() as conn:
            result = conn.execute(
                "DELETE FROM symbols WHERE repository_id = ?", (repository_id,)
            )
            conn.commit()
            logger.info(
                f"Deleted {result.rowcount} symbols for repository {repository_id}"
            )

    def search_symbols(
        self,
        query: str,
        repository_id: str | None = None,
        symbol_kind: SymbolKind | str | None = None,
        limit: int = 50,
    ) -> list[Symbol]:
        """Search for symbols by name."""

        def _search_symbols():
            with self._get_connection() as conn:
                sql = "SELECT * FROM symbols WHERE name LIKE ?"
                params: list[Any] = [f"%{query}%"]

                if repository_id:
                    sql += " AND repository_id = ?"
                    params.append(repository_id)

                if symbol_kind:
                    sql += " AND kind = ?"
                    # Convert enum to string value if needed
                    kind_value = (
                        symbol_kind.value
                        if isinstance(symbol_kind, SymbolKind)
                        else symbol_kind
                    )
                    params.append(kind_value)

                # Order by exact match first, then by name
                sql += " ORDER BY (CASE WHEN name = ? THEN 0 ELSE 1 END), name LIMIT ?"
                params.append(query)
                params.append(limit)

                rows = conn.execute(sql, params).fetchall()

                return [
                    Symbol(
                        name=row["name"],
                        kind=SymbolKind(row["kind"]),
                        file_path=row["file_path"],
                        line_number=row["line_number"],
                        column_number=row["column_number"],
                        repository_id=row["repository_id"],
                        docstring=row["docstring"],
                    )
                    for row in rows
                ]

        return self._execute_with_retry("Search symbols", _search_symbols)

    def get_symbol_by_id(self, symbol_id: int) -> Symbol | None:
        """Get a specific symbol by its ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM symbols WHERE id = ?", (symbol_id,)
            ).fetchone()

            if not row:
                return None

            return Symbol(
                name=row["name"],
                kind=SymbolKind(row["kind"]),
                file_path=row["file_path"],
                line_number=row["line_number"],
                column_number=row["column_number"],
                repository_id=row["repository_id"],
                docstring=row["docstring"],
            )

    def get_symbols_by_file(self, file_path: str, repository_id: str) -> list[Symbol]:
        """Get all symbols from a specific file."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM symbols
                WHERE file_path = ? AND repository_id = ?
                ORDER BY line_number, column_number
            """,
                (file_path, repository_id),
            ).fetchall()

            return [
                Symbol(
                    name=row["name"],
                    kind=SymbolKind(row["kind"]),
                    file_path=row["file_path"],
                    line_number=row["line_number"],
                    column_number=row["column_number"],
                    repository_id=row["repository_id"],
                    docstring=row["docstring"],
                )
                for row in rows
            ]


class ProductionSymbolStorage(SQLiteSymbolStorage):
    """Production symbol storage that uses standard data directory and database name."""

    def __init__(self):
        """Initialize with standard production database path."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_path = DATA_DIR / "symbols.db"
        super().__init__(str(db_path))

    @classmethod
    def create_with_schema(cls) -> "ProductionSymbolStorage":
        """
        Factory method to create ProductionSymbolStorage with initialized schema.

        Returns:
            ProductionSymbolStorage instance with schema already created
        """
        storage = cls()
        storage.create_schema()
        return storage
