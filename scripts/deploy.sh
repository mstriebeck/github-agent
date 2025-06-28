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

# Function to check for TIME_WAIT connections on a port
has_time_wait_connections() {
    local port="$1"
    netstat -an | grep ":$port " | grep -q "TIME_WAIT"
}

# Function to wait for TIME_WAIT connections to be cleaned up
wait_for_time_wait_cleanup() {
    local ports="$1"
    local max_wait=30
    local elapsed=0
    
    echo "Checking for TIME_WAIT connections that need cleanup..."
    
    local has_time_wait=false
    for port in $ports; do
        if has_time_wait_connections "$port"; then
            echo "Found TIME_WAIT connections on port $port"
            has_time_wait=true
        fi
    done
    
    if [[ "$has_time_wait" == false ]]; then
        echo "No TIME_WAIT connections found, proceeding..."
        return 0
    fi
    
    echo "Waiting for TIME_WAIT connections to be cleaned up..."
    while [[ $elapsed -lt $max_wait ]]; do
        local all_clear=true
        
        for port in $ports; do
            if has_time_wait_connections "$port"; then
                all_clear=false
                break
            fi
        done
        
        if [[ "$all_clear" == true ]]; then
            echo "All TIME_WAIT connections cleared after ${elapsed}s"
            return 0
        fi
        
        sleep 1
        elapsed=$((elapsed + 1))
        
        # Log progress every 5 seconds
        if [[ $((elapsed % 5)) -eq 0 ]]; then
            echo "Still waiting for TIME_WAIT cleanup... (${elapsed}s elapsed)"
        fi
    done
    
    echo "Warning: Some TIME_WAIT connections may still exist after ${max_wait}s"
    return 0  # Don't fail the deployment for this
}

# Function to wait for ports to be freed
wait_for_ports_free() {
    local config_file="$1"
    local timeout="${2:-60}"   # Default 60 seconds (reduced since shutdown waits for ports)
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
    echo "🛑 Stopping GitHub MCP server (may take up to 60 seconds for graceful port cleanup)..."
    launchctl unload ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist 2>/dev/null || echo "Service not running"
    echo "✅ Server stopped successfully"
fi

# Wait for ports to be freed (skip during install since no config exists yet)
if [[ "$INSTALL_MODE" == false ]]; then
    config_file="$INSTALL_DIR/repositories.json"
    if [[ -f "$config_file" ]]; then
        # Get the ports that need to be checked
        ports=$(get_ports_from_config "$config_file")
        if [[ $? -eq 0 ]] && [[ -n "$ports" ]]; then
            # First, wait for any TIME_WAIT connections to be cleaned up
            wait_for_time_wait_cleanup "$ports"
            
            # Then wait for ports to be completely free
            if ! wait_for_ports_free "$config_file" 30; then
                echo "Error: Failed to free up ports. Deployment aborted." >&2
                echo "Please manually stop any conflicting processes and try again." >&2
                exit 1
            fi
        else
            echo "Warning: Could not get ports from config, skipping port check"
        fi
    else
        echo "Warning: Config file not found at $config_file, skipping port check"
    fi
fi

# Function to deploy a file (print, remove, copy)
deploy_file() {
    local filename="$1"
    echo "Copying $filename..."
    
    # Force remove with extended attributes
    if [ -f "$INSTALL_DIR/$filename" ]; then
        rm -f "$INSTALL_DIR/$filename"
        # Clear any extended attributes that might prevent overwrite
        [ -f "$INSTALL_DIR/$filename" ] && xattr -c "$INSTALL_DIR/$filename" 2>/dev/null || true
    fi
    
    cp "$filename" "$INSTALL_DIR/"
}

# Copy files from project root
echo "Copying service files..."
cd "$PROJECT_ROOT"

# Deploy core service files
deploy_file "github_mcp_master.py"
deploy_file "github_mcp_worker.py"
deploy_file "github_tools.py"
deploy_file "repository_manager.py"
deploy_file "repositories.json"
deploy_file "requirements.txt"

# Deploy shutdown system files
deploy_file "shutdown_manager.py"
deploy_file "exit_codes.py"
deploy_file "health_monitor.py"
deploy_file "shutdown_core.py"
deploy_file "system_utils.py"

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
