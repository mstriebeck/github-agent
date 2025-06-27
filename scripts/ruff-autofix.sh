#!/bin/bash
set -o pipefail

# Ruff auto-fix script
# Runs ruff --fix and format, detects if changes were made
echo "🔧 Running Ruff auto-fix..."

# Create output directory
mkdir -p ruff_autofix_output

# Check if there are any changes before we start
echo "Checking initial git status..."
git status --porcelain > ruff_autofix_output/git-status-before.txt

# Run ruff fixes
echo "========================================="
echo "Running ruff check --fix..."
echo "========================================="
ruff check --fix . 2>&1 | tee ruff_autofix_output/ruff-fix.log
ruff_fix_exit=$?

echo "========================================="
echo "Running ruff format..."
echo "========================================="
ruff format . 2>&1 | tee ruff_autofix_output/ruff-format.log
ruff_format_exit=$?

# Check what changed
echo "Checking git status after fixes..."
git status --porcelain > ruff_autofix_output/git-status-after.txt

# Compare before and after
if ! diff -q ruff_autofix_output/git-status-before.txt ruff_autofix_output/git-status-after.txt > /dev/null; then
    echo "📝 Ruff made changes to files!"
    echo "Changes detected:"
    git diff --name-only | tee ruff_autofix_output/changed-files.txt
    
    # Show the actual changes
    echo "========================================="
    echo "Git diff summary:"
    echo "========================================="
    git diff --stat | tee ruff_autofix_output/diff-stat.txt
    
    # Set output for GitHub Actions
    if [ -n "$GITHUB_OUTPUT" ]; then
        echo "changes_made=true" >> $GITHUB_OUTPUT
        echo "commit_needed=true" >> $GITHUB_OUTPUT
    fi
    
    exit 0  # Success - changes were made
else
    echo "✅ No changes made by ruff"
    if [ -n "$GITHUB_OUTPUT" ]; then
        echo "changes_made=false" >> $GITHUB_OUTPUT
        echo "commit_needed=false" >> $GITHUB_OUTPUT
    fi
    
    # If ruff had errors but didn't change files, we should still report that
    if [ $ruff_fix_exit -ne 0 ] || [ $ruff_format_exit -ne 0 ]; then
        echo "⚠️  Ruff reported issues but couldn't auto-fix them"
        exit 1
    fi
    
    exit 0  # Success - no changes needed
fi
