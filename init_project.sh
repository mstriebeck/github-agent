#!/bin/bash

# PR Review Agent - Project Initialization Script
# Run this in each project/repository where you want to use the PR agent
# Usage: ./init_project.sh [/path/to/pr_review_server.py]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if we're in a Git repository
check_git_repo() {
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        log_error "Not in a Git repository. Please run this from your project root."
        exit 1
    fi
    
    log_success "Git repository detected"
}

# Get server path from argument or prompt
get_server_path() {
    if [ -n "$1" ]; then
        SERVER_PATH="$1"
    else
        read -p "Enter path to pr_review_server.py: " SERVER_PATH
    fi
    
    if [ ! -f "$SERVER_PATH" ]; then
        log_error "Server script not found at: $SERVER_PATH"
        exit 1
    fi
    
    # Convert to absolute path
    SERVER_PATH=$(realpath "$SERVER_PATH")
    log_success "Using server at: $SERVER_PATH"
}

# Test that the server script is valid
test_server_script() {
    log_info "Testing server script..."
    
    # Test the server script syntax and imports without actually running it
    if python3 -c "
import sys
import os
sys.path.insert(0, os.path.dirname('$SERVER_PATH'))

# Test that we can import the server module without running it
try:
    # Read the file and compile it to check syntax
    with open('$SERVER_PATH', 'r') as f:
        code = f.read()
    
    compile(code, '$SERVER_PATH', 'exec')
    
    # Test imports by importing the modules used in the server
    import mcp.server
    import mcp.types
    import mcp.server.stdio
    import github
    import git
    import requests
    
    print('Server script syntax and dependencies are valid')
except SyntaxError as e:
    print(f'Syntax error in server script: {e}')
    sys.exit(1)
except ImportError as e:
    print(f'Missing dependency: {e}')
    sys.exit(1)
except Exception as e:
    print(f'Error in server script: {e}')
    sys.exit(1)
" 2>/dev/null; then
        log_success "Server script is valid"
    else
        log_error "Server script has syntax errors or missing dependencies"
        exit 1
    fi
}

# Setup environment variables for this project
setup_env() {
    log_info "Setting up environment variables..."
    
    # Get repository info from Git
    REMOTE_URL=$(git config --get remote.origin.url 2>/dev/null || echo "")
    SUGGESTED_REPO=""
    
    if [[ $REMOTE_URL =~ github\.com[:/]([^/]+)/([^/.]+) ]]; then
        SUGGESTED_REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    fi
    
    # Create .env file
    if [ -f .env ]; then
        log_warning ".env file already exists"
        read -p "Overwrite? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Keeping existing .env file"
            return
        fi
    fi
    
    cat > .env << EOF
# GitHub Configuration for PR Agent
GITHUB_TOKEN=your_github_personal_access_token_here
GITHUB_REPO=${SUGGESTED_REPO:-owner/repo-name}

# Optional: CI/CD Integration
CI_API_KEY=your_ci_system_api_key_here

# Instructions:
# 1. Replace GITHUB_TOKEN with your personal access token
# 2. Create token at: https://github.com/settings/tokens
# 3. Required scopes: repo, pull_requests:write, statuses:read
# 4. Update GITHUB_REPO if the auto-detected value is wrong
EOF
    
    log_success "Created .env file"
    log_warning "Please edit .env and add your GitHub token"
}

# Setup MCP configuration
setup_mcp_config() {
    log_info "Setting up MCP server configuration..."
    
    CURRENT_DIR=$(pwd)
    
    # Create config directories
    mkdir -p ~/.config/claude-code ~/.config/amp
    
    # Claude Code configuration
    CLAUDE_CONFIG=~/.config/claude-code/settings.json
    if [ -f "$CLAUDE_CONFIG" ]; then
        # Update existing config
        log_info "Updating existing Claude Code configuration..."
        
        # Create backup
        cp "$CLAUDE_CONFIG" "$CLAUDE_CONFIG.backup.$(date +%s)"
        
        # Use jq to update, or create new if jq not available
        if command -v jq >/dev/null 2>&1; then
            jq --arg path "$SERVER_PATH" --arg cwd "$CURRENT_DIR" \
               '.mcpServers["pr-review"] = {
                  "command": "python3",
                  "args": [$path],
                  "cwd": $cwd,
                  "env": {
                    "GITHUB_TOKEN": "",
                    "GITHUB_REPO": ""
                  }
                }' "$CLAUDE_CONFIG" > "$CLAUDE_CONFIG.tmp" && mv "$CLAUDE_CONFIG.tmp" "$CLAUDE_CONFIG"
        else
            # Fallback: recreate the file (warning: this overwrites other servers)
            log_warning "jq not found, creating new config (this will overwrite existing MCP servers)"
            cat > "$CLAUDE_CONFIG" << EOF
{
  "mcpServers": {
    "pr-review": {
      "command": "python3",
      "args": ["$SERVER_PATH"],
      "cwd": "$CURRENT_DIR",
      "env": {
        "GITHUB_TOKEN": "",
        "GITHUB_REPO": ""
      }
    }
  }
}
EOF
        fi
    else
        # Create new config
        cat > "$CLAUDE_CONFIG" << EOF
{
  "mcpServers": {
    "pr-review": {
      "command": "python3",
      "args": ["$SERVER_PATH"],
      "cwd": "$CURRENT_DIR",
      "env": {
        "GITHUB_TOKEN": "",
        "GITHUB_REPO": ""
      }
    }
  }
}
EOF
    fi
    
    # SourceGraph Amp configuration
    AMP_CONFIG=~/.config/amp/settings.json
    if [ -f "$AMP_CONFIG" ]; then
        # Update existing config
        log_info "Updating existing SourceGraph Amp configuration..."
        
        # Create backup
        cp "$AMP_CONFIG" "$AMP_CONFIG.backup.$(date +%s)"
        
        # Use jq to update, or create new if jq not available
        if command -v jq >/dev/null 2>&1; then
            jq --arg path "$SERVER_PATH" --arg cwd "$CURRENT_DIR" \
               '.mcpServers["pr-review"] = {
                  "command": "python3",
                  "args": [$path],
                  "cwd": $cwd,
                  "env": {
                    "GITHUB_TOKEN": "",
                    "GITHUB_REPO": ""
                  }
                }' "$AMP_CONFIG" > "$AMP_CONFIG.tmp" && mv "$AMP_CONFIG.tmp" "$AMP_CONFIG"
        else
            # Fallback: recreate the file
            log_warning "jq not found, creating new config (this will overwrite existing MCP servers)"
            cat > "$AMP_CONFIG" << EOF
{
  "mcpServers": {
    "pr-review": {
      "command": "python3",
      "args": ["$SERVER_PATH"],
      "cwd": "$CURRENT_DIR",
      "env": {
        "GITHUB_TOKEN": "",
        "GITHUB_REPO": ""
      }
    }
  }
}
EOF
        fi
    else
        # Create new config
        cat > "$AMP_CONFIG" << EOF
{
  "mcpServers": {
    "pr-review": {
      "command": "python3",
      "args": ["$SERVER_PATH"],
      "cwd": "$CURRENT_DIR",
      "env": {
        "GITHUB_TOKEN": "",
        "GITHUB_REPO": ""
      }
    }
  }
}
EOF
    fi
    
    log_success "MCP configurations updated"
    log_warning "Remember to update environment variables in:"
    log_warning "  - $CLAUDE_CONFIG"
    log_warning "  - $AMP_CONFIG"
    log_warning "Or use the .env file in this directory"
}

# Create workflow documentation
create_workflow_docs() {
    log_info "Setting up workflow documentation..."
    
    # Get project language/type hints from directory structure
    PROJECT_TYPE="Generic"
    CI_SYSTEM="GitHub Actions"
    LINTING_TOOL="ESLint/SwiftLint/etc."
    TEST_FRAMEWORK="Jest/XCTest/etc."
    
    if [ -f "Package.swift" ] || find . -maxdepth 1 -name "*.xcodeproj" -o -name "*.xcworkspace" | grep -q .; then
        PROJECT_TYPE="Swift/iOS"
        LINTING_TOOL="SwiftLint"
        TEST_FRAMEWORK="XCTest"
    elif [ -f "package.json" ]; then
        PROJECT_TYPE="Node.js/JavaScript"
        LINTING_TOOL="ESLint"
        TEST_FRAMEWORK="Jest"
    elif [ -f "requirements.txt" ] || [ -f "pyproject.toml" ]; then
        PROJECT_TYPE="Python"
        LINTING_TOOL="flake8/black"
        TEST_FRAMEWORK="pytest"
    elif [ -f "Cargo.toml" ]; then
        PROJECT_TYPE="Rust"
        LINTING_TOOL="clippy"
        TEST_FRAMEWORK="cargo test"
    fi
    
    # Detect CI system
    if [ -d ".github/workflows" ]; then
        CI_SYSTEM="GitHub Actions"
    elif [ -f "Jenkinsfile" ]; then
        CI_SYSTEM="Jenkins"
    elif [ -f ".gitlab-ci.yml" ]; then
        CI_SYSTEM="GitLab CI"
    fi
    
    # Handle CLAUDE.md
    if [ -f "CLAUDE.md" ]; then
        log_warning "CLAUDE.md already exists - not modifying existing file"
        log_info "Please manually add the PR Review Agent tools to your CLAUDE.md:"
        cat > CLAUDE_PR_TOOLS.md << EOF
# PR Review Agent Tools (add to your existing CLAUDE.md)

## Available PR Review Tools

### Branch Context (Auto-detects current branch/PR)
- \`get_current_branch()\` - Get current Git branch and last commit info
- \`get_current_commit()\` - Get detailed current commit information
- \`find_pr_for_branch()\` - Find PR associated with current branch

### PR Management (Branch-aware)
- \`get_pr_comments()\` - Get all PR comments (uses current branch's PR)
- \`post_pr_reply(comment_id, message)\` - Reply to specific comment

### CI/CD (Commit-aware)
- \`get_build_status()\` - Check build status (uses current commit)
- \`read_swiftlint_logs()\` - Get linting violations (customize for your tools)

## PR Review Workflow Instructions

### ALWAYS Start with Context
1. Call \`get_current_branch()\` to understand current branch
2. Call \`find_pr_for_branch()\` to find associated PR
3. This ensures all actions target the correct branch/PR

### Common PR Commands
- "Address PR feedback" → Get context, get comments, fix issues, reply
- "Fix build issues" → Get context, check build status, read logs, fix
- "What's the status?" → Get context, check build, summarize

### Response Format for PR Work
Always:
- **Start with context**: "Working on branch \`feature/login\` with PR #123"
- **Explain actions**: "Checking build status for commit abc123..."
- **Summarize results**: "Found 3 linting violations and 2 test failures"
- **Provide next steps**: "I'll fix the violations first, then address the test failures"
EOF
        log_info "→ See CLAUDE_PR_TOOLS.md for content to add to your existing CLAUDE.md"
    else
        cat > CLAUDE.md << EOF
# PR Review Agent Instructions

## Project Context
This is a $PROJECT_TYPE project with the following characteristics:
- Main branch: \`main\`
- CI/CD: $CI_SYSTEM
- Code style: $LINTING_TOOL enforced
- Test framework: $TEST_FRAMEWORK

## Available Tools

### Branch Context (Auto-detects current branch/PR)
- \`get_current_branch()\` - Get current Git branch and last commit info
- \`get_current_commit()\` - Get detailed current commit information
- \`find_pr_for_branch()\` - Find PR associated with current branch

### PR Management (Branch-aware)
- \`get_pr_comments()\` - Get all PR comments (uses current branch's PR)
- \`post_pr_reply(comment_id, message)\` - Reply to specific comment

### CI/CD (Commit-aware)
- \`get_build_status()\` - Check build status (uses current commit)
- \`read_swiftlint_logs()\` - Get linting violations (customize for your tools)

## Workflow Instructions

### ALWAYS Start with Context
1. Call \`get_current_branch()\` to understand current branch
2. Call \`find_pr_for_branch()\` to find associated PR
3. This ensures all actions target the correct branch/PR

### Common Commands
- "Address PR feedback" → Get context, get comments, fix issues, reply
- "Fix build issues" → Get context, check build status, read logs, fix
- "What's the status?" → Get context, check build, summarize

## Response Format
Always:
- **Start with context**: "Working on branch \`feature/login\` with PR #123"
- **Explain actions**: "Checking build status for commit abc123..."
- **Summarize results**: "Found 3 linting violations and 2 test failures"
- **Provide next steps**: "I'll fix the violations first, then address the test failures"

## Project-Specific Notes
[Add any project-specific instructions here]
- Special build steps
- Custom CI tools  
- Code style requirements
- Testing procedures
EOF
        log_success "Created CLAUDE.md"
    fi
    
    # Handle AGENT.md
    if [ -f "AGENT.md" ]; then
        log_warning "AGENT.md already exists - not modifying existing file"
        log_info "Please manually add the PR Review Agent tools to your AGENT.md:"
        cat > AGENT_PR_TOOLS.md << EOF
# PR Review Agent Tools (add to your existing AGENT.md)

## PR Review MCP Tools Available

### Git Context (Auto-detecting)
- \`get_current_branch()\` - Current branch and commit info
- \`find_pr_for_branch()\` - Find PR for current branch

### PR Management
- \`get_pr_comments()\` - All PR comments (auto-detects current PR)
- \`post_pr_reply(comment_id, message)\` - Reply to comments

### Build & Quality
- \`get_build_status()\` - CI status (auto-detects current commit)
- \`read_swiftlint_logs()\` - Linting issues (customize for your tools)

## PR Review Workflow Patterns

### Always Establish Context First
Before any action, run:
\`\`\`
get_current_branch() → find_pr_for_branch()
\`\`\`

### Common PR Commands
- "Address PR feedback" → Get context, comments, address each one
- "Fix build failures" → Get context, check status, read logs, fix issues
- "Status check" → Get context, build status, pending comments, summarize

## PR Communication Style
- Start responses with current context: "On branch \`feature/auth\`, PR #45:"
- Be concise but thorough in PR responses
- Explain reasoning behind changes
EOF
        log_info "→ See AGENT_PR_TOOLS.md for content to add to your existing AGENT.md"
    else
        cat > AGENT.md << EOF
# PR Review Agent Configuration

## Project Setup
- Language: $PROJECT_TYPE
- Repository: $(git config --get remote.origin.url 2>/dev/null || "Not configured")
- Main branch: \`main\`
- CI/CD: $CI_SYSTEM

## Agent Tools Available

### Git Context (Auto-detecting)
- \`get_current_branch()\` - Current branch and commit info
- \`find_pr_for_branch()\` - Find PR for current branch

### PR Management
- \`get_pr_comments()\` - All PR comments (auto-detects current PR)
- \`post_pr_reply(comment_id, message)\` - Reply to comments

### Build & Quality
- \`get_build_status()\` - CI status (auto-detects current commit)
- \`read_swiftlint_logs()\` - Linting issues (customize for your tools)

## Workflow Patterns

### Always Establish Context First
Before any action, run:
\`\`\`
get_current_branch() → find_pr_for_branch()
\`\`\`

### Common Commands
- "Address PR feedback" → Get context, comments, address each one
- "Fix build failures" → Get context, check status, read logs, fix issues
- "Status check" → Get context, build status, pending comments, summarize

## Communication Style
- Start responses with current context: "On branch \`feature/auth\`, PR #45:"
- Be concise but thorough in PR responses
- Explain reasoning behind changes

## Project-Specific Configuration
[Customize these based on your project]
- Update linting tool integration in \`read_swiftlint_logs()\`
- Configure CI API access for your system
- Add any special build or test commands
EOF
        log_success "Created AGENT.md"
    fi
}

# Run project verification
run_verification() {
    log_info "Running project setup verification..."
    
    local errors=0
    
    # Check .env file
    if [ -f .env ]; then
        source .env 2>/dev/null || true
        if [ "$GITHUB_TOKEN" = "your_github_personal_access_token_here" ] || [ -z "$GITHUB_TOKEN" ]; then
            log_warning "GitHub token not configured in .env"
        else
            log_success ".env file configured"
        fi
    else
        log_warning ".env file not found"
    fi
    
    # Check MCP configurations
    if [ -f ~/.config/claude-code/settings.json ]; then
        log_success "Claude Code MCP configuration exists"
    else
        log_warning "Claude Code MCP configuration not found"
    fi
    
    if [ -f ~/.config/amp/settings.json ]; then
        log_success "SourceGraph Amp MCP configuration exists"
    else
        log_warning "SourceGraph Amp MCP configuration not found"
    fi
    
    # Check workflow docs
    if [ -f CLAUDE.md ]; then
        if [ -f CLAUDE_PR_TOOLS.md ]; then
            log_success "CLAUDE.md exists, PR tools reference created (CLAUDE_PR_TOOLS.md)"
        else
            log_success "CLAUDE.md already exists (not modified)"
        fi
    else
        log_success "CLAUDE.md workflow documentation created"
    fi
    
    if [ -f AGENT.md ]; then
        if [ -f AGENT_PR_TOOLS.md ]; then
            log_success "AGENT.md exists, PR tools reference created (AGENT_PR_TOOLS.md)"
        else
            log_success "AGENT.md already exists (not modified)"
        fi
    else
        log_success "AGENT.md workflow documentation created"
    fi
    
    # Test server accessibility
    if python3 -c "exec(open('$SERVER_PATH').read())" 2>/dev/null; then
        log_success "Server script is accessible and valid"
    else
        log_error "Cannot access or run server script"
        ((errors++))
    fi
    
    if [ $errors -eq 0 ]; then
        log_success "Project setup verification completed successfully!"
    else
        log_warning "Project setup completed with $errors errors. Please review the issues above."
    fi
}

# Usage info
show_usage() {
    echo "PR Review Agent - Project Initialization Script"
    echo
    echo "This script sets up a project to use the PR Review Agent."
    echo "Run this in each project/repository where you want to use the agent."
    echo
    echo "Usage: $0 [/path/to/pr_review_server.py]"
    echo
    echo "If no path is provided, you'll be prompted to enter it."
    echo
    echo "What this script does:"
    echo "  - Checks that you're in a Git repository"
    echo "  - Creates .env file with GitHub configuration"
    echo "  - Updates MCP server configurations for Claude Code and Amp"
    echo "  - Creates CLAUDE.md and AGENT.md workflow documentation"
    echo "  - Verifies the setup"
    echo
    echo "After running this script:"
    echo "  1. Edit .env file with your GitHub token"
    echo "  2. Optionally update MCP config files with environment variables"
    echo "  3. Customize CLAUDE.md and AGENT.md for your project"
    echo "  4. Test with: claude or amp"
    echo
}

# Main function
main() {
    if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
        show_usage
        exit 0
    fi
    
    log_info "Starting PR Review Agent project initialization..."
    echo
    
    check_git_repo
    get_server_path "$1"
    test_server_script
    setup_env
    setup_mcp_config
    create_workflow_docs
    
    echo
    log_success "Project initialization completed!"
    echo
    log_info "Next steps:"
    echo "1. Edit .env file with your GitHub token:"
    echo "   - Get token from: https://github.com/settings/tokens"
    echo "   - Required scopes: repo, pull_requests:write, statuses:read"
    echo "2. Test the setup:"
    echo "   - Run: claude (for Claude Code)"
    echo "   - Run: amp (for SourceGraph Amp)"
    echo "   - Try: 'What's my current branch?'"
    echo "3. Customize CLAUDE.md and AGENT.md for your project needs"
    echo
    
    run_verification
}

# Run main function
main "$@"
