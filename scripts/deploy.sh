#!/bin/bash

# GitHub Agent Deploy Script
# Copies files to install location and restarts the service
# Can be used standalone for deployments after code changes

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Detect OS
OS="$(uname)"
case $OS in
  'Linux')
    INSTALL_DIR="/opt/github-agent"
    USE_SYSTEMD=true
    ;;
  'Darwin')
    INSTALL_DIR="$HOME/.local/share/github-agent"
    USE_SYSTEMD=false
    ;;
  *)
    echo "Unsupported OS: $OS"
    exit 1
    ;;
esac

# Check if installation directory exists
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Error: Installation directory $INSTALL_DIR not found"
    echo "Please run the install script first"
    exit 1
fi

echo "Deploying GitHub Agent to $INSTALL_DIR..."

# Check for install mode (called from install script)
INSTALL_MODE=false
if [[ "$1" == "--install-mode" ]]; then
    INSTALL_MODE=true
fi

# Stop service before deployment (skip during install)
if [[ "$INSTALL_MODE" == false ]]; then
    echo "Stopping service..."
    if [[ "$USE_SYSTEMD" == true ]]; then
        systemctl stop pr-agent 2>/dev/null || echo "Service not running"
    else
        launchctl stop com.mstriebeck.github_mcp_server 2>/dev/null || echo "Service not running"
    fi
fi

# Copy files from project root
echo "Copying service files..."
cd "$PROJECT_ROOT"

# Remove existing Python files to avoid permission issues
[ -f "$INSTALL_DIR/github_mcp_master.py" ] && rm -f "$INSTALL_DIR/github_mcp_master.py"
[ -f "$INSTALL_DIR/github_mcp_worker.py" ] && rm -f "$INSTALL_DIR/github_mcp_worker.py"
[ -f "$INSTALL_DIR/github_tools.py" ] && rm -f "$INSTALL_DIR/github_tools.py"
[ -f "$INSTALL_DIR/queue_models.py" ] && rm -f "$INSTALL_DIR/queue_models.py"
[ -f "$INSTALL_DIR/repository_manager.py" ] && rm -f "$INSTALL_DIR/repository_manager.py"
[ -f "$INSTALL_DIR/repository_cli.py" ] && rm -f "$INSTALL_DIR/repository_cli.py"
[ -f "$INSTALL_DIR/requirements.txt" ] && rm -f "$INSTALL_DIR/requirements.txt"

# Copy updated files
cp github_mcp_master.py "$INSTALL_DIR/"
cp github_mcp_worker.py "$INSTALL_DIR/"
cp github_tools.py "$INSTALL_DIR/"
cp queue_models.py "$INSTALL_DIR/"
cp repository_manager.py "$INSTALL_DIR/"
cp repository_cli.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"

# Update dependencies if requirements changed
echo "Updating Python dependencies..."
cd "$INSTALL_DIR"
source .venv/bin/activate
pip install -r requirements.txt --upgrade

# Set ownership (Linux only)
if [[ "$USE_SYSTEMD" == true ]]; then
    chown -R www-data:www-data "$INSTALL_DIR"
fi

# Start service (skip during install)
if [[ "$INSTALL_MODE" == false ]]; then
    echo "Starting service..."
    if [[ "$USE_SYSTEMD" == true ]]; then
        systemctl start pr-agent
        echo "Service started. Check status with: sudo systemctl status pr-agent"
    else
        launchctl start com.mstriebeck.github_mcp_server
        echo "Service started. Check status with: launchctl list | grep github_mcp_server"
    fi
    
    echo "Deployment complete!"
else
    echo "Files deployed (install mode - service management handled by install script)"
fi
