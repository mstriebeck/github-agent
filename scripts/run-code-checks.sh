#!/bin/bash
set -e

# Combined code checks script
# Runs ruff, mypy, and bandit checks
# Continues running all checks even if one fails
# Returns non-zero exit code if any check fails

echo "Starting combined code checks..."

# Initialize tracking variables
exit_code=0
failures=()

# Create output directories
mkdir -p code_check_output/{ruff,mypy,bandit}

echo "========================================="
echo "Running Ruff linting..."
echo "========================================="
ruff check . --output-format=github 2>&1 | tee code_check_output/ruff/ruff-check.log
ruff_check_exit=$?
if [ $ruff_check_exit -eq 0 ]; then
    echo "✅ Ruff check passed"
else
    echo "❌ Ruff check failed (exit code: $ruff_check_exit)"
    failures+=("ruff-check")
    exit_code=1
fi

ruff format --check . 2>&1 | tee code_check_output/ruff/ruff-format.log
ruff_format_exit=$?
if [ $ruff_format_exit -eq 0 ]; then
    echo "✅ Ruff format check passed"
else
    echo "❌ Ruff format check failed (exit code: $ruff_format_exit)"
    failures+=("ruff-format")
    exit_code=1
fi

# Also run with JSON output for artifact
ruff check . --output-format=json > code_check_output/ruff/ruff-check.json 2>/dev/null || true

echo "========================================="
echo "Running mypy type checking..."
echo "========================================="
mypy . --ignore-missing-imports --show-error-codes 2>&1 | tee code_check_output/mypy/mypy-results.log
mypy_exit=$?
if [ $mypy_exit -eq 0 ]; then
    echo "✅ mypy type checking passed"
else
    echo "❌ mypy type checking failed (exit code: $mypy_exit)"
    failures+=("mypy")
    exit_code=1
fi

echo "========================================="
echo "Running bandit security check..."
echo "========================================="
bandit -r . -f json -o code_check_output/bandit/bandit-results.json 2>&1 | tee code_check_output/bandit/bandit.log
bandit_exit=$?
if [ $bandit_exit -eq 0 ]; then
    echo "✅ Bandit security check passed"
else
    echo "❌ Bandit security check failed (exit code: $bandit_exit)"
    failures+=("bandit")
    exit_code=1
fi

# Also generate text format for bandit
bandit -r . -f txt 2>&1 | tee code_check_output/bandit/bandit-results.txt || true

echo "========================================="
echo "Code checks summary:"
echo "========================================="

if [ $exit_code -eq 0 ]; then
    echo "🎉 All code checks passed!"
else
    echo "💥 Some code checks failed:"
    for failure in "${failures[@]}"; do
        echo "  - $failure"
    done
fi

echo "Check results saved to code_check_output/"
exit $exit_code
