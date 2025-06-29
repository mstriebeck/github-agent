#!/usr/bin/env python3

"""
Tests for utility functions extracted from github_mcp_server.py

These test pure logic functions that can be tested without external dependencies.
"""

import os
import re
import tempfile
import unittest


def parse_github_remote_url(remote_url):
    """Extract repo name from GitHub remote URL"""
    if remote_url.startswith("git@github.com:"):
        _, path = remote_url.split(":", 1)
    elif remote_url.startswith("https://github.com/"):
        path = remote_url.split("github.com/", 1)[-1]
    else:
        raise ValueError(f"Unrecognized GitHub remote URL: {remote_url}")
    return path.replace(".git", "")


def find_matching_workflow_run(workflow_runs, target_commit):
    """
    Find workflow run matching commit with fallback strategy
    Returns the run ID or None if no runs available
    """
    if not workflow_runs:
        return None

    # Look for exact match
    for run in workflow_runs:
        if run["head_sha"] == target_commit:
            return run["id"]

    # Look for partial match (first 8 characters)
    short_commit = target_commit[:8]
    for run in workflow_runs:
        if run["head_sha"].startswith(short_commit):
            return run["id"]

    # Fallback to most recent workflow run
    latest_run = workflow_runs[0]
    return latest_run["id"]


def find_file_with_alternatives(directory, primary_filename, alternatives):
    """
    Find a file in directory, trying primary name first, then alternatives
    Returns the found file path or None if not found
    """
    primary_path = os.path.join(directory, primary_filename)
    if os.path.exists(primary_path):
        return primary_path

    # Try alternatives
    for alt_name in alternatives:
        alt_path = os.path.join(directory, alt_name)
        if os.path.exists(alt_path):
            return alt_path

    return None


def is_swiftlint_violation_line(line):
    """Check if a line matches SwiftLint violation pattern"""
    violation_pattern = re.compile(
        r"^/.+\.swift:\d+:\d+:\s+(error|warning):\s+.+\s+\(.+\)$"
    )
    return bool(violation_pattern.match(line.strip()))


class TestGitHubURLParsing(unittest.TestCase):
    """Test GitHub remote URL parsing"""

    def test_parse_ssh_urls(self):
        """Test parsing SSH-style GitHub URLs"""
        test_cases = [
            ("git@github.com:owner/repo.git", "owner/repo"),
            ("git@github.com:microsoft/vscode.git", "microsoft/vscode"),
            ("git@github.com:facebook/react.git", "facebook/react"),
            ("git@github.com:owner/repo-with-dashes.git", "owner/repo-with-dashes"),
            (
                "git@github.com:owner/repo_with_underscores.git",
                "owner/repo_with_underscores",
            ),
        ]

        for url, expected_repo in test_cases:
            with self.subTest(url=url):
                result = parse_github_remote_url(url)
                self.assertEqual(result, expected_repo)

    def test_parse_https_urls(self):
        """Test parsing HTTPS GitHub URLs"""
        test_cases = [
            ("https://github.com/owner/repo.git", "owner/repo"),
            ("https://github.com/microsoft/vscode.git", "microsoft/vscode"),
            ("https://github.com/facebook/react.git", "facebook/react"),
            ("https://github.com/owner/repo", "owner/repo"),  # No .git suffix
            ("https://github.com/owner/repo-with-dashes.git", "owner/repo-with-dashes"),
        ]

        for url, expected_repo in test_cases:
            with self.subTest(url=url):
                result = parse_github_remote_url(url)
                self.assertEqual(result, expected_repo)

    def test_parse_invalid_urls(self):
        """Test parsing invalid URLs raises ValueError"""
        invalid_urls = [
            "ftp://github.com/owner/repo.git",
            "not-a-url",
            "https://gitlab.com/owner/repo.git",
            "git@gitlab.com:owner/repo.git",
            "",
        ]

        for invalid_url in invalid_urls:
            with self.subTest(url=invalid_url):
                with self.assertRaises(ValueError):
                    parse_github_remote_url(invalid_url)


class TestWorkflowRunMatching(unittest.TestCase):
    """Test workflow run matching logic"""

    def setUp(self):
        """Set up sample workflow run data"""
        self.sample_runs = [
            {"id": "run_1", "head_sha": "abc123def456789012345678901234567890abcd"},
            {"id": "run_2", "head_sha": "def45600123456789012345678901234567890ef"},
            {"id": "run_3", "head_sha": "123456789012345678901234567890abcdef1234"},
            {"id": "run_4", "head_sha": "987654321098765432109876543210fedcba9876"},
        ]

    def test_exact_commit_match(self):
        """Test exact commit SHA matching"""
        target_commit = "abc123def456789012345678901234567890abcd"
        result = find_matching_workflow_run(self.sample_runs, target_commit)
        self.assertEqual(result, "run_1")

    def test_partial_commit_match(self):
        """Test partial commit SHA matching (first 8 chars)"""
        target_commit = (
            "def45600ffffffffffffffffffffffffffffffff"  # Only first 8 match run_2
        )
        result = find_matching_workflow_run(self.sample_runs, target_commit)
        self.assertEqual(result, "run_2")

    def test_fallback_to_latest(self):
        """Test fallback to most recent run when no match found"""
        target_commit = "nonexistent_commit_sha_that_matches_nothing"
        result = find_matching_workflow_run(self.sample_runs, target_commit)
        self.assertEqual(result, "run_1")  # First in list is most recent

    def test_empty_workflow_runs(self):
        """Test behavior with empty workflow runs list"""
        result = find_matching_workflow_run([], "any_commit")
        self.assertIsNone(result)

    def test_exact_match_priority(self):
        """Test that exact match takes priority over partial match"""
        runs_with_collision = [
            {"id": "exact_match", "head_sha": "abc12345"},
            {
                "id": "partial_match",
                "head_sha": "abc12300000000000000000000000000000000",
            },
        ]
        target_commit = "abc12345"
        result = find_matching_workflow_run(runs_with_collision, target_commit)
        self.assertEqual(result, "exact_match")


class TestFileWithAlternatives(unittest.TestCase):
    """Test file finding with alternative names"""

    def setUp(self):
        """Create temporary directory with test files"""
        self.temp_dir = tempfile.mkdtemp()

        # Create some test files
        self.primary_file = os.path.join(self.temp_dir, "primary.txt")
        self.alt1_file = os.path.join(self.temp_dir, "alternative1.txt")
        self.alt2_file = os.path.join(self.temp_dir, "alternative2.txt")

        with open(self.alt1_file, "w") as f:
            f.write("alternative1 content")
        with open(self.alt2_file, "w") as f:
            f.write("alternative2 content")

    def tearDown(self):
        """Clean up temporary directory"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_primary_file_exists(self):
        """Test finding primary file when it exists"""
        with open(self.primary_file, "w") as f:
            f.write("primary content")

        alternatives = ["alternative1.txt", "alternative2.txt"]
        result = find_file_with_alternatives(self.temp_dir, "primary.txt", alternatives)
        self.assertEqual(result, self.primary_file)

    def test_first_alternative_found(self):
        """Test finding first alternative when primary doesn't exist"""
        alternatives = ["alternative1.txt", "alternative2.txt"]
        result = find_file_with_alternatives(self.temp_dir, "primary.txt", alternatives)
        self.assertEqual(result, self.alt1_file)

    def test_second_alternative_found(self):
        """Test finding second alternative when first doesn't exist"""
        os.remove(self.alt1_file)  # Remove first alternative
        alternatives = ["alternative1.txt", "alternative2.txt"]
        result = find_file_with_alternatives(self.temp_dir, "primary.txt", alternatives)
        self.assertEqual(result, self.alt2_file)

    def test_no_files_found(self):
        """Test when no files are found"""
        alternatives = ["nonexistent1.txt", "nonexistent2.txt"]
        result = find_file_with_alternatives(self.temp_dir, "primary.txt", alternatives)
        self.assertIsNone(result)

    def test_empty_alternatives(self):
        """Test with empty alternatives list"""
        result = find_file_with_alternatives(self.temp_dir, "primary.txt", [])
        self.assertIsNone(result)


class TestSwiftLintViolationPattern(unittest.TestCase):
    """Test SwiftLint violation line pattern matching"""

    def test_valid_violation_lines(self):
        """Test lines that should match SwiftLint violation pattern"""
        valid_lines = [
            "/Users/dev/MyProject/Sources/MyApp/ContentView.swift:25:1: warning: Line should be 120 characters or less (line_length)",
            "/path/to/project/Sources/Core/NetworkManager.swift:87:5: error: Force unwrapping should be avoided (force_unwrapping)",
            "/absolute/path/MyProject/Tests/MyAppTests/ContentViewTests.swift:42:1: warning: TODO should be resolved (todo)",
            "/Users/john.doe/Development/MyApp/Sources/Utils/Extensions.swift:156:80: error: Variable name should start with a lowercase character (identifier_name)",
        ]

        for line in valid_lines:
            with self.subTest(line=line):
                self.assertTrue(is_swiftlint_violation_line(line))

    def test_invalid_violation_lines(self):
        """Test lines that should NOT match SwiftLint violation pattern"""
        invalid_lines = [
            "",  # Empty line
            "Building for iOS Simulator",  # Build status
            "SwiftLint found 0 violations",  # Summary line
            "relative/path.swift:25:1: warning: message (rule)",  # Relative path
            "/path/to/file.swift:25:1: info: message (rule)",  # Info severity (not error/warning)
            "/path/to/file.swift:25:1: warning: message",  # Missing rule parentheses
            "/path/to/file.txt:25:1: warning: message (rule)",  # Not a .swift file
            "Just some random text",  # Random text
            "/path/to/file.swift: warning: message (rule)",  # Missing line:column
        ]

        for line in invalid_lines:
            with self.subTest(line=line):
                self.assertFalse(is_swiftlint_violation_line(line))

    def test_whitespace_handling(self):
        """Test that pattern handles whitespace correctly"""
        line_with_spaces = "  /path/to/file.swift:25:1: warning: message (rule)  "
        self.assertTrue(is_swiftlint_violation_line(line_with_spaces))
        self.assertFalse(is_swiftlint_violation_line(line_with_spaces))


if __name__ == "__main__":
    unittest.main()
