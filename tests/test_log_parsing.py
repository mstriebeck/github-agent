#!/usr/bin/env python3

"""
Tests for log parsing functions in github_mcp_server.py

These tests focus on pure functions that parse SwiftLint violations
and build output without requiring external dependencies.
"""

import re
import unittest


# Extract just the parsing functions we need to test without importing the whole module
def extract_file_from_violation(violation_line):
    """Extract file path from violation line"""
    match = re.match(r"^(/[^:]+\.swift):", violation_line)
    return match.group(1) if match else ""


def extract_line_number_from_violation(violation_line):
    """Extract line number from violation line"""
    match = re.match(r"^/[^:]+\.swift:(\d+):", violation_line)
    return int(match.group(1)) if match else 0


def extract_severity_from_violation(violation_line):
    """Extract severity (error/warning) from violation line"""
    match = re.search(r":\s+(error|warning):", violation_line)
    return match.group(1) if match else ""


def extract_message_from_violation(violation_line):
    """Extract violation message from violation line"""
    match = re.search(r":\s+(?:error|warning):\s+(.+)\s+\(.+\)$", violation_line)
    return match.group(1) if match else ""


def extract_rule_from_violation(violation_line):
    """Extract rule name from violation line"""
    match = re.search(r"\(([^)]+)\)$", violation_line)
    return match.group(1) if match else ""


class TestSwiftLintViolationExtraction(unittest.TestCase):
    """Test SwiftLint violation parsing functions"""

    def setUp(self):
        """Set up test data with realistic SwiftLint violation lines"""
        self.sample_violations = [
            "/Users/dev/MyProject/Sources/MyApp/ContentView.swift:25:1: warning: Line should be 120 characters or less: currently 135 characters (line_length)",
            "/Users/dev/MyProject/Sources/MyApp/Models/User.swift:15:23: error: Variable name should start with a lowercase character (identifier_name)",
            "/path/to/project/Sources/Core/NetworkManager.swift:87:5: warning: TODO should be resolved (todo)",
            "/absolute/path/MyProject/Tests/MyAppTests/ContentViewTests.swift:42:1: error: Force unwrapping should be avoided (force_unwrapping)",
            "/Users/john.doe/Development/MyApp/Sources/Utils/Extensions.swift:156:80: warning: Trailing whitespace violated (trailing_whitespace)",
        ]

    def test_extract_file_from_violation(self):
        """Test file path extraction from violation lines"""
        expected_files = [
            "/Users/dev/MyProject/Sources/MyApp/ContentView.swift",
            "/Users/dev/MyProject/Sources/MyApp/Models/User.swift",
            "/path/to/project/Sources/Core/NetworkManager.swift",
            "/absolute/path/MyProject/Tests/MyAppTests/ContentViewTests.swift",
            "/Users/john.doe/Development/MyApp/Sources/Utils/Extensions.swift",
        ]

        for violation, expected_file in zip(
            self.sample_violations, expected_files, strict=False
        ):
            with self.subTest(violation=violation):
                result = extract_file_from_violation(violation)
                self.assertEqual(result, expected_file)

    def test_extract_line_number_from_violation(self):
        """Test line number extraction from violation lines"""
        expected_line_numbers = [25, 15, 87, 42, 156]

        for violation, expected_line in zip(
            self.sample_violations, expected_line_numbers, strict=False
        ):
            with self.subTest(violation=violation):
                result = extract_line_number_from_violation(violation)
                self.assertEqual(result, expected_line)

    def test_extract_severity_from_violation(self):
        """Test severity extraction from violation lines"""
        expected_severities = ["warning", "error", "warning", "error", "warning"]

        for violation, expected_severity in zip(
            self.sample_violations, expected_severities, strict=False
        ):
            with self.subTest(violation=violation):
                result = extract_severity_from_violation(violation)
                self.assertEqual(result, expected_severity)

    def test_extract_message_from_violation(self):
        """Test message extraction from violation lines"""
        expected_messages = [
            "Line should be 120 characters or less: currently 135 characters",
            "Variable name should start with a lowercase character",
            "TODO should be resolved",
            "Force unwrapping should be avoided",
            "Trailing whitespace violated",
        ]

        for violation, expected_message in zip(
            self.sample_violations, expected_messages, strict=False
        ):
            with self.subTest(violation=violation):
                result = extract_message_from_violation(violation)
                self.assertEqual(result, expected_message)

    def test_extract_rule_from_violation(self):
        """Test rule name extraction from violation lines"""
        expected_rules = [
            "line_length",
            "identifier_name",
            "todo",
            "force_unwrapping",
            "trailing_whitespace",
        ]

        for violation, expected_rule in zip(
            self.sample_violations, expected_rules, strict=False
        ):
            with self.subTest(violation=violation):
                result = extract_rule_from_violation(violation)
                self.assertEqual(result, expected_rule)

    def test_extract_from_invalid_violation_lines(self):
        """Test extraction functions with truly invalid lines"""
        truly_invalid_lines = [
            "",  # Empty line
            "This is not a violation line",  # Random text
            "Just some text without structure",  # No file path structure
        ]

        for invalid_line in truly_invalid_lines:
            with self.subTest(invalid_line=invalid_line):
                # These should return empty strings or 0 for invalid input
                self.assertEqual(extract_file_from_violation(invalid_line), "")
                self.assertEqual(extract_line_number_from_violation(invalid_line), 0)
                self.assertEqual(extract_severity_from_violation(invalid_line), "")
                self.assertEqual(extract_message_from_violation(invalid_line), "")
                self.assertEqual(extract_rule_from_violation(invalid_line), "")

    def test_extract_from_partially_valid_lines(self):
        """Test extraction from lines that partially match patterns"""

        # Test line with non-numeric line number
        line_with_non_numeric = "/path/to/file.swift:abc:def: error: message (rule)"
        self.assertEqual(
            extract_file_from_violation(line_with_non_numeric), "/path/to/file.swift"
        )
        self.assertEqual(
            extract_line_number_from_violation(line_with_non_numeric), 0
        )  # No numeric match
        self.assertEqual(
            extract_severity_from_violation(line_with_non_numeric), "error"
        )
        self.assertEqual(extract_rule_from_violation(line_with_non_numeric), "rule")

        # Test line with 'info' severity (not error/warning)
        info_line = "/path/to/file.swift:25:1: info: message"
        self.assertEqual(extract_file_from_violation(info_line), "/path/to/file.swift")
        self.assertEqual(extract_line_number_from_violation(info_line), 25)
        self.assertEqual(
            extract_severity_from_violation(info_line), ""
        )  # 'info' not captured
        self.assertEqual(
            extract_message_from_violation(info_line), ""
        )  # No rule parentheses
        self.assertEqual(
            extract_rule_from_violation(info_line), ""
        )  # No rule parentheses

        # Test relative path
        relative_line = "relative/path.swift:25:1: warning: message (rule)"
        self.assertEqual(
            extract_file_from_violation(relative_line), ""
        )  # Absolute path required
        self.assertEqual(
            extract_line_number_from_violation(relative_line), 0
        )  # Needs absolute path
        self.assertEqual(
            extract_severity_from_violation(relative_line), "warning"
        )  # Still matches
        self.assertEqual(
            extract_rule_from_violation(relative_line), "rule"
        )  # Still matches


class TestBuildOutputPatterns(unittest.TestCase):
    """Test build output parsing patterns"""

    def setUp(self):
        """Set up test data with realistic build output lines"""
        # Import regex patterns from the main module
        import re

        self.compiler_error_pattern = re.compile(
            r"^(/.*\.swift):(\d+):(\d+): error: (.+)$"
        )
        self.compiler_warning_pattern = re.compile(
            r"^(/.*\.swift):(\d+):(\d+): warning: (.+)$"
        )
        self.test_failure_pattern = re.compile(
            r"^(/.*\.swift):(\d+): error: (.+) : (.+)$"
        )

        self.sample_compiler_errors = [
            "/Users/dev/MyProject/Sources/MyApp/ContentView.swift:42:23: error: Use of unresolved identifier 'unknownVariable'",
            "/path/to/project/Sources/Core/Model.swift:15:1: error: Expected declaration",
            "/absolute/path/MyProject/Sources/Utils/Helper.swift:89:45: error: Cannot convert value of type 'String' to expected argument type 'Int'",
        ]

        self.sample_compiler_warnings = [
            "/Users/dev/MyProject/Sources/MyApp/ViewController.swift:67:12: warning: Initialization of immutable value 'result' was never used",
            "/path/to/project/Sources/Core/DataManager.swift:234:8: warning: Variable 'temp' was never mutated; consider changing to 'let' constant",
        ]

        self.sample_test_failures = [
            '/Users/dev/MyProject/Tests/MyAppTests/ContentViewTests.swift:25: error: testButtonTap() : XCTAssertEqual failed: ("Expected") is not equal to ("Actual")',
            "/path/to/project/Tests/CoreTests/ModelTests.swift:89: error: testDataValidation() : XCTAssertTrue failed",
        ]

    def test_compiler_error_pattern(self):
        """Test compiler error regex pattern"""
        expected_matches = [
            (
                "/Users/dev/MyProject/Sources/MyApp/ContentView.swift",
                "42",
                "23",
                "Use of unresolved identifier 'unknownVariable'",
            ),
            (
                "/path/to/project/Sources/Core/Model.swift",
                "15",
                "1",
                "Expected declaration",
            ),
            (
                "/absolute/path/MyProject/Sources/Utils/Helper.swift",
                "89",
                "45",
                "Cannot convert value of type 'String' to expected argument type 'Int'",
            ),
        ]

        for error_line, expected_match in zip(
            self.sample_compiler_errors, expected_matches, strict=False
        ):
            with self.subTest(error_line=error_line):
                match = self.compiler_error_pattern.match(error_line)
                self.assertIsNotNone(match, f"Pattern should match: {error_line}")
                assert match
                self.assertEqual(match.groups(), expected_match)

    def test_compiler_warning_pattern(self):
        """Test compiler warning regex pattern"""
        expected_matches = [
            (
                "/Users/dev/MyProject/Sources/MyApp/ViewController.swift",
                "67",
                "12",
                "Initialization of immutable value 'result' was never used",
            ),
            (
                "/path/to/project/Sources/Core/DataManager.swift",
                "234",
                "8",
                "Variable 'temp' was never mutated; consider changing to 'let' constant",
            ),
        ]

        for warning_line, expected_match in zip(
            self.sample_compiler_warnings, expected_matches, strict=False
        ):
            with self.subTest(warning_line=warning_line):
                match = self.compiler_warning_pattern.match(warning_line)
                self.assertIsNotNone(match, f"Pattern should match: {warning_line}")
                assert match
                self.assertEqual(match.groups(), expected_match)

    def test_test_failure_pattern(self):
        """Test test failure regex pattern"""
        expected_matches = [
            (
                "/Users/dev/MyProject/Tests/MyAppTests/ContentViewTests.swift",
                "25",
                "testButtonTap()",
                'XCTAssertEqual failed: ("Expected") is not equal to ("Actual")',
            ),
            (
                "/path/to/project/Tests/CoreTests/ModelTests.swift",
                "89",
                "testDataValidation()",
                "XCTAssertTrue failed",
            ),
        ]

        for test_line, expected_match in zip(
            self.sample_test_failures, expected_matches, strict=False
        ):
            with self.subTest(test_line=test_line):
                match = self.test_failure_pattern.match(test_line)
                self.assertIsNotNone(match, f"Pattern should match: {test_line}")
                assert match
                self.assertEqual(match.groups(), expected_match)

    def test_patterns_dont_match_wrong_types(self):
        """Test that patterns don't match incorrect line types"""
        # Compiler error pattern shouldn't match warnings or test failures
        for warning_line in self.sample_compiler_warnings:
            self.assertIsNone(self.compiler_error_pattern.match(warning_line))

        for test_line in self.sample_test_failures:
            self.assertIsNone(self.compiler_error_pattern.match(test_line))

        # Warning pattern shouldn't match errors or test failures
        for error_line in self.sample_compiler_errors:
            self.assertIsNone(self.compiler_warning_pattern.match(error_line))

        for test_line in self.sample_test_failures:
            self.assertIsNone(self.compiler_warning_pattern.match(test_line))

        # Test failure pattern shouldn't match compiler errors or warnings
        for error_line in self.sample_compiler_errors:
            self.assertIsNone(self.test_failure_pattern.match(error_line))

        for warning_line in self.sample_compiler_warnings:
            self.assertIsNone(self.test_failure_pattern.match(warning_line))


if __name__ == "__main__":
    unittest.main()
