#!/usr/bin/env python3

"""
Test for parse_build_output function
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from github_tools import parse_build_output

# Add the current directory to Python path to import github_tools
sys.path.insert(0, str(Path(__file__).parent))

# Sample Python test output (realistic pytest output with failures and warnings)
PYTHON_TEST_OUTPUT = """
================ test session starts ================
platform darwin -- Python 3.12.0, pytest-8.0.0, pluggy-1.3.0
rootdir: /workspace
plugins: cov-4.0.0
collected 15 items

tests/test_health_monitor.py::test_is_server_healthy_true PASSED    [ 13%]
tests/test_health_monitor.py::test_is_server_healthy_false_old FAILED [20%]
tests/test_health_monitor.py::test_is_server_healthy_missing_file PASSED [33%]

  /usr/lib/python3.12/unittest/case.py:690: DeprecationWarning: It is deprecated to return a value that is not None from a test case (<bound method TestGetLinterErrors.test_no_repo_manager of <tests.test_get_linter_errors.TestGetLinterErrors testMethod=test_no_repo_manager>>)
    return self.run(*args, **kwds)

================================ FAILURES =================================
______________________ test_is_server_healthy_false_old ______________________

self = <tests.test_health_monitor.TestHealthStatusFunctions object at 0x103db8290>, tmp_path = PosixPath('/private/var/folders/w8/ytp3dwy5049d8sl146pgb9340000gn/T/pytest-of-mstriebeck/pytest-45/test_is_server_healthy_false_o0')

    def test_is_server_healthy_false_old(self, tmp_path):
        \"\"\"Test server healthy check returning false for old timestamp.\"\"\"
        health_file = tmp_path / "health.json"
        old_time = datetime.now() - timedelta(seconds=20)
        test_data = {"server_status": "running", "timestamp": old_time.isoformat()}

        with open(health_file, "w") as f:
            json.dump(test_data, f)

>       result = is_server_healthy(str(health_file), max_age_seconds=10)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       TypeError: is_server_healthy() got an unexpected keyword argument 'max_age_seconds'. Did you mean 'max_age_seconds___'?

tests/test_health_monitor.py:518: TypeError

______________________ test_assertion_failure ______________________

self = <tests.test_health_monitor.TestHealthStatusFunctions object at 0x103d2b820>, tmp_path = PosixPath('/private/var/folders/w8/ytp3dwy5049d8sl146pgb9340000gn/T/pytest-of-mstriebeck/pytest-45/test_is_server_healthy_true0')

    def test_is_server_healthy_true(self, tmp_path):
        \"\"\"Test server healthy check returning true.\"\"\"
        health_file = tmp_path / "health.json"
        test_data = {
            "server_status": "running",
            "timestamp": datetime.now().isoformat(),
        }

        with open(health_file, "w") as f:
            json.dump(test_data, f)

        result = is_server_healthy(str(health_file))

>       assert result is True
E       assert False is True

tests/test_health_monitor.py:507: AssertionError

================ short test summary info ================
FAILED tests/test_health_monitor.py::test_is_server_healthy_false_old - TypeError: is_server_healthy() got an unexpected keyword argument 'max_age_seconds'
FAILED tests/test_health_monitor.py::test_assertion_failure - AssertionError: assert False is True
================ 2 failed, 13 passed in 2.45s ================
"""

# Sample Swift build output
SWIFT_BUILD_OUTPUT = """
Building for production...
/Users/developer/project/Sources/App/Controllers/UserController.swift:45:12: error: Use of undeclared identifier 'invalidFunction'
/Users/developer/project/Sources/App/Models/User.swift:23:8: warning: Variable 'unusedVar' was never used
/Users/developer/project/Tests/AppTests/UserTests.swift:67: error: XCTAssertEqual failed: ("expected", "actual") : Values do not match

Build FAILED.
"""


async def test_parse_build_output_python():
    """Test parsing Python build output"""
    print("Testing Python build output parsing...")

    with tempfile.TemporaryDirectory() as temp_dir:
        # Write Python test output to file
        output_file = os.path.join(temp_dir, "python_test_output.txt")
        with open(output_file, "w") as f:
            f.write(PYTHON_TEST_OUTPUT)

        # Test with language="python" and expected_filename=None (should auto-detect)
        issues = await parse_build_output(temp_dir, language="python")

        print(f"Found {len(issues)} issues")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. Type: {issue['type']}, Severity: {issue['severity']}")
            if "file" in issue:
                print(f"      File: {issue['file']}")
            if "error_type" in issue:
                print(f"      Error: {issue['error_type']} - {issue['message']}")
            if "warning_type" in issue:
                print(f"      Warning: {issue['warning_type']} - {issue['message']}")
            if "assertion" in issue:
                print(f"      Assertion: {issue['assertion']}")
                print(f"      Error: {issue['error']}")

        # Verify we found the expected types of issues
        issue_types = [issue["type"] for issue in issues]
        assert "python_warning" in issue_types, "Should find Python warnings"
        assert (
            "python_runtime_error" in issue_types
        ), "Should find Python runtime errors"
        assert "python_test_failure" in issue_types, "Should find Python test failures"

        print("✓ Python build output parsing test passed!")


async def test_parse_build_output_swift():
    """Test parsing Swift build output"""
    print("Testing Swift build output parsing...")

    with tempfile.TemporaryDirectory() as temp_dir:
        # Write Swift build output to file
        output_file = os.path.join(temp_dir, "build_and_test_all.txt")
        with open(output_file, "w") as f:
            f.write(SWIFT_BUILD_OUTPUT)

        # Test with language="swift" and expected_filename=None (should auto-detect)
        issues = await parse_build_output(temp_dir, language="swift")

        print(f"Found {len(issues)} issues")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. Type: {issue['type']}, Severity: {issue['severity']}")
            if "file" in issue:
                print(f"      File: {issue['file']}, Line: {issue['line_number']}")
            if "message" in issue:
                print(f"      Message: {issue['message']}")

        # Verify we found the expected types of issues
        issue_types = [issue["type"] for issue in issues]
        assert "compiler_error" in issue_types, "Should find Swift compiler errors"
        assert "compiler_warning" in issue_types, "Should find Swift compiler warnings"
        assert "test_failure" in issue_types, "Should find Swift test failures"

        print("✓ Swift build output parsing test passed!")


async def test_filename_detection():
    """Test that the function correctly detects filenames based on language"""
    print("Testing filename detection...")

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create Python test output file
        python_file = os.path.join(temp_dir, "python_test_output.txt")
        with open(python_file, "w") as f:
            f.write("# Python test output\nTest completed successfully")

        # Test Python language detection
        _ = await parse_build_output(temp_dir, language="python")
        print("✓ Successfully found python_test_output.txt for language='python'")

        # Create Swift test output file
        swift_file = os.path.join(temp_dir, "build_and_test_all.txt")
        with open(swift_file, "w") as f:
            f.write("// Swift build output\nBuild completed successfully")

        # Test Swift language detection
        _ = await parse_build_output(temp_dir, language="swift")
        print("✓ Successfully found build_and_test_all.txt for language='swift'")


async def test_fallback_alternatives():
    """Test that the function tries alternative filenames"""
    print("Testing fallback alternatives...")

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create alternative Python output file
        alt_file = os.path.join(temp_dir, "output.txt")
        with open(alt_file, "w") as f:
            f.write("Alternative output file")

        # Should find output.txt as fallback for Python
        _ = await parse_build_output(temp_dir, language="python")
        print("✓ Successfully found alternative file 'output.txt' for Python")


async def main():
    """Run all tests"""
    print("=" * 60)
    print("TESTING parse_build_output FUNCTION")
    print("=" * 60)

    try:
        await test_filename_detection()
        print()
        await test_fallback_alternatives()
        print()
        await test_parse_build_output_python()
        print()
        await test_parse_build_output_swift()
        print()
        print("=" * 60)
        print("ALL TESTS PASSED! ✓")
        print("=" * 60)
    except Exception as e:
        print(f"❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
