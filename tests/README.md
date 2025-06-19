# Tests for github_mcp_server.py

This directory contains unit tests for the parsing functions in `github_mcp_server.py`.

## What's Tested

The tests focus on pure functions that don't require external dependencies:

### SwiftLint Violation Parsing (`test_log_parsing.py`)
- `extract_file_from_violation()` - Extracts file paths from SwiftLint output
- `extract_line_number_from_violation()` - Extracts line numbers from SwiftLint output  
- `extract_severity_from_violation()` - Extracts error/warning severity
- `extract_message_from_violation()` - Extracts violation messages
- `extract_rule_from_violation()` - Extracts SwiftLint rule names

### Build Output Parsing (`test_log_parsing.py`)
- Regex patterns for compiler errors, warnings, and test failures
- Pattern validation to ensure they match only the correct line types

### Utility Functions (`test_utilities.py`)
- `parse_github_remote_url()` - Parses GitHub SSH and HTTPS remote URLs
- `find_matching_workflow_run()` - Workflow run matching with fallback strategy
- `find_file_with_alternatives()` - File finding with alternative names
- `is_swiftlint_violation_line()` - SwiftLint violation pattern matching

## Running Tests

```bash
# Run all tests
python tests/run_tests.py

# Run specific test file
python -m unittest tests.test_log_parsing

# Run with verbose output
python tests/run_tests.py -v
```

## Test Data

The tests use realistic sample data based on actual SwiftLint and Xcode build output patterns:

- SwiftLint violations with various file paths, line numbers, severities, messages and rules
- Compiler errors and warnings from Swift builds
- XCTest failure messages
- Edge cases with malformed or partially valid input

## Adding More Tests

If you have actual log output from your builds, you can easily add more test cases:

1. Add sample lines to the `setUp()` methods in `test_log_parsing.py`
2. Add corresponding expected results
3. The test framework will automatically validate all combinations

The parsing functions are designed to be robust and handle edge cases gracefully.
