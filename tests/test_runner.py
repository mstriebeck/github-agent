"""
Test runner script for comprehensive shutdown system testing.

This script runs all tests in different configurations and provides
detailed reporting of test results, coverage, and performance.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class SystemTestRunner:
    """Comprehensive test runner for shutdown system."""

    def __init__(self, test_dir: Path):
        self.test_dir = test_dir
        self.results: dict[str, dict] = {}

    def run_unit_tests(self, verbose: bool = False) -> dict[str, dict]:
        """Run unit tests for individual components."""
        print("🧪 Running Unit Tests...")

        unit_test_files = [
            "test_exit_codes.py",
            "test_health_monitor.py",
            "test_shutdown_manager.py",
        ]

        results: dict[str, dict] = {}
        for test_file in unit_test_files:
            test_path = self.test_dir / test_file
            if test_path.exists():
                print(f"  Running {test_file}...")
                result = self._run_pytest(test_path, verbose)
                results[test_file] = result
            else:
                print(f"  ⚠️  {test_file} not found")
                results[test_file] = {"status": "not_found"}

        return results

    def run_integration_tests(self, verbose: bool = False) -> dict[str, dict]:
        """Run integration tests with mock processes."""
        print("🔗 Running Integration Tests...")

        integration_files = ["test_shutdown_integration.py"]

        results: dict[str, dict] = {}
        for test_file in integration_files:
            test_path = self.test_dir / test_file
            if test_path.exists():
                print(f"  Running {test_file}...")
                result = self._run_pytest(test_path, verbose, timeout=60)
                results[test_file] = result
            else:
                print(f"  ⚠️  {test_file} not found")
                results[test_file] = {"status": "not_found"}

        return results

    def run_edge_case_tests(self, verbose: bool = False) -> dict[str, dict]:
        """Run edge case and stress tests."""
        print("⚡ Running Edge Case Tests...")

        edge_case_files = ["test_edge_cases.py"]

        results: dict[str, dict] = {}
        for test_file in edge_case_files:
            test_path = self.test_dir / test_file
            if test_path.exists():
                print(f"  Running {test_file}...")
                result = self._run_pytest(test_path, verbose, timeout=120)
                results[test_file] = result
            else:
                print(f"  ⚠️  {test_file} not found")
                results[test_file] = {"status": "not_found"}

        return results

    def run_abstract_tests(self, verbose: bool = False) -> dict[str, dict]:
        """Run tests for abstract base classes."""
        print("🎭 Running Abstract Base Class Tests...")

        # The abstract classes are tested indirectly through integration tests
        # But we can run a quick validation
        test_path = self.test_dir / "test_abstracts.py"

        if test_path.exists():
            print("  Running abstract class validation...")
            result = self._run_pytest(test_path, verbose, test_pattern="test_*")
            return {"test_abstracts.py": result}
        else:
            print("  ⚠️  test_abstracts.py not found")
            return {"test_abstracts.py": {"status": "not_found"}}

    def run_performance_tests(self, verbose: bool = False) -> dict[str, dict]:
        """Run performance and timing tests."""
        print("🏎️  Running Performance Tests...")

        # Run specific performance-focused tests
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(self.test_dir),
            "-m",
            "slow",  # Run tests marked as slow
            "--tb=short",
            "--durations=10",  # Show 10 slowest tests
        ]

        if verbose:
            cmd.append("-v")

        return {"performance": self._run_command(cmd, timeout=180)}

    def run_coverage_analysis(self) -> dict[str, dict]:
        """Run tests with coverage analysis."""
        print("📊 Running Coverage Analysis...")

        try:
            # Install coverage if not available
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "coverage"],
                capture_output=True,
                check=False,
            )

            # Run tests with coverage
            cmd = [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--source=../",  # Cover parent directory
                "--omit=*/tests/*,*/test_*",  # Exclude test files
                "-m",
                "pytest",
                str(self.test_dir),
                "--tb=short",
            ]

            result = self._run_command(cmd, timeout=300)

            if result["returncode"] == 0:
                # Generate coverage report
                report_cmd = [
                    sys.executable,
                    "-m",
                    "coverage",
                    "report",
                    "--show-missing",
                ]
                report_result = self._run_command(report_cmd, timeout=60)
                result["coverage_report"] = report_result["stdout"]

                # Generate HTML report
                html_cmd = [sys.executable, "-m", "coverage", "html", "-d", "htmlcov"]
                self._run_command(html_cmd, timeout=60)
                print("  📄 HTML coverage report generated in htmlcov/")

            return {"coverage": result}

        except Exception as e:
            return {"coverage": {"status": "error", "error": str(e)}}

    def run_all_tests(
        self,
        verbose: bool = False,
        include_performance: bool = False,
        include_coverage: bool = False,
    ) -> dict:
        """Run all test suites."""
        print("🚀 Running Comprehensive Test Suite...")
        print("=" * 60)

        start_time = time.time()
        all_results: dict[str, dict[str, Any]] = {}

        # Run test suites in order
        all_results["unit"] = self.run_unit_tests(verbose)
        all_results["integration"] = self.run_integration_tests(verbose)
        all_results["edge_cases"] = self.run_edge_case_tests(verbose)
        all_results["abstracts"] = self.run_abstract_tests(verbose)

        if include_performance:
            all_results["performance"] = self.run_performance_tests(verbose)

        if include_coverage:
            all_results["coverage"] = self.run_coverage_analysis()

        total_time = time.time() - start_time
        all_results["total_time"] = {"execution_time": total_time}

        return all_results

    def _run_pytest(
        self,
        test_path: Path,
        verbose: bool = False,
        timeout: int = 60,
        test_pattern: str | None = None,
    ) -> dict:
        """Run pytest on a specific file."""
        cmd = [sys.executable, "-m", "pytest", str(test_path), "--tb=short"]

        if verbose:
            cmd.append("-v")

        if test_pattern:
            cmd.extend(["-k", test_pattern])

        return self._run_command(cmd, timeout)

    def _run_command(self, cmd: list[str], timeout: int) -> dict:
        """Run a command and capture results."""
        try:
            start_time = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.test_dir.parent,  # Run from project root
            )
            duration = time.time() - start_time

            return {
                "status": "completed",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": duration,
                "success": result.returncode == 0,
            }

        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "returncode": -1,
                "error": f"Command timed out after {timeout}s",
                "success": False,
            }
        except Exception as e:
            return {
                "status": "error",
                "returncode": -1,
                "error": str(e),
                "success": False,
            }

    def print_summary(self, results: dict):
        """Print a summary of test results."""
        print("\n" + "=" * 60)
        print("📋 TEST SUMMARY")
        print("=" * 60)

        total_tests = 0
        total_passed = 0
        total_failed = 0
        total_errors = 0

        for suite_name, suite_results in results.items():
            if suite_name == "total_time":
                continue

            print(f"\n{suite_name.upper()}:")

            if isinstance(suite_results, dict) and "status" in suite_results:
                # Single test result
                self._print_test_result("  ", suite_name, suite_results)
                if suite_results.get("success"):
                    total_passed += 1
                else:
                    total_failed += 1
            else:
                # Multiple test results
                for test_name, test_result in suite_results.items():
                    self._print_test_result("  ", test_name, test_result)
                    if test_result.get("success"):
                        total_passed += 1
                    elif test_result.get("status") == "not_found":
                        total_errors += 1
                    else:
                        total_failed += 1

        total_tests = total_passed + total_failed + total_errors

        print(f"\n{'=' * 60}")
        print(f"TOTAL: {total_tests} tests")
        print(f"✅ PASSED: {total_passed}")
        print(f"❌ FAILED: {total_failed}")
        print(f"⚠️  ERRORS: {total_errors}")

        if "total_time" in results:
            print(f"⏱️  TOTAL TIME: {results['total_time']:.2f}s")

        success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        print(f"📊 SUCCESS RATE: {success_rate:.1f}%")

        # Overall status
        if total_failed == 0 and total_errors == 0:
            print("🎉 ALL TESTS PASSED!")
        elif total_failed > 0:
            print("💥 SOME TESTS FAILED")
        else:
            print("⚠️  SOME TESTS HAD ERRORS")

    def _print_test_result(self, indent: str, test_name: str, result: dict):
        """Print a single test result."""
        status = result.get("status", "unknown")
        success = result.get("success", False)
        duration = result.get("duration", 0)

        if success:
            icon = "✅"
        elif status == "not_found":
            icon = "⚠️"
        elif status == "timeout":
            icon = "⏰"
        else:
            icon = "❌"

        print(f"{indent}{icon} {test_name:<30} ({duration:.2f}s)")

        # Show error details for failures
        if not success and status != "not_found":
            error = result.get("error", "")
            stderr = result.get("stderr", "")
            if error:
                print(f"{indent}    Error: {error}")
            elif stderr:
                # Show last few lines of stderr
                stderr_lines = stderr.strip().split("\n")
                for line in stderr_lines[-3:]:
                    if line.strip():
                        print(f"{indent}    {line}")


def main():
    """Main test runner entry point."""
    parser = argparse.ArgumentParser(description="Run shutdown system tests")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--unit", action="store_true", help="Run only unit tests")
    parser.add_argument(
        "--integration", action="store_true", help="Run only integration tests"
    )
    parser.add_argument(
        "--edge-cases", action="store_true", help="Run only edge case tests"
    )
    parser.add_argument(
        "--performance", action="store_true", help="Include performance tests"
    )
    parser.add_argument(
        "--coverage", action="store_true", help="Include coverage analysis"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests including performance and coverage",
    )

    args = parser.parse_args()

    # Find test directory
    test_dir = Path(__file__).parent
    runner = SystemTestRunner(test_dir)

    if args.all:
        results = runner.run_all_tests(
            verbose=args.verbose, include_performance=True, include_coverage=True
        )
    elif args.unit:
        results = {"unit": runner.run_unit_tests(args.verbose)}
    elif args.integration:
        results = {"integration": runner.run_integration_tests(args.verbose)}
    elif args.edge_cases:
        results = {"edge_cases": runner.run_edge_case_tests(args.verbose)}
    else:
        # Default: run core tests
        results = runner.run_all_tests(
            verbose=args.verbose,
            include_performance=args.performance,
            include_coverage=args.coverage,
        )

    runner.print_summary(results)

    # Exit with non-zero code if tests failed
    failed_tests = sum(
        1
        for suite in results.values()
        if isinstance(suite, dict) and not suite.get("success", True)
    )

    if failed_tests > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
