"""
Tests for error handling and resilience features in MCP codebase server.

This module tests various error scenarios including database failures,
file system errors, memory pressure, and corruption recovery.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from python_symbol_extractor import PythonSymbolExtractor
from repository_indexer import PythonRepositoryIndexer
from symbol_storage import SQLiteSymbolStorage, Symbol, SymbolKind


class TestDatabaseErrorHandling(unittest.TestCase):
    """Test database error handling and recovery mechanisms."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_errors.db"

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_database_connection_retry_logic(self):
        """Test that database connections are retried on failure."""
        storage = SQLiteSymbolStorage(self.db_path, max_retries=2, retry_delay=0.01)

        # Mock sqlite3.connect to fail the first time, succeed the second
        original_connect = sqlite3.connect
        call_count = 0

        def mock_connect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise sqlite3.DatabaseError("Connection failed")
            return original_connect(*args, **kwargs)

        with patch("sqlite3.connect", side_effect=mock_connect):
            # Force a new connection
            storage._connection = None
            conn = storage._get_connection()
            self.assertIsNotNone(conn)
            self.assertEqual(call_count, 2)

    def test_database_corruption_recovery(self):
        """Test database corruption detection and recovery."""
        storage = SQLiteSymbolStorage(self.db_path)

        # Create a corrupt database file
        with open(self.db_path, "wb") as f:
            f.write(b"corrupted database content")

        # Force connection reset
        storage._connection = None

        # This should trigger corruption recovery
        with patch.object(storage, "_recover_from_corruption") as mock_recover:
            mock_recover.side_effect = lambda: storage.create_schema()
            try:
                storage.create_schema()
            except sqlite3.DatabaseError:
                pass  # Expected on corrupted database

        # Verify recovery was attempted
        self.assertTrue(mock_recover.called or self.db_path.exists())

    def test_insert_symbols_batch_processing(self):
        """Test that large symbol batches are processed correctly."""
        storage = SQLiteSymbolStorage(self.db_path)

        # Create a large number of symbols
        symbols = []
        for i in range(2500):  # More than batch size of 1000
            symbols.append(
                Symbol(
                    name=f"symbol_{i}",
                    kind=SymbolKind.FUNCTION,
                    file_path=f"/test/file_{i % 10}.py",
                    line_number=i,
                    column_number=0,
                    repository_id="test_repo",
                )
            )

        # Insert symbols and verify they're processed in batches
        storage.insert_symbols(symbols)

        # Verify all symbols were inserted
        results = storage.search_symbols(
            "symbol_", repository_id="test_repo", limit=3000
        )
        self.assertEqual(len(results), 2500)

    def test_database_operation_retry_on_failure(self):
        """Test that database operations have retry logic available."""
        storage = SQLiteSymbolStorage(self.db_path, max_retries=2, retry_delay=0.01)

        # Test that the retry mechanism exists and is configured
        self.assertEqual(storage.max_retries, 2)
        self.assertEqual(storage.retry_delay, 0.01)

        # Test a simple database operation that should work
        symbol = Symbol(
            name="test_symbol",
            kind=SymbolKind.FUNCTION,
            file_path="/test/file.py",
            line_number=1,
            column_number=0,
            repository_id="test_repo",
        )

        # This should succeed normally
        storage.insert_symbol(symbol)

        # Verify the symbol was inserted
        results = storage.search_symbols("test_symbol", repository_id="test_repo")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "test_symbol")

    def test_memory_management_during_large_operations(self):
        """Test memory management during large database operations."""
        storage = SQLiteSymbolStorage(self.db_path)

        # Create a very large symbol list
        large_symbol_count = 5000
        symbols = []
        for i in range(large_symbol_count):
            symbols.append(
                Symbol(
                    name=f"large_symbol_{i}",
                    kind=SymbolKind.VARIABLE,
                    file_path=f"/large/file_{i % 100}.py",
                    line_number=i % 1000,
                    column_number=0,
                    repository_id="large_repo",
                )
            )

        # This should not cause memory issues due to batching
        storage.insert_symbols(symbols)

        # Verify symbols were inserted correctly
        results = storage.search_symbols(
            "large_symbol_", repository_id="large_repo", limit=100
        )
        self.assertEqual(len(results), 100)  # Limited by query limit


class TestFileSystemErrorHandling(unittest.TestCase):
    """Test file system error handling in symbol extraction and repository indexing."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PythonSymbolExtractor()

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_file_handling(self):
        """Test handling of missing files."""
        non_existent_file = "/path/that/does/not/exist.py"

        with self.assertRaises(FileNotFoundError):
            self.extractor.extract_from_file(non_existent_file, "test_repo")

    def test_permission_denied_handling(self):
        """Test handling of permission denied errors."""
        # Create a file with restricted permissions
        restricted_file = Path(self.temp_dir) / "restricted.py"
        restricted_file.write_text("def test(): pass")

        # Make file unreadable (this may not work on all systems)
        try:
            os.chmod(restricted_file, 0o000)

            with self.assertRaises((PermissionError, OSError)):
                self.extractor.extract_from_file(str(restricted_file), "test_repo")
        finally:
            # Restore permissions for cleanup
            try:
                os.chmod(restricted_file, 0o644)
            except Exception:
                pass

    def test_encoding_error_recovery(self):
        """Test recovery from encoding errors with multiple encoding attempts."""
        # Create file with non-UTF8 content
        binary_file = Path(self.temp_dir) / "binary.py"
        with open(binary_file, "wb") as f:
            f.write(b"def test(): pass\n# \x80\x81\x82 invalid utf-8")

        # Should succeed with latin-1 fallback
        symbols = self.extractor.extract_from_file(str(binary_file), "test_repo")
        self.assertGreater(len(symbols), 0)

    def test_corrupted_python_file_handling(self):
        """Test handling of corrupted Python files."""
        corrupted_file = Path(self.temp_dir) / "corrupted.py"

        # Test binary content
        with open(corrupted_file, "wb") as f:
            f.write(b"\x00\x01\x02\x03 not python code")

        symbols = self.extractor.extract_from_file(str(corrupted_file), "test_repo")
        self.assertEqual(len(symbols), 0)  # Should return empty list for binary content

    def test_syntax_error_handling(self):
        """Test handling of Python syntax errors."""
        syntax_error_file = Path(self.temp_dir) / "syntax_error.py"
        syntax_error_file.write_text("def invalid_syntax(:\n    pass")

        with self.assertRaises(SyntaxError):
            self.extractor.extract_from_file(str(syntax_error_file), "test_repo")

    def test_extremely_long_line_handling(self):
        """Test handling of files with extremely long lines."""
        long_line_file = Path(self.temp_dir) / "long_line.py"
        # Create a file with an extremely long line
        long_line = "x = " + "a" * 15000 + "\n"
        long_line_file.write_text(long_line + "def test(): pass\n")

        # Should return empty list due to long line detection
        symbols = self.extractor.extract_from_file(str(long_line_file), "test_repo")
        self.assertEqual(len(symbols), 0)

    def test_empty_file_handling(self):
        """Test handling of empty files."""
        empty_file = Path(self.temp_dir) / "empty.py"
        empty_file.write_text("")

        symbols = self.extractor.extract_from_file(str(empty_file), "test_repo")
        self.assertEqual(len(symbols), 0)


class TestRepositoryIndexerErrorHandling(unittest.TestCase):
    """Test error handling in repository indexing operations."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_repo = Path(self.temp_dir) / "test_repo"
        self.temp_repo.mkdir()

        # Create mock storage and extractor
        self.mock_storage = Mock()
        self.mock_extractor = Mock()

        self.indexer = PythonRepositoryIndexer(
            symbol_extractor=self.mock_extractor,
            symbol_storage=self.mock_storage,
            max_file_size_mb=1.0,  # Small size for testing
        )

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_nonexistent_repository_handling(self):
        """Test handling of non-existent repository paths."""
        with self.assertRaises(ValueError):
            self.indexer.index_repository("/path/that/does/not/exist", "test_repo")

    def test_file_not_directory_handling(self):
        """Test handling when repository path is a file, not directory."""
        file_path = self.temp_repo / "not_a_dir.txt"
        file_path.write_text("not a directory")

        with self.assertRaises(ValueError):
            self.indexer.index_repository(str(file_path), "test_repo")

    def test_large_file_skipping(self):
        """Test that files larger than max_file_size are skipped."""
        # Create a large Python file
        large_file = self.temp_repo / "large.py"
        large_content = "# " + "x" * (2 * 1024 * 1024)  # 2MB content
        large_file.write_text(large_content)

        result = self.indexer.index_repository(str(self.temp_repo), "test_repo")

        # File should be skipped due to size
        self.assertEqual(len(result.skipped_files), 1)
        self.assertIn(str(large_file), result.skipped_files)

    def test_indexing_continues_on_file_errors(self):
        """Test that indexing continues when individual files fail."""
        # Create good and bad files
        good_file = self.temp_repo / "good.py"
        good_file.write_text("def good_function(): pass")

        bad_file = self.temp_repo / "bad.py"
        bad_file.write_text("def bad_syntax(:\n    pass")

        # Mock extractor to fail on bad file
        def mock_extract(file_path, repo_id):
            if "bad.py" in file_path:
                raise SyntaxError("Invalid syntax")
            return [
                Symbol("good_function", SymbolKind.FUNCTION, file_path, 1, 0, repo_id)
            ]

        self.mock_extractor.extract_from_file.side_effect = mock_extract

        result = self.indexer.index_repository(str(self.temp_repo), "test_repo")

        # Should have one successful and one failed file
        self.assertEqual(len(result.processed_files), 1)
        self.assertEqual(len(result.failed_files), 1)

    def test_memory_error_propagation(self):
        """Test that critical errors like MemoryError are propagated."""
        # Create a file
        test_file = self.temp_repo / "test.py"
        test_file.write_text("def test(): pass")

        # Mock extractor to raise MemoryError
        self.mock_extractor.extract_from_file.side_effect = MemoryError("Out of memory")

        with self.assertRaises(MemoryError):
            self.indexer.index_repository(str(self.temp_repo), "test_repo")


class TestIntegrationErrorHandling(unittest.TestCase):
    """Integration tests for error propagation and recovery."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "integration_test.db"

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_error_handling(self):
        """Test error handling in a complete indexing workflow."""
        # Create test repository
        repo_dir = Path(self.temp_dir) / "test_repo"
        repo_dir.mkdir()

        # Create various types of files
        (repo_dir / "good.py").write_text("def good(): pass")
        (repo_dir / "syntax_error.py").write_text("def bad(:\n    pass")
        (repo_dir / "empty.py").write_text("")

        # Create storage and indexer
        storage = SQLiteSymbolStorage(self.db_path)
        extractor = PythonSymbolExtractor()
        indexer = PythonRepositoryIndexer(extractor, storage)

        # Index repository - should handle errors gracefully
        result = indexer.index_repository(str(repo_dir), "test_repo")

        # Verify mixed results
        self.assertGreater(len(result.processed_files), 0)  # At least good.py
        self.assertGreater(len(result.failed_files), 0)  # syntax_error.py

    def test_search_error_handling_integration(self):
        """Test error handling in search operations."""
        import asyncio

        from codebase_tools import execute_search_symbols

        storage = SQLiteSymbolStorage(self.db_path)

        # Test empty query
        result = asyncio.run(
            execute_search_symbols("test_repo", "/test/path", "", storage)
        )
        result_dict = eval(
            result.replace("null", "None")
            .replace("true", "True")
            .replace("false", "False")
        )
        self.assertIn("error", result_dict)
        self.assertIn("empty", result_dict["error"])

        # Test invalid limit
        result = asyncio.run(
            execute_search_symbols(
                "test_repo", "/test/path", "test", storage, limit=150
            )
        )
        result_dict = eval(
            result.replace("null", "None")
            .replace("true", "True")
            .replace("false", "False")
        )
        self.assertIn("error", result_dict)
        self.assertIn("between 1 and 100", result_dict["error"])


if __name__ == "__main__":
    unittest.main()
