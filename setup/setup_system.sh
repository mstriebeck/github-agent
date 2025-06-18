#!/bin/bash

# PR Review Agent - System Setup Script
# Sets up the development environment with required tools and libraries
# Run this once per development machine from the agent repository

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check Python version
check_python_version() {
    log_info "Checking Python version..."
    
    if command_exists python3; then
        PYTHON_CMD="python3"
    elif command_exists python; then
        PYTHON_CMD="python"
    else
        log_error "Python not found. Please install Python 3.8+ first."
        exit 1
    fi
    
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
        log_error "Python 3.8+ required. Found: $PYTHON_VERSION"
        log_info "Please install Python 3.8+ using:"
        log_info "  - pyenv: pyenv install 3.11.0 && pyenv global 3.11.0"
        log_info "  - conda: conda install python=3.11"
        log_info "  - system package manager"
        exit 1
    fi
    
    log_success "Python version $PYTHON_VERSION is compatible"
    export PYTHON_CMD
}

# Install Python dependencies
install_python_deps() {
    log_info "Installing Python dependencies..."
    
    # Required packages for PR agent
    PACKAGES=(
        "mcp"
        "pygithub"
        "gitpython"
        "requests"
        "pydantic"
        "python-dotenv"
    )
    
    log_info "Installing required packages: ${PACKAGES[*]}"
    
    # Check if we're in a virtual environment
    if [ -n "$VIRTUAL_ENV" ]; then
        log_success "Virtual environment detected: $VIRTUAL_ENV"
        
        # Use the virtual environment's pip
        VENV_PIP="$VIRTUAL_ENV/bin/pip"
        VENV_PYTHON="$VIRTUAL_ENV/bin/python"
        
        if [ -f "$VENV_PIP" ]; then
            PIP_CMD="$VENV_PIP"
            PYTHON_CMD="$VENV_PYTHON"
            log_info "Using virtual environment pip: $PIP_CMD"
        else
            log_error "Virtual environment detected but pip not found at $VENV_PIP"
            exit 1
        fi
        
        INSTALL_METHOD="venv"
    else
        # Check if pip exists
        if ! command_exists pip && ! command_exists pip3; then
            log_error "pip not found. Please install pip first."
            exit 1
        fi
        
        PIP_CMD="pip"
        if command_exists pip3; then
            PIP_CMD="pip3"
        fi
        
        # Check if system has externally-managed-environment restriction
        if $PIP_CMD install --help 2>/dev/null | grep -q "break-system-packages"; then
            log_warning "System has externally-managed Python environment"
            log_info "Choose installation method:"
            echo "1. Use --user flag (install to user directory)"
            echo "2. Use --break-system-packages (not recommended)"
            echo "3. Create and use virtual environment"
            echo "4. Use pipx (if available)"
            read -p "Enter choice (1-4): " choice
            
            case $choice in
                1) INSTALL_METHOD="user" ;;
                2) INSTALL_METHOD="break-system" ;;
                3) INSTALL_METHOD="create-venv" ;;
                4) INSTALL_METHOD="pipx" ;;
                *) 
                    log_warning "Invalid choice, defaulting to user installation"
                    INSTALL_METHOD="user"
                    ;;
            esac
        else
            INSTALL_METHOD="global"
        fi
    fi
    
    case $INSTALL_METHOD in
        "venv")
            # Already in virtual environment, proceed normally
            for package in "${PACKAGES[@]}"; do
                if $PYTHON_CMD -c "import ${package//-/_}" 2>/dev/null; then
                    log_success "$package already installed"
                else
                    log_info "Installing $package..."
                    $PIP_CMD install "$package"
                    log_success "$package installed"
                fi
            done
            ;;
            
        "user")
            # Install to user directory
            for package in "${PACKAGES[@]}"; do
                if $PYTHON_CMD -c "import ${package//-/_}" 2>/dev/null; then
                    log_success "$package already installed"
                else
                    log_info "Installing $package to user directory..."
                    $PIP_CMD install --user "$package"
                    log_success "$package installed"
                fi
            done
            log_warning "Packages installed to user directory. Make sure ~/.local/bin is in your PATH"
            ;;
            
        "break-system")
            # Use break-system-packages flag (not recommended)
            log_warning "Using --break-system-packages flag (not recommended)"
            for package in "${PACKAGES[@]}"; do
                if $PYTHON_CMD -c "import ${package//-/_}" 2>/dev/null; then
                    log_success "$package already installed"
                else
                    log_info "Installing $package..."
                    $PIP_CMD install --break-system-packages "$package"
                    log_success "$package installed"
                fi
            done
            ;;
            
        "create-venv")
            # Create and setup virtual environment
            log_info "Creating virtual environment..."
            VENV_PATH="$HOME/.pr-agent-venv"
            
            if [ ! -d "$VENV_PATH" ]; then
                $PYTHON_CMD -m venv "$VENV_PATH"
                log_success "Virtual environment created at $VENV_PATH"
            else
                log_success "Virtual environment already exists at $VENV_PATH"
            fi
            
            # Activate virtual environment and install packages
            source "$VENV_PATH/bin/activate"
            PYTHON_CMD="$VENV_PATH/bin/python"
            PIP_CMD="$VENV_PATH/bin/pip"
            
            for package in "${PACKAGES[@]}"; do
                if $PYTHON_CMD -c "import ${package//-/_}" 2>/dev/null; then
                    log_success "$package already installed"
                else
                    log_info "Installing $package in virtual environment..."
                    $PIP_CMD install "$package"
                    log_success "$package installed"
                fi
            done
            
            log_success "Packages installed in virtual environment"
            log_warning "Remember to activate the virtual environment before using the agent:"
            log_warning "  source $VENV_PATH/bin/activate"
            
            # Update the global PYTHON_CMD for the rest of the script
            export PYTHON_CMD="$VENV_PATH/bin/python"
            export VENV_PYTHON_PATH="$VENV_PATH/bin/python"
            ;;
            
        "pipx")
            if ! command_exists pipx; then
                log_error "pipx not found. Install with: brew install pipx"
                log_info "Falling back to user installation..."
                INSTALL_METHOD="user"
                install_python_deps  # Recursive call with user method
                return
            fi
            
            log_info "Using pipx for application installation..."
            # Note: pipx is mainly for applications, not libraries
            # We'll still need pip for some packages
            log_warning "pipx is best for applications. Installing core packages with pip --user"
            
            for package in "${PACKAGES[@]}"; do
                if $PYTHON_CMD -c "import ${package//-/_}" 2>/dev/null; then
                    log_success "$package already installed"
                else
                    log_info "Installing $package with pip --user..."
                    $PIP_CMD install --user "$package"
                    log_success "$package installed"
                fi
            done
            ;;
            
        "global")
            # Traditional global installation
            for package in "${PACKAGES[@]}"; do
                if $PYTHON_CMD -c "import ${package//-/_}" 2>/dev/null; then
                    log_success "$package already installed"
                else
                    log_info "Installing $package..."
                    $PIP_CMD install "$package"
                    log_success "$package installed"
                fi
            done
            ;;
    esac
}

# Check Node.js and npm (for agents)
check_nodejs() {
    log_info "Checking Node.js for agent installation..."
    
    if ! command_exists node; then
        log_error "Node.js not found. Required for Claude Code/SourceGraph Amp."
        log_info "Please install Node.js from https://nodejs.org/ or using:"
        log_info "  - nvm: nvm install --lts"
        log_info "  - package manager: brew install node, apt install nodejs npm, etc."
        exit 1
    fi
    
    if ! command_exists npm; then
        log_error "npm not found. Please install npm."
        exit 1
    fi
    
    NODE_VERSION=$(node --version)
    log_success "Node.js $NODE_VERSION is available"
}

# Install agents globally
install_agents() {
    check_nodejs
    
    log_info "Installing coding agents globally..."
    
    # Install Claude Code
    if command_exists claude; then
        CLAUDE_VERSION=$(claude --version 2>/dev/null || echo "unknown")
        log_success "Claude Code already installed (version: $CLAUDE_VERSION)"
    else
        log_info "Installing Claude Code..."
        npm install -g @anthropic-ai/claude-code
        log_success "Claude Code installed"
    fi
    
    # Install SourceGraph Amp
    if command_exists amp; then
        AMP_VERSION=$(amp --version 2>/dev/null || echo "unknown")
        log_success "SourceGraph Amp already installed (version: $AMP_VERSION)"
    else
        log_info "Installing SourceGraph Amp..."
        npm install -g @sourcegraph/amp
        log_success "SourceGraph Amp installed"
    fi
}

# Check basic Git installation
check_git() {
    log_info "Checking Git installation..."
    
    if ! command_exists git; then
        log_error "Git not found. Please install Git first."
        exit 1
    fi
    
    GIT_VERSION=$(git --version)
    log_success "$GIT_VERSION is available"
}

# Verify required files exist
check_required_files() {
    log_info "Checking required files..."
    
    REQUIRED_FILES=(
        "pr_agent_server.py"
    )
    
    for file in "${REQUIRED_FILES[@]}"; do
        if [ ! -f "$SCRIPT_DIR/$file" ]; then
            log_error "Required file not found: $file"
            log_error "Please ensure you have all agent files in the same directory as this script"
            exit 1
        fi
        log_success "Found $file"
    done
}

# Run verification tests
run_verification() {
    log_info "Running system verification..."
    
    local errors=0
    
    # Test Python and libraries
    log_info "Testing Python libraries..."
    if $PYTHON_CMD -c "import mcp, github, git, requests, pydantic; print('All libraries available')" 2>/dev/null; then
        log_success "Python libraries verified"
    else
        log_error "Python libraries test failed"
        ((errors++))
    fi
    
    # Test agents
    if command_exists claude; then
        log_success "Claude Code available"
    else
        log_warning "Claude Code not installed"
    fi
    
    if command_exists amp; then
        log_success "SourceGraph Amp available"
    else
        log_warning "SourceGraph Amp not installed"
    fi
    
    # Test PR review server script
    log_info "Testing PR review server script..."
    
    # Use the correct Python command (might be in venv)
    TEST_PYTHON_CMD="$PYTHON_CMD"
    if [ -n "$VENV_PYTHON_PATH" ]; then
        TEST_PYTHON_CMD="$VENV_PYTHON_PATH"
    fi
    
    if $TEST_PYTHON_CMD -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
try:
    import pr_agent_server
    print('PR agent server script is valid')
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
" 2>/dev/null; then
        log_success "PR agent server script verified"
    else
        log_error "PR agent server script test failed"
        ((errors++))
    fi
    
    if [ $errors -eq 0 ]; then
        log_success "System setup verification completed successfully!"
    else
        log_warning "System setup completed with $errors errors. Please review the issues above."
    fi
}

# Main setup function
main() {
    log_info "Starting PR Review Agent system setup..."
    echo
    
    check_required_files
    check_python_version
    install_python_deps
    install_agents
    check_git
    
    echo
    log_success "System setup completed!"
    echo
    log_info "Next steps:"
    if [ -n "$VENV_PYTHON_PATH" ]; then
        echo "1. Virtual environment created at: $(dirname "$VENV_PYTHON_PATH")"
        echo "2. To start the PR Agent Server, first activate the virtual environment:"
        echo "   source $(dirname "$VENV_PYTHON_PATH")/bin/activate"
        echo "3. Then run: python $SCRIPT_DIR/pr_agent_server.py"
        echo "4. Server will be available at http://localhost:8080"
    else
        echo "1. The system is now ready to use the PR Agent Server"
        echo "2. To start the server: python $SCRIPT_DIR/pr_agent_server.py"
        echo "3. Server will be available at http://localhost:8080"
        echo "4. Use HTTP API or install as systemd service with install-services.sh"
    fi
    echo
    
    run_verification
}

# Usage info
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "PR Review Agent - System Setup Script"
    echo
    echo "This script sets up the development environment with required tools and libraries."
    echo "Run this once per development machine from the agent repository directory."
    echo
    echo "Usage: $0"
    echo
    echo "Requirements:"
    echo "  - Python 3.8+"
    echo "  - Node.js and npm"
    echo "  - Git"
    echo
    echo "The script will install:"
    echo "  - Python libraries: mcp, pygithub, gitpython, requests, pydantic, python-dotenv"
    echo "  - Claude Code (via npm)"
    echo "  - SourceGraph Amp (via npm)"
    echo
    exit 0
fi

# Run main setup
main
