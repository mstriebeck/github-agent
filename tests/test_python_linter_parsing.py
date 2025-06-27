#!/usr/bin/env python3

"""
Tests for Python linter error parsing functions in github_tools.py

Tests for parsing ruff and mypy error outputs.
"""

import os
import sys
import unittest

# Add parent directory to path to import the main module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from github_tools import (
    extract_file_from_ruff_error,
    extract_line_number_from_ruff_error,
    extract_column_from_ruff_error,
    extract_rule_from_ruff_error,
    extract_message_from_ruff_error,
    extract_file_from_mypy_error,
    extract_line_number_from_mypy_error,
    extract_message_from_mypy_error,
    extract_error_code_from_mypy_error,
)


class TestRuffErrorParsing(unittest.TestCase):
    """Test ruff error parsing functions"""

    def setUp(self):
        """Set up test data with realistic ruff error lines"""
        self.sample_ruff_errors = [
            "::error title=Ruff (UP045),file=/Volumes/Code/github-agent/github_tools.py,line=503,col=49,endLine=503,endColumn=62::github_tools.py:503:49: UP045 Use `X | None` for type annotations",
            "::error title=Ruff (E501),file=/path/to/project/src/main.py,line=42,col=80,endLine=42,endColumn=120::main.py:42:80: E501 line too long (120 > 79 characters)",
            "::error title=Ruff (F401),file=/Users/dev/project/utils/helpers.py,line=15,col=1,endLine=15,endColumn=20::helpers.py:15:1: F401 'os' imported but unused",
        ]

    def test_extract_file_from_ruff_error(self):
        """Test file path extraction from ruff error lines"""
        expected_files = [
            "/Volumes/Code/github-agent/github_tools.py",
            "/path/to/project/src/main.py",
            "/Users/dev/project/utils/helpers.py",
        ]

        for error_line, expected_file in zip(self.sample_ruff_errors, expected_files, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_file_from_ruff_error(error_line)
                self.assertEqual(result, expected_file)

    def test_extract_line_number_from_ruff_error(self):
        """Test line number extraction from ruff error lines"""
        expected_line_numbers = [503, 42, 15]

        for error_line, expected_line in zip(self.sample_ruff_errors, expected_line_numbers, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_line_number_from_ruff_error(error_line)
                self.assertEqual(result, expected_line)

    def test_extract_column_from_ruff_error(self):
        """Test column number extraction from ruff error lines"""
        expected_columns = [49, 80, 1]

        for error_line, expected_col in zip(self.sample_ruff_errors, expected_columns, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_column_from_ruff_error(error_line)
                self.assertEqual(result, expected_col)

    def test_extract_rule_from_ruff_error(self):
        """Test rule code extraction from ruff error lines"""
        expected_rules = ["UP045", "E501", "F401"]

        for error_line, expected_rule in zip(self.sample_ruff_errors, expected_rules, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_rule_from_ruff_error(error_line)
                self.assertEqual(result, expected_rule)

    def test_extract_message_from_ruff_error(self):
        """Test message extraction from ruff error lines"""
        expected_messages = [
            "github_tools.py:503:49: UP045 Use `X | None` for type annotations",
            "main.py:42:80: E501 line too long (120 > 79 characters)",
            "helpers.py:15:1: F401 'os' imported but unused",
        ]

        for error_line, expected_message in zip(self.sample_ruff_errors, expected_messages, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_message_from_ruff_error(error_line)
                self.assertEqual(result, expected_message)

    def test_extract_from_invalid_ruff_lines(self):
        """Test extraction functions with invalid ruff lines"""
        invalid_lines = [
            "",  # Empty line
            "This is not a ruff error line",  # Random text
            "::error title=SomeOtherTool,file=/path/file.py::message",  # Different tool
        ]

        for invalid_line in invalid_lines:
            with self.subTest(invalid_line=invalid_line):
                # These should return empty strings or 0 for invalid input
                self.assertEqual(extract_file_from_ruff_error(invalid_line), "")
                self.assertEqual(extract_line_number_from_ruff_error(invalid_line), 0)
                self.assertEqual(extract_column_from_ruff_error(invalid_line), 0)
                self.assertEqual(extract_rule_from_ruff_error(invalid_line), "")
                self.assertEqual(extract_message_from_ruff_error(invalid_line), "")


class TestMypyErrorParsing(unittest.TestCase):
    """Test mypy error parsing functions"""

    def setUp(self):
        """Set up test data with realistic mypy error lines"""
        self.sample_mypy_errors = [
            "tests/test_resource_manager.py:391: error: Cannot assign to a method  [method-assign]",
            "src/main.py:25: error: Incompatible types in assignment (expression has type \"str\", variable has type \"int\")  [assignment]",
            "utils/helpers.py:156: error: Argument 1 to \"open\" has incompatible type \"int\"; expected \"str\"  [arg-type]",
            "models/user.py:42: error: Missing return statement  [return]",
        ]

    def test_extract_file_from_mypy_error(self):
        """Test file path extraction from mypy error lines"""
        expected_files = [
            "tests/test_resource_manager.py",
            "src/main.py",
            "utils/helpers.py",
            "models/user.py",
        ]

        for error_line, expected_file in zip(self.sample_mypy_errors, expected_files, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_file_from_mypy_error(error_line)
                self.assertEqual(result, expected_file)

    def test_extract_line_number_from_mypy_error(self):
        """Test line number extraction from mypy error lines"""
        expected_line_numbers = [391, 25, 156, 42]

        for error_line, expected_line in zip(self.sample_mypy_errors, expected_line_numbers, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_line_number_from_mypy_error(error_line)
                self.assertEqual(result, expected_line)

    def test_extract_message_from_mypy_error(self):
        """Test message extraction from mypy error lines"""
        expected_messages = [
            "Cannot assign to a method",
            "Incompatible types in assignment (expression has type \"str\", variable has type \"int\")",
            "Argument 1 to \"open\" has incompatible type \"int\"; expected \"str\"",
            "Missing return statement",
        ]

        for error_line, expected_message in zip(self.sample_mypy_errors, expected_messages, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_message_from_mypy_error(error_line)
                self.assertEqual(result, expected_message)

    def test_extract_error_code_from_mypy_error(self):
        """Test error code extraction from mypy error lines"""
        expected_codes = ["method-assign", "assignment", "arg-type", "return"]

        for error_line, expected_code in zip(self.sample_mypy_errors, expected_codes, strict=False):
            with self.subTest(error_line=error_line):
                result = extract_error_code_from_mypy_error(error_line)
                self.assertEqual(result, expected_code)

    def test_extract_from_invalid_mypy_lines(self):
        """Test extraction functions with invalid mypy lines"""
        invalid_lines = [
            "",  # Empty line
            "This is not a mypy error line",  # Random text
            "file.txt:25: info: Some info message",  # Not an error
            "file.py:abc: error: Invalid line number",  # Non-numeric line
        ]

        for invalid_line in invalid_lines:
            with self.subTest(invalid_line=invalid_line):
                # These should return empty strings or 0 for invalid input
                self.assertEqual(extract_file_from_mypy_error(invalid_line), "")
                self.assertEqual(extract_line_number_from_mypy_error(invalid_line), 0)
                self.assertEqual(extract_message_from_mypy_error(invalid_line), "")
                self.assertEqual(extract_error_code_from_mypy_error(invalid_line), "")

    def test_mypy_error_without_error_code(self):
        """Test mypy error line without error code brackets"""
        error_without_code = "src/main.py:25: error: Some error message"
        
        self.assertEqual(extract_file_from_mypy_error(error_without_code), "src/main.py")
        self.assertEqual(extract_line_number_from_mypy_error(error_without_code), 25)
        self.assertEqual(extract_message_from_mypy_error(error_without_code), "Some error message")
        self.assertEqual(extract_error_code_from_mypy_error(error_without_code), "")


if __name__ == "__main__":
    unittest.main()
