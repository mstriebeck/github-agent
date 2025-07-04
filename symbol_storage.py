"""
Symbol storage and database management for MCP codebase server.

This module provides the core database schema and operations for storing
and retrieving Python symbols from repositories.
"""

import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Symbol:
    """Represents a Python symbol with its location and metadata."""

    name: str
    kind: str  # class, function, method, variable, constant, module
    file_path: str
    line_number: int
    column_number: int
    repository_id: str
    docstring: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert symbol to dictionary representation."""
        return {
            "name": self.name,
            "kind": self.kind,
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
    """SQLite implementation of symbol storage."""

    def __init__(self, db_path: str | Path):
        """Initialize SQLite symbol storage.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def create_schema(self) -> None:
        """Create the database schema for symbol storage."""
        with self._get_connection() as conn:
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

    def insert_symbol(self, symbol: Symbol) -> None:
        """Insert a symbol into the database."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO symbols (name, kind, file_path, line_number,
                                   column_number, repository_id, docstring)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    symbol.name,
                    symbol.kind,
                    symbol.file_path,
                    symbol.line_number,
                    symbol.column_number,
                    symbol.repository_id,
                    symbol.docstring,
                ),
            )
            conn.commit()

    def insert_symbols(self, symbols: list[Symbol]) -> None:
        """Insert multiple symbols into the database."""
        if not symbols:
            return

        with self._get_connection() as conn:
            data = [
                (
                    s.name,
                    s.kind,
                    s.file_path,
                    s.line_number,
                    s.column_number,
                    s.repository_id,
                    s.docstring,
                )
                for s in symbols
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
            logger.info(f"Inserted {len(symbols)} symbols into database")

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
                    symbol.kind,
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
        symbol_kind: str | None = None,
        limit: int = 50,
    ) -> list[Symbol]:
        """Search for symbols by name."""
        with self._get_connection() as conn:
            sql = "SELECT * FROM symbols WHERE name LIKE ?"
            params: list[Any] = [f"%{query}%"]

            if repository_id:
                sql += " AND repository_id = ?"
                params.append(repository_id)

            if symbol_kind:
                sql += " AND kind = ?"
                params.append(symbol_kind)

            # Order by exact match first, then by name
            sql += " ORDER BY (CASE WHEN name = ? THEN 0 ELSE 1 END), name LIMIT ?"
            params.append(query)
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()

            return [
                Symbol(
                    name=row["name"],
                    kind=row["kind"],
                    file_path=row["file_path"],
                    line_number=row["line_number"],
                    column_number=row["column_number"],
                    repository_id=row["repository_id"],
                    docstring=row["docstring"],
                )
                for row in rows
            ]

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
                kind=row["kind"],
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
                    kind=row["kind"],
                    file_path=row["file_path"],
                    line_number=row["line_number"],
                    column_number=row["column_number"],
                    repository_id=row["repository_id"],
                    docstring=row["docstring"],
                )
                for row in rows
            ]
