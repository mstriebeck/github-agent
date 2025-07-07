"""
Unit tests for repository indexing functionality.
"""

import tempfile
from pathlib import Path

import pytest

from python_symbol_extractor import PythonSymbolExtractor
from repository_indexer import (
    AbstractRepositoryIndexer,
    IndexingResult,
    PythonRepositoryIndexer,
)
from symbol_storage import Symbol, SymbolKind
from tests.conftest import MockSymbolExtractor


class TestIndexingResult:
    """Test the IndexingResult class."""

    def test_init(self):
        """Test IndexingResult initialization."""
        result = IndexingResult()
        assert result.processed_files == []
        assert result.failed_files == []
        assert result.total_symbols == 0
        assert result.skipped_files == []

    def test_add_processed_file(self):
        """Test adding processed files."""
        result = IndexingResult()
        result.add_processed_file("test.py", 5)
        result.add_processed_file("module.py", 3)

        assert result.processed_files == ["test.py", "module.py"]
        assert result.total_symbols == 8

    def test_add_failed_file(self):
        """Test adding failed files."""
        result = IndexingResult()
        result.add_failed_file("broken.py", "Syntax error")
        result.add_failed_file("missing.py", "File not found")

        assert result.failed_files == [
            ("broken.py", "Syntax error"),
            ("missing.py", "File not found"),
        ]

    def test_add_skipped_file(self):
        """Test adding skipped files."""
        result = IndexingResult()
        result.add_skipped_file("large.py")
        result.add_skipped_file("excluded.py")

        assert result.skipped_files == ["large.py", "excluded.py"]

    def test_success_rate(self):
        """Test success rate calculation."""
        result = IndexingResult()

        # Empty result should have 100% success rate
        assert result.success_rate == 1.0

        # Add some processed files
        result.add_processed_file("good1.py", 2)
        result.add_processed_file("good2.py", 3)
        assert result.success_rate == 1.0

        # Add failed files
        result.add_failed_file("bad1.py", "error")
        assert result.success_rate == 2 / 3  # 2 success out of 3 attempts

        result.add_failed_file("bad2.py", "error")
        assert result.success_rate == 0.5  # 2 success out of 4 attempts

    def test_str_representation(self):
        """Test string representation."""
        result = IndexingResult()
        result.add_processed_file("test.py", 5)
        result.add_failed_file("broken.py", "error")
        result.add_skipped_file("large.py")

        str_repr = str(result)
        assert "processed=1" in str_repr
        assert "failed=1" in str_repr
        assert "skipped=1" in str_repr
        assert "symbols=5" in str_repr
        assert "success_rate=50.00%" in str_repr


class TestPythonRepositoryIndexer:
    """Test the PythonRepositoryIndexer class."""

    @pytest.fixture
    def indexer(self, mock_symbol_extractor, mock_symbol_storage):
        """Create a repository indexer."""
        return PythonRepositoryIndexer(mock_symbol_extractor, mock_symbol_storage)

    def test_init(self, mock_symbol_extractor, mock_symbol_storage):
        """Test indexer initialization."""
        indexer = PythonRepositoryIndexer(mock_symbol_extractor, mock_symbol_storage)

        assert indexer.symbol_extractor is mock_symbol_extractor
        assert indexer.symbol_storage is mock_symbol_storage
        assert "__pycache__" in indexer.exclude_patterns
        assert ".git" in indexer.exclude_patterns

    def test_init_with_custom_options(self, mock_symbol_extractor, mock_symbol_storage):
        """Test indexer initialization with custom options."""
        exclude_patterns = {"custom", "exclude"}
        max_size = 5.0

        indexer = PythonRepositoryIndexer(
            mock_symbol_extractor,
            mock_symbol_storage,
            exclude_patterns=exclude_patterns,
            max_file_size_mb=max_size,
        )

        assert indexer.exclude_patterns == exclude_patterns
        assert indexer.max_file_size_bytes == 5 * 1024 * 1024

    def test_is_python_file(self, indexer):
        """Test Python file detection."""
        assert indexer._is_python_file(Path("test.py"))
        assert indexer._is_python_file(Path("module.py"))
        assert not indexer._is_python_file(Path("test.txt"))
        assert not indexer._is_python_file(Path("README.md"))
        assert not indexer._is_python_file(Path("script.sh"))

    def test_should_exclude_path(self, indexer):
        """Test path exclusion logic."""
        # Excluded directories
        assert indexer._should_exclude_path(Path("__pycache__"))
        assert indexer._should_exclude_path(Path("project/__pycache__"))
        assert indexer._should_exclude_path(Path(".git"))
        assert indexer._should_exclude_path(Path("project/.venv"))

        # Excluded files
        assert indexer._should_exclude_path(Path("test.pyc"))
        assert indexer._should_exclude_path(Path("module.pyo"))

        # Regular Python files should not be excluded
        assert not indexer._should_exclude_path(Path("test.py"))
        assert not indexer._should_exclude_path(Path("src/module.py"))

    def test_clear_repository_index(self, indexer):
        """Test clearing repository index."""
        # Clear should call delete_symbols_by_repository
        indexer.clear_repository_index("test-repo")

        # Verify the mock was called
        assert "test-repo" in indexer.symbol_storage.deleted_repositories

    def test_index_nonexistent_repository(self, indexer):
        """Test indexing nonexistent repository."""
        with pytest.raises(ValueError, match="Repository path does not exist"):
            indexer.index_repository("/nonexistent/path", "test-repo")

    def test_index_file_as_repository(self, indexer):
        """Test indexing a file instead of directory."""
        with tempfile.NamedTemporaryFile(suffix=".py") as tmp_file:
            with pytest.raises(ValueError, match="Repository path is not a directory"):
                indexer.index_repository(tmp_file.name, "test-repo")

    def test_index_empty_repository(self, indexer):
        """Test indexing an empty repository."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = indexer.index_repository(tmp_dir, "test-repo")

            assert len(result.processed_files) == 0
            assert len(result.failed_files) == 0
            assert result.total_symbols == 0
            assert result.success_rate == 1.0

    def test_index_repository_with_python_files(self, indexer):
        """Test indexing repository with Python files."""
        # Set up mock to return 2 symbols per file
        test_symbols = [
            Symbol("test_func", SymbolKind.FUNCTION, "test.py", 1, 0, "test-repo"),
            Symbol("TestClass", SymbolKind.CLASS, "test.py", 5, 0, "test-repo"),
        ]
        indexer.symbol_extractor.symbols = test_symbols

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create some Python files
            (tmp_path / "main.py").write_text("def main(): pass")
            (tmp_path / "utils.py").write_text("class Utils: pass")
            (tmp_path / "src").mkdir()
            (tmp_path / "src" / "module.py").write_text("x = 1")

            # Create non-Python files (should be ignored)
            (tmp_path / "README.md").write_text("# Project")
            (tmp_path / "config.json").write_text("{}")

            result = indexer.index_repository(tmp_dir, "test-repo")

            # Should process 3 Python files
            assert len(result.processed_files) == 3
            assert len(result.failed_files) == 0
            assert (
                result.total_symbols == 6
            )  # 2 symbols per file from mock (3 files * 2 symbols)
            assert result.success_rate == 1.0

            # Verify files were processed
            processed_names = [Path(f).name for f in result.processed_files]
            assert "main.py" in processed_names
            assert "utils.py" in processed_names
            assert "module.py" in processed_names

    def test_index_repository_with_excluded_directories(self, indexer):
        """Test indexing with excluded directories."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create Python files in main directory
            (tmp_path / "main.py").write_text("def main(): pass")

            # Create Python files in excluded directories
            (tmp_path / "__pycache__").mkdir()
            (tmp_path / "__pycache__" / "cache.py").write_text("# cached")
            (tmp_path / ".git").mkdir()
            (tmp_path / ".git" / "hooks.py").write_text("# git hooks")

            result = indexer.index_repository(tmp_dir, "test-repo")

            # Should only process main.py
            assert len(result.processed_files) == 1
            assert Path(result.processed_files[0]).name == "main.py"

    def test_index_repository_with_syntax_errors(self, mock_symbol_storage):
        """Test indexing repository with syntax error files."""
        # Create custom mock extractor that raises syntax errors

        class SyntaxErrorExtractor(MockSymbolExtractor):
            def extract_from_file(
                self, file_path: str, repository_id: str
            ) -> list[Symbol]:
                raise SyntaxError("Invalid syntax")

        mock_extractor = SyntaxErrorExtractor()
        indexer = PythonRepositoryIndexer(mock_extractor, mock_symbol_storage)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "broken.py").write_text("def broken(")  # Invalid syntax

            result = indexer.index_repository(tmp_dir, "test-repo")

            assert len(result.processed_files) == 0
            assert len(result.failed_files) == 1
            assert "File parsing error" in result.failed_files[0][1]
            assert result.success_rate == 0.0

    def test_index_repository_with_encoding_errors(self, mock_symbol_storage):
        """Test indexing repository with encoding error files."""
        # Create custom mock extractor that raises encoding errors

        class EncodingErrorExtractor(MockSymbolExtractor):
            def extract_from_file(
                self, file_path: str, repository_id: str
            ) -> list[Symbol]:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")

        mock_extractor = EncodingErrorExtractor()
        indexer = PythonRepositoryIndexer(mock_extractor, mock_symbol_storage)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "encoded.py").write_text("# file with encoding issues")

            result = indexer.index_repository(tmp_dir, "test-repo")

            assert len(result.processed_files) == 0
            assert len(result.failed_files) == 1
            assert "File parsing error" in result.failed_files[0][1]
            assert result.success_rate == 0.0

    def test_index_repository_with_large_files(self, indexer):
        """Test indexing repository with large files."""
        # Set a very small max file size
        indexer.max_file_size_bytes = 10  # 10 bytes

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create small file
            (tmp_path / "small.py").write_text("x=1")  # 3 bytes

            # Create large file
            large_content = "# " + "x" * 100  # Much larger than 10 bytes
            (tmp_path / "large.py").write_text(large_content)

            result = indexer.index_repository(tmp_dir, "test-repo")

            # Should process small file, skip large file
            assert len(result.processed_files) == 1
            assert len(result.skipped_files) == 1
            assert Path(result.processed_files[0]).name == "small.py"
            assert Path(result.skipped_files[0]).name == "large.py"

    def test_find_python_files(self, indexer):
        """Test finding Python files in directory structure."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create directory structure
            (tmp_path / "main.py").write_text("# main")
            (tmp_path / "src").mkdir()
            (tmp_path / "src" / "module.py").write_text("# module")
            (tmp_path / "tests").mkdir()
            (tmp_path / "tests" / "test_main.py").write_text("# test")
            (tmp_path / "__pycache__").mkdir()
            (tmp_path / "__pycache__" / "cached.py").write_text("# cached")
            (tmp_path / "README.md").write_text("# readme")

            files = indexer._find_python_files(tmp_path)

            # Should find 3 Python files, excluding __pycache__
            assert len(files) == 3
            file_names = [f.name for f in files]
            assert "main.py" in file_names
            assert "module.py" in file_names
            assert "test_main.py" in file_names
            assert "cached.py" not in file_names

    def test_integration_with_real_storage_and_extractor(self, temp_database):
        """Integration test with real storage and extractor."""
        # Create real extractor
        extractor = PythonSymbolExtractor()

        # Create indexer with real components
        indexer = PythonRepositoryIndexer(extractor, temp_database)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create test repository
            repo_path = Path(tmp_dir) / "test_repo"
            repo_path.mkdir()

            # Create Python files
            (repo_path / "main.py").write_text(
                """
def main():
    '''Main function.'''
    print("Hello, World!")

class Application:
    '''Application class.'''

    def run(self):
        '''Run the application.'''
        pass
"""
            )

            (repo_path / "utils.py").write_text(
                """
CONSTANT = 42

def helper():
    '''Helper function.'''
    return CONSTANT
"""
            )

            # Index the repository
            result = indexer.index_repository(str(repo_path), "integration-test")

            # Verify indexing results
            assert len(result.processed_files) == 2
            assert len(result.failed_files) == 0
            assert result.total_symbols > 0
            assert result.success_rate == 1.0

            # Verify symbols were stored - search using query parameter
            symbols = temp_database.search_symbols("", repository_id="integration-test")
            assert len(symbols) > 0

            # Check specific symbols
            symbol_names = [s.name for s in symbols]
            assert "main" in symbol_names
            assert "Application" in symbol_names
            assert "Application.run" in symbol_names
            assert "CONSTANT" in symbol_names
            assert "helper" in symbol_names

    def test_mock_indexer_default_result(self, mock_repository_indexer):
        """Test mock indexer with default result."""
        result = mock_repository_indexer.index_repository("/test/path", "test-repo")

        assert isinstance(result, IndexingResult)
        assert mock_repository_indexer.last_repository_path == "/test/path"
        assert mock_repository_indexer.last_repository_id == "test-repo"

    def test_mock_indexer_clear_functionality(self, mock_repository_indexer):
        """Test mock clear repository index."""
        mock_repository_indexer.clear_repository_index("repo1")
        mock_repository_indexer.clear_repository_index("repo2")

        assert mock_repository_indexer.clear_calls == ["repo1", "repo2"]

    def test_abstract_interface_compliance(
        self, mock_symbol_extractor, mock_symbol_storage, mock_repository_indexer
    ):
        """Test that indexers implement the abstract interface."""
        assert isinstance(
            PythonRepositoryIndexer(mock_symbol_extractor, mock_symbol_storage),
            AbstractRepositoryIndexer,
        )
        assert isinstance(mock_repository_indexer, AbstractRepositoryIndexer)
