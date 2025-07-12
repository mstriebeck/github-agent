#!/usr/bin/env python3

"""
Integration tests for the startup orchestrator module.
"""

import tempfile
import time
from pathlib import Path

import pytest

from constants import Language
from python_symbol_extractor import PythonSymbolExtractor
from repository_indexer import PythonRepositoryIndexer
from repository_manager import RepositoryConfig
from startup_orchestrator import CodebaseStartupOrchestrator, IndexingStatusEnum
from symbol_storage import SQLiteSymbolStorage


class TestStartupOrchestratorIntegration:
    """Integration tests for startup orchestrator."""

    @pytest.mark.asyncio
    async def test_full_startup_sequence_single_repository(self):
        """Test complete startup sequence with a single Python repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo_dir = Path(temp_dir) / "test_repo"
            repo_dir.mkdir()

            # Create multiple Python files with various symbols
            (repo_dir / "__init__.py").write_text("")
            (repo_dir / "main.py").write_text(
                """
\"\"\"Main module for testing.\"\"\"

def main():
    \"\"\"Main function.\"\"\"
    pass

class Application:
    \"\"\"Application class.\"\"\"

    def __init__(self):
        self.name = "test"

    def run(self):
        \"\"\"Run the application.\"\"\"
        pass

CONSTANT = "value"
            """
            )

            (repo_dir / "utils.py").write_text(
                """
\"\"\"Utility functions.\"\"\"

def helper_function(x, y):
    \"\"\"A helper function.\"\"\"
    return x + y

class Helper:
    \"\"\"Helper class.\"\"\"

    @staticmethod
    def static_method():
        \"\"\"Static method.\"\"\"
        return True
            """
            )

            # Create subdirectory with more files
            sub_dir = repo_dir / "submodule"
            sub_dir.mkdir()
            (sub_dir / "__init__.py").write_text("")
            (sub_dir / "processor.py").write_text(
                """
\"\"\"Data processor.\"\"\"

class DataProcessor:
    \"\"\"Processes data.\"\"\"

    def process(self, data):
        \"\"\"Process the data.\"\"\"
        return data.upper()
            """
            )

            # Create orchestrator with dependency injection
            db_path = data_dir / "symbols.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Create repository config
            python_repo = RepositoryConfig(
                name="test-repo",
                workspace=str(repo_dir),
                description="Test Python repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="testowner",
                github_repo="testrepo",
            )

            start_time = time.time()
            result = await orchestrator.initialize_repositories([python_repo])
            elapsed_time = time.time() - start_time

            # Verify results
            assert result.total_repositories == 1
            assert result.indexed_repositories == 1
            assert result.failed_repositories == 0
            assert result.skipped_repositories == 0
            assert result.success_rate == 1.0
            assert (
                result.startup_duration <= elapsed_time + 1.0
            )  # Allow for timing differences
            assert len(result.indexing_statuses) == 1

            status = result.indexing_statuses[0]
            assert status.repository_id == "test-repo"
            assert status.status == IndexingStatusEnum.COMPLETED
            assert status.result is not None
            assert (
                status.result.total_symbols >= 6
            )  # At least main, Application, run, helper_function, Helper, DataProcessor
            assert (
                len(status.result.processed_files) >= 3
            )  # main.py, utils.py, processor.py
            assert status.duration is not None
            assert status.duration > 0

    @pytest.mark.asyncio
    async def test_full_startup_sequence_multiple_repositories(self):
        """Test complete startup sequence with multiple repositories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            # Create first Python repository
            repo1_dir = Path(temp_dir) / "repo1"
            repo1_dir.mkdir()
            (repo1_dir / "module1.py").write_text(
                """
def function1():
    \"\"\"Function 1.\"\"\"
    pass

class Class1:
    \"\"\"Class 1.\"\"\"
    pass
            """
            )

            # Create second Python repository
            repo2_dir = Path(temp_dir) / "repo2"
            repo2_dir.mkdir()
            (repo2_dir / "module2.py").write_text(
                """
def function2():
    \"\"\"Function 2.\"\"\"
    pass

class Class2:
    \"\"\"Class 2.\"\"\"
    pass
            """
            )

            # Create Swift repository (should be skipped)
            repo3_dir = Path(temp_dir) / "repo3"
            repo3_dir.mkdir()
            (repo3_dir / "main.swift").write_text(
                """
import Foundation

class SwiftClass {
    func method() {}
}
            """
            )

            # Create orchestrator with dependency injection
            db_path = data_dir / "symbols.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Create repository configs
            python_repo1 = RepositoryConfig(
                name="python-repo-1",
                workspace=str(repo1_dir),
                description="First Python repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner1",
                github_repo="repo1",
            )

            python_repo2 = RepositoryConfig(
                name="python-repo-2",
                workspace=str(repo2_dir),
                description="Second Python repository",
                language=Language.PYTHON,
                port=8081,
                python_path="/usr/bin/python3",
                github_owner="owner2",
                github_repo="repo2",
            )

            swift_repo = RepositoryConfig(
                name="swift-repo",
                workspace=str(repo3_dir),
                description="Swift repository",
                language=Language.SWIFT,
                port=8082,
                python_path="/usr/bin/python3",
                github_owner="owner3",
                github_repo="repo3",
            )

            repositories = [python_repo1, python_repo2, swift_repo]
            result = await orchestrator.initialize_repositories(repositories)

            # Verify results
            assert result.total_repositories == 3
            assert result.indexed_repositories == 2  # Two Python repos
            assert result.failed_repositories == 0
            assert result.skipped_repositories == 1  # Swift repo
            assert result.success_rate == 1.0
            assert len(result.indexing_statuses) == 2  # Only Python repos

            # Check individual statuses
            status1 = next(
                s
                for s in result.indexing_statuses
                if s.repository_id == "python-repo-1"
            )
            status2 = next(
                s
                for s in result.indexing_statuses
                if s.repository_id == "python-repo-2"
            )

            assert status1.status == IndexingStatusEnum.COMPLETED
            assert status1.result is not None
            assert status1.result.total_symbols >= 2  # function1, Class1

            assert status2.status == IndexingStatusEnum.COMPLETED
            assert status2.result is not None
            assert status2.result.total_symbols >= 2  # function2, Class2

    @pytest.mark.asyncio
    async def test_startup_with_mixed_success_and_failure(self):
        """Test startup with some repositories succeeding and others failing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            # Create working Python repository
            good_repo_dir = Path(temp_dir) / "good_repo"
            good_repo_dir.mkdir()
            (good_repo_dir / "module.py").write_text(
                """
def working_function():
    \"\"\"A working function.\"\"\"
    pass
            """
            )

            # Create orchestrator with dependency injection
            db_path = data_dir / "symbols.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Create mixed repository configs
            good_repo = RepositoryConfig(
                name="good-repo",
                workspace=str(good_repo_dir),
                description="Working repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner1",
                github_repo="good",
            )

            bad_repo = RepositoryConfig(
                name="bad-repo",
                workspace="/nonexistent/path",
                description="Non-existent repository",
                language=Language.PYTHON,
                port=8081,
                python_path="/usr/bin/python3",
                github_owner="owner2",
                github_repo="bad",
            )

            repositories = [good_repo, bad_repo]
            result = await orchestrator.initialize_repositories(repositories)

            # Verify results
            assert result.total_repositories == 2
            assert result.indexed_repositories == 1
            assert result.failed_repositories == 1
            assert result.skipped_repositories == 0
            assert result.success_rate == 0.5
            assert len(result.indexing_statuses) == 2

            # Check individual statuses
            good_status = next(
                s for s in result.indexing_statuses if s.repository_id == "good-repo"
            )
            bad_status = next(
                s for s in result.indexing_statuses if s.repository_id == "bad-repo"
            )

            assert good_status.status == IndexingStatusEnum.COMPLETED
            assert good_status.result is not None
            assert good_status.result.total_symbols >= 1

            assert bad_status.status == IndexingStatusEnum.FAILED
            assert bad_status.error_message is not None
            assert (
                "does not exist" in bad_status.error_message.lower()
                or "not found" in bad_status.error_message.lower()
            )

    @pytest.mark.asyncio
    async def test_performance_with_larger_repository(self):
        """Test performance with a larger repository containing many files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo_dir = Path(temp_dir) / "large_repo"
            repo_dir.mkdir()

            # Create many Python files
            num_files = 20
            symbols_per_file = 5

            for i in range(num_files):
                content = f'"""Module {i}."""\n\n'
                for j in range(symbols_per_file):
                    content += f"""
def function_{i}_{j}():
    \"\"\"Function {i}_{j}.\"\"\"
    pass

class Class_{i}_{j}:
    \"\"\"Class {i}_{j}.\"\"\"

    def method_{i}_{j}(self):
        \"\"\"Method {i}_{j}.\"\"\"
        pass
                    """

                (repo_dir / f"module_{i}.py").write_text(content)

            # Create orchestrator with dependency injection
            db_path = data_dir / "symbols.db"
            storage = SQLiteSymbolStorage(str(db_path))
            extractor = PythonSymbolExtractor()
            indexer = PythonRepositoryIndexer(extractor, storage)
            orchestrator = CodebaseStartupOrchestrator(storage, extractor, indexer)

            # Create repository config
            large_repo = RepositoryConfig(
                name="large-repo",
                workspace=str(repo_dir),
                description="Large test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="large",
            )

            start_time = time.time()
            result = await orchestrator.initialize_repositories([large_repo])
            elapsed_time = time.time() - start_time

            # Verify results
            assert result.total_repositories == 1
            assert result.indexed_repositories == 1
            assert result.failed_repositories == 0
            assert result.success_rate == 1.0
            assert len(result.indexing_statuses) == 1

            status = result.indexing_statuses[0]
            assert status.status == IndexingStatusEnum.COMPLETED
            assert status.result is not None

            # Should have processed all files
            assert len(status.result.processed_files) == num_files

            # Should have found all symbols (functions, classes, methods)
            expected_symbols = (
                num_files * symbols_per_file * 3
            )  # function, class, method per iteration
            assert (
                status.result.total_symbols >= expected_symbols * 0.9
            )  # Allow 10% tolerance

            # Should complete in reasonable time (adjust threshold as needed)
            assert elapsed_time < 30.0  # Should complete within 30 seconds

            # Log performance metrics for visibility
            print("Performance test results:")
            print(f"  Files: {num_files}")
            print(f"  Symbols: {status.result.total_symbols}")
            print(f"  Time: {elapsed_time:.2f}s")
            print(
                f"  Rate: {status.result.total_symbols / elapsed_time:.1f} symbols/sec"
            )

    @pytest.mark.asyncio
    async def test_database_persistence_across_runs(self):
        """Test that database persists symbols across multiple runs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo_dir = Path(temp_dir) / "test_repo"
            repo_dir.mkdir()

            (repo_dir / "persistent.py").write_text(
                """
def persistent_function():
    \"\"\"A persistent function.\"\"\"
    pass

class PersistentClass:
    \"\"\"A persistent class.\"\"\"
    pass
            """
            )

            # First run
            db_path = data_dir / "symbols.db"
            storage1 = SQLiteSymbolStorage(str(db_path))
            extractor1 = PythonSymbolExtractor()
            indexer1 = PythonRepositoryIndexer(extractor1, storage1)
            orchestrator1 = CodebaseStartupOrchestrator(storage1, extractor1, indexer1)

            repo_config = RepositoryConfig(
                name="persistent-repo",
                workspace=str(repo_dir),
                description="Persistent repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
                github_owner="owner",
                github_repo="persistent",
            )

            result1 = await orchestrator1.initialize_repositories([repo_config])

            assert result1.indexed_repositories == 1
            assert result1.indexing_statuses[0].result is not None
            first_run_symbols = result1.indexing_statuses[0].result.total_symbols

            # Second run with new orchestrator instance
            storage2 = SQLiteSymbolStorage(str(db_path))
            extractor2 = PythonSymbolExtractor()
            indexer2 = PythonRepositoryIndexer(extractor2, storage2)
            orchestrator2 = CodebaseStartupOrchestrator(storage2, extractor2, indexer2)
            result2 = await orchestrator2.initialize_repositories([repo_config])

            assert result2.indexed_repositories == 1
            assert result2.indexing_statuses[0].result is not None
            second_run_symbols = result2.indexing_statuses[0].result.total_symbols

            # Should have same number of symbols (data was cleared and re-indexed)
            assert second_run_symbols == first_run_symbols

            # Database file should exist
            assert (data_dir / "symbols.db").exists()
