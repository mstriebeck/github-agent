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

# Function to get ports from repositories.json
get_ports_from_config() {
    local config_file="$1"
    if [[ ! -f "$config_file" ]]; then
        echo "Warning: $config_file not found, cannot check ports" >&2
        return 1
    fi
    
    # Extract ports using python/jq - try jq first, fallback to python
    if command -v jq >/dev/null 2>&1; then
        jq -r '.repositories | to_entries[] | .value.port' "$config_file" 2>/dev/null
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "
import json, sys
try:
    with open('$config_file') as f:
        data = json.load(f)
    for repo in data.get('repositories', {}).values():
        if 'port' in repo:
            print(repo['port'])
except Exception as e:
    sys.exit(1)
" 2>/dev/null
    else
        echo "Error: Neither jq nor python3 available to parse config" >&2
        return 1
    fi
}

# Function to check if a port is free
is_port_free() {
    local port="$1"
    ! lsof -i ":$port" >/dev/null 2>&1
}

# Function to wait for ports to be freed
wait_for_ports_free() {
    local config_file="$1"
    local timeout="${2:-30}"  # Default 30 seconds
    local check_interval=1
    local elapsed=0
    
    echo "Getting ports from $config_file..."
    local ports
    ports=$(get_ports_from_config "$config_file")
    if [[ $? -ne 0 ]] || [[ -z "$ports" ]]; then
        echo "Warning: Could not get ports from config, skipping port check"
        return 0
    fi
    
    echo "Waiting for ports to be freed: $ports"
    
    while [[ $elapsed -lt $timeout ]]; do
        local all_free=true
        
        for port in $ports; do
            if ! is_port_free "$port"; then
                echo "Port $port still in use..."
                all_free=false
                break
            fi
        done
        
        if [[ "$all_free" == true ]]; then
            echo "All ports are now free"
            return 0
        fi
        
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
        echo "Waited ${elapsed}s for ports to be freed..."
    done
    
    echo "Error: Ports still in use after ${timeout}s timeout:" >&2
    for port in $ports; do
        if ! is_port_free "$port"; then
            echo "  Port $port: $(lsof -i ":$port" 2>/dev/null || echo 'unknown process')" >&2
        fi
    done
    return 1
}

# Always stop service first (even in install mode for safety)
echo "Stopping service..."
if [[ "$USE_SYSTEMD" == true ]]; then
    systemctl stop pr-agent 2>/dev/null || echo "Service not running"
else
    launchctl unload ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist 2>/dev/null || echo "Service not running"
fi

# Wait for ports to be freed (skip during install since no config exists yet)
if [[ "$INSTALL_MODE" == false ]]; then
    config_file="$INSTALL_DIR/repositories.json"
    if [[ -f "$config_file" ]]; then
        if ! wait_for_ports_free "$config_file" 30; then
            echo "Error: Failed to free up ports. Deployment aborted." >&2
            echo "Please manually stop any conflicting processes and try again." >&2
            exit 1
        fi
    else
        echo "Warning: Config file not found at $config_file, skipping port check"
    fi
fi

# Copy files from project root
echo "Copying service files..."
cd "$PROJECT_ROOT"

# Remove existing Python files to avoid permission issues
[ -f "$INSTALL_DIR/github_mcp_master.py" ] && rm -f "$INSTALL_DIR/github_mcp_master.py"
[ -f "$INSTALL_DIR/github_mcp_worker.py" ] && rm -f "$INSTALL_DIR/github_mcp_worker.py"
[ -f "$INSTALL_DIR/github_tools.py" ] && rm -f "$INSTALL_DIR/github_tools.py"
[ -f "$INSTALL_DIR/repository_manager.py" ] && rm -f "$INSTALL_DIR/repository_manager.py"
[ -f "$INSTALL_DIR/repository_cli.py" ] && rm -f "$INSTALL_DIR/repository_cli.py"
[ -f "$INSTALL_DIR/requirements.txt" ] && rm -f "$INSTALL_DIR/requirements.txt"
# Remove shutdown system files
[ -f "$INSTALL_DIR/shutdown_manager.py" ] && rm -f "$INSTALL_DIR/shutdown_manager.py"
[ -f "$INSTALL_DIR/exit_codes.py" ] && rm -f "$INSTALL_DIR/exit_codes.py"
[ -f "$INSTALL_DIR/health_monitor.py" ] && rm -f "$INSTALL_DIR/health_monitor.py"
[ -f "$INSTALL_DIR/shutdown_core.py" ] && rm -f "$INSTALL_DIR/shutdown_core.py"
[ -f "$INSTALL_DIR/system_utils.py" ] && rm -f "$INSTALL_DIR/system_utils.py"

# Copy updated files
cp github_mcp_master.py "$INSTALL_DIR/"
cp github_mcp_worker.py "$INSTALL_DIR/"
cp github_tools.py "$INSTALL_DIR/"
cp repository_manager.py "$INSTALL_DIR/"
cp repository_cli.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"
# Copy shutdown system files
cp shutdown_manager.py "$INSTALL_DIR/"
cp exit_codes.py "$INSTALL_DIR/"
cp health_monitor.py "$INSTALL_DIR/"
cp shutdown_core.py "$INSTALL_DIR/"
cp system_utils.py "$INSTALL_DIR/"

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
        launchctl load ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist
        echo "Service started. Check status with: launchctl list | grep github_mcp_server"
    fi
    
    echo "Deployment complete!"
else
    echo "Files deployed (install mode - service management handled by install script)"
fi
