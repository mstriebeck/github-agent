"""
Tests for memory pressure scenarios and memory management.

This module tests how the system behaves under memory constraints
and ensures proper memory management during large operations.
"""

import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from python_symbol_extractor import PythonSymbolExtractor
from repository_indexer import PythonRepositoryIndexer
from symbol_storage import SQLiteSymbolStorage, Symbol, SymbolKind


class TestMemoryPressureScenarios(unittest.TestCase):
    """Test system behavior under memory pressure."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "memory_test.db"

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)
        # Force garbage collection
        gc.collect()

    def test_large_symbol_batch_memory_usage(self):
        """Test memory usage during large symbol batch processing."""
        storage = SQLiteSymbolStorage(self.db_path)

        # Create a large number of symbols (should be processed in batches)
        symbol_count = 10000
        symbols = []

        for i in range(symbol_count):
            symbols.append(
                Symbol(
                    name=f"memory_test_symbol_{i}",
                    kind=SymbolKind.FUNCTION,
                    file_path=f"/memory/test/file_{i % 100}.py",
                    line_number=i % 1000,
                    column_number=0,
                    repository_id="memory_test_repo",
                    docstring=f"Test symbol {i} with some documentation content",
                )
            )

        # Monitor memory usage during insertion
        import os

        import psutil

        process = psutil.Process(os.getpid())
        memory_before = process.memory_info().rss

        # Insert symbols - should use batching to manage memory
        storage.insert_symbols(symbols)

        memory_after = process.memory_info().rss
        memory_increase = memory_after - memory_before

        # Memory increase should be reasonable (less than 100MB for this test)
        self.assertLess(
            memory_increase,
            100 * 1024 * 1024,
            f"Memory increase {memory_increase / 1024 / 1024:.1f}MB is too high",
        )

        # Verify all symbols were inserted
        results = storage.search_symbols(
            "memory_test_symbol", repository_id="memory_test_repo", limit=100
        )
        self.assertEqual(len(results), 100)  # Limited by query limit

    def test_memory_error_handling_in_extraction(self):
        """Test handling of MemoryError during symbol extraction."""
        extractor = PythonSymbolExtractor()

        # Create a test file
        test_file = Path(self.temp_dir) / "memory_test.py"
        test_file.write_text("def test_function(): pass")

        # Mock ast.parse to raise MemoryError
        with patch("ast.parse", side_effect=MemoryError("Simulated memory error")):
            with self.assertRaises(MemoryError):
                extractor.extract_from_file(str(test_file), "test_repo")

    def test_large_file_memory_management(self):
        """Test memory management when processing large files."""
        # Create a large Python file
        large_file = Path(self.temp_dir) / "large_file.py"

        # Create content that would consume significant memory during AST parsing
        lines = []
        for i in range(10000):
            lines.append(f"def function_{i}():")
            lines.append(f"    '''Docstring for function {i}'''")
            lines.append(f"    variable_{i} = 'value_{i}'")
            lines.append(f"    return variable_{i}")
            lines.append("")

        large_file.write_text("\n".join(lines))

        # Extract symbols from large file
        extractor = PythonSymbolExtractor()

        # Monitor memory during extraction
        import os

        import psutil

        process = psutil.Process(os.getpid())
        memory_before = process.memory_info().rss

        symbols = extractor.extract_from_file(str(large_file), "large_repo")

        memory_after = process.memory_info().rss
        memory_increase = memory_after - memory_before

        # Should have extracted many symbols
        self.assertGreater(len(symbols), 10000)

        # Memory increase should be reasonable
        self.assertLess(
            memory_increase,
            200 * 1024 * 1024,
            f"Memory increase {memory_increase / 1024 / 1024:.1f}MB is too high",
        )

    def test_indexer_memory_management_with_many_files(self):
        """Test memory management when indexing many files."""
        # Create test repository with many files
        repo_dir = Path(self.temp_dir) / "many_files_repo"
        repo_dir.mkdir()

        # Create many small Python files
        file_count = 1000
        for i in range(file_count):
            file_path = repo_dir / f"file_{i}.py"
            file_path.write_text(
                f"""
def function_{i}():
    '''Function {i} docstring'''
    return {i}

class Class_{i}:
    '''Class {i} docstring'''
    def method_{i}(self):
        return {i}
"""
            )

        # Create storage and indexer
        storage = SQLiteSymbolStorage(self.db_path)
        extractor = PythonSymbolExtractor()
        indexer = PythonRepositoryIndexer(extractor, storage)

        # Monitor memory during indexing
        import os

        import psutil

        process = psutil.Process(os.getpid())
        memory_before = process.memory_info().rss

        # Index repository
        result = indexer.index_repository(str(repo_dir), "many_files_repo")

        memory_after = process.memory_info().rss
        memory_increase = memory_after - memory_before

        # Should have processed all files
        self.assertEqual(len(result.processed_files), file_count)

        # Memory increase should be reasonable for 1000 files
        self.assertLess(
            memory_increase,
            500 * 1024 * 1024,
            f"Memory increase {memory_increase / 1024 / 1024:.1f}MB is too high",
        )

    def test_database_memory_management_large_queries(self):
        """Test memory management during large database queries."""
        storage = SQLiteSymbolStorage(self.db_path)

        # Insert a large number of symbols first
        symbols = []
        for i in range(5000):
            symbols.append(
                Symbol(
                    name=f"query_test_symbol_{i}",
                    kind=SymbolKind.FUNCTION,
                    file_path=f"/query/test/file_{i % 50}.py",
                    line_number=i % 100,
                    column_number=0,
                    repository_id="query_test_repo",
                )
            )

        storage.insert_symbols(symbols)

        # Monitor memory during large queries
        import os

        import psutil

        process = psutil.Process(os.getpid())
        memory_before = process.memory_info().rss

        # Perform multiple large queries
        for _ in range(10):
            results = storage.search_symbols(
                "query_test_symbol", repository_id="query_test_repo", limit=100
            )
            self.assertEqual(len(results), 100)

        memory_after = process.memory_info().rss
        memory_increase = memory_after - memory_before

        # Memory increase should be minimal for queries
        self.assertLess(
            memory_increase,
            50 * 1024 * 1024,
            f"Memory increase {memory_increase / 1024 / 1024:.1f}MB is too high for queries",
        )

    def test_recovery_from_memory_pressure(self):
        """Test system recovery after memory pressure events."""
        storage = SQLiteSymbolStorage(self.db_path)

        # Simulate memory pressure by creating and destroying large objects
        large_objects = []
        try:
            # Create objects that consume memory
            for _i in range(100):
                large_objects.append([f"data_{j}" for j in range(10000)])

            # Try to perform database operations under memory pressure
            symbol = Symbol(
                name="pressure_test",
                kind=SymbolKind.FUNCTION,
                file_path="/pressure/test.py",
                line_number=1,
                column_number=0,
                repository_id="pressure_repo",
            )

            storage.insert_symbol(symbol)

            # Verify symbol was inserted
            results = storage.search_symbols(
                "pressure_test", repository_id="pressure_repo"
            )
            self.assertEqual(len(results), 1)

        finally:
            # Release memory pressure
            large_objects.clear()
            gc.collect()

        # System should still be functional after memory pressure
        another_symbol = Symbol(
            name="after_pressure_test",
            kind=SymbolKind.FUNCTION,
            file_path="/after/pressure.py",
            line_number=1,
            column_number=0,
            repository_id="pressure_repo",
        )

        storage.insert_symbol(another_symbol)
        results = storage.search_symbols(
            "after_pressure_test", repository_id="pressure_repo"
        )
        self.assertEqual(len(results), 1)

    def test_graceful_degradation_under_memory_limits(self):
        """Test graceful degradation when approaching memory limits."""
        # This test simulates what happens when the system approaches memory limits
        extractor = PythonSymbolExtractor()

        # Create a file that would normally succeed
        normal_file = Path(self.temp_dir) / "normal.py"
        normal_file.write_text("def normal_function(): pass")

        # Mock memory pressure during extraction
        original_parse = __import__("ast").parse

        def memory_limited_parse(*args, **kwargs):
            # Simulate memory pressure by limiting available operations
            if len(args[0]) > 100:  # If source is large
                raise MemoryError("Simulated memory pressure")
            return original_parse(*args, **kwargs)

        with patch("ast.parse", side_effect=memory_limited_parse):
            # Small file should still work
            symbols = extractor.extract_from_file(str(normal_file), "test_repo")
            self.assertGreater(len(symbols), 0)

            # Large content should fail gracefully
            large_content = "def large(): pass\n" * 1000
            large_file = Path(self.temp_dir) / "large.py"
            large_file.write_text(large_content)

            with self.assertRaises(MemoryError):
                extractor.extract_from_file(str(large_file), "test_repo")


if __name__ == "__main__":
    unittest.main()
