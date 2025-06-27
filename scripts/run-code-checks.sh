#!/bin/bash
# Don't use set -e since we want to continue running all checks even if one fails
# But we do want pipefail to get the correct exit codes from piped commands
set -o pipefail

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
elif [ $ruff_check_exit -eq 127 ]; then
    echo "❌ Ruff command not found!"
    failures+=("ruff-check-missing")
    exit_code=1
else
    echo "❌ Ruff check failed (exit code: $ruff_check_exit)"
    failures+=("ruff-check")
    exit_code=1
fi

ruff format --check . 2>&1 | tee code_check_output/ruff/ruff-format.log
ruff_format_exit=$?
if [ $ruff_format_exit -eq 0 ]; then
    echo "✅ Ruff format check passed"
elif [ $ruff_format_exit -eq 127 ]; then
    echo "❌ Ruff format command not found!"
    failures+=("ruff-format-missing")
    exit_code=1
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
elif [ $mypy_exit -eq 127 ]; then
    echo "❌ mypy command not found!"
    failures+=("mypy-missing")
    exit_code=1
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
elif [ $bandit_exit -eq 127 ]; then
    echo "❌ Bandit command not found!"
    failures+=("bandit-missing")
    exit_code=1
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

# Create a combined lint output file for the GitHub Agent linter tool
echo "Creating combined lint output for linter tool..."
COMBINED_OUTPUT="code_check_output/lint-output.txt"

# Combine all linter outputs into a single file
{
    echo "=== RUFF CHECK OUTPUT ==="
    if [ -f "code_check_output/ruff/ruff-check.log" ]; then
        cat code_check_output/ruff/ruff-check.log
    fi
    echo ""
    
    echo "=== RUFF FORMAT OUTPUT ==="
    if [ -f "code_check_output/ruff/ruff-format.log" ]; then
        cat code_check_output/ruff/ruff-format.log
    fi
    echo ""
    
    echo "=== MYPY OUTPUT ==="
    if [ -f "code_check_output/mypy/mypy.log" ]; then
        cat code_check_output/mypy/mypy.log
    fi
    echo ""
    
    echo "=== BANDIT OUTPUT ==="
    if [ -f "code_check_output/bandit/bandit.log" ]; then
        cat code_check_output/bandit/bandit.log
    fi
} > "$COMBINED_OUTPUT"

echo "Combined lint output saved to $COMBINED_OUTPUT"
exit $exit_code
