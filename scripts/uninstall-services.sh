#!/bin/bash
set -e

# GitHub Agent Uninstall Script
# Removes all installed files, services, and configurations

echo "=== GitHub Agent Uninstall Script ==="
echo ""

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    USE_SYSTEMD=true
    INSTALL_DIR="/opt/github-agent"
    LOG_DIR="/var/log"
    SERVICE_FILE="/etc/systemd/system/pr-agent.service"
    echo "Detected Linux system (systemd)"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    USE_SYSTEMD=false
    INSTALL_DIR="$HOME/.local/share/github-agent"
    LOG_DIR="$INSTALL_DIR/logs"
    SERVICE_FILE="$HOME/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist"
    echo "Detected macOS system (launchd)"
else
    echo "❌ Unsupported OS: $OSTYPE"
    exit 1
fi

echo "Configuration:"
echo "  Install directory: $INSTALL_DIR"
echo "  Log directory: $LOG_DIR"
echo "  Service file: $SERVICE_FILE"
echo ""

# Confirmation prompt
read -p "⚠️  This will completely remove the GitHub Agent service and all data. Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstall cancelled."
    exit 0
fi
echo ""

# Stop and remove service
echo "🛑 Stopping and removing service..."
if [[ "$USE_SYSTEMD" == true ]]; then
    # Linux: systemd service
    if systemctl is-active --quiet pr-agent 2>/dev/null; then
        echo "  Stopping systemd service..."
        sudo systemctl stop pr-agent
    fi
    
    if systemctl is-enabled --quiet pr-agent 2>/dev/null; then
        echo "  Disabling systemd service..."
        sudo systemctl disable pr-agent
    fi
    
    if [ -f "$SERVICE_FILE" ]; then
        echo "  Removing systemd service file..."
        sudo rm -f "$SERVICE_FILE"
        sudo systemctl daemon-reload
    fi
    
else
    # macOS: launchd service
    if launchctl list | grep -q com.mstriebeck.github_mcp_server 2>/dev/null; then
        echo "  Stopping launchd service..."
        launchctl stop com.mstriebeck.github_mcp_server 2>/dev/null || true
        echo "  Unloading launchd service..."
        launchctl unload "$SERVICE_FILE" 2>/dev/null || true
    fi
    
    if [ -f "$SERVICE_FILE" ]; then
        echo "  Removing launchd plist file..."
        rm -f "$SERVICE_FILE"
    fi
fi

# Remove installation directory
echo "🗂️  Removing installation directory..."
if [ -d "$INSTALL_DIR" ]; then
    if [[ "$USE_SYSTEMD" == true ]]; then
        echo "  Removing $INSTALL_DIR (requires sudo)..."
        sudo rm -rf "$INSTALL_DIR"
    else
        echo "  Removing $INSTALL_DIR..."
        # Handle permission issues with cache files
        if ! rm -rf "$INSTALL_DIR" 2>/dev/null; then
            echo "  Permission issues detected, trying with sudo..."
            sudo rm -rf "$INSTALL_DIR" 2>/dev/null || {
                echo "  Removing files individually..."
                find "$INSTALL_DIR" -type f -delete 2>/dev/null || true
                find "$INSTALL_DIR" -type d -empty -delete 2>/dev/null || true
                # Final attempt with sudo if directory still exists
                if [ -d "$INSTALL_DIR" ]; then
                    sudo rm -rf "$INSTALL_DIR" 2>/dev/null || true
                fi
            }
        fi
    fi
else
    echo "  Installation directory not found (already removed)"
fi

# Remove log files
echo "🗃️  Removing log files..."
if [[ "$USE_SYSTEMD" == true ]]; then
    # Linux: Remove from /var/log
    if [ -f "/var/log/github_mcp_server.log" ]; then
        echo "  Removing system log file..."
        sudo rm -f "/var/log/github_mcp_server.log"
    fi
else
    # macOS: Logs are in install directory (already removed)
    echo "  Log files removed with installation directory"
fi

# Remove any leftover database files in current directory
echo "🗄️  Checking for leftover database files..."
if [ -f "pr_replies.db" ]; then
    echo "  Removing pr_replies.db from current directory..."
    rm -f "pr_replies.db"
fi

# Clean up any Python cache files
echo "🧹 Cleaning up cache files..."
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

echo ""
echo "=== Verification ==="

# Verify service removal
echo "🔍 Verifying service removal..."
if [[ "$USE_SYSTEMD" == true ]]; then
    if systemctl list-units --all | grep -q pr-agent; then
        echo "  ❌ systemd service still exists"
        CLEANUP_ISSUES=true
    else
        echo "  ✅ systemd service removed"
    fi
    
    if [ -f "$SERVICE_FILE" ]; then
        echo "  ❌ Service file still exists: $SERVICE_FILE"
        CLEANUP_ISSUES=true
    else
        echo "  ✅ Service file removed"
    fi
else
    if launchctl list | grep -q com.mstriebeck.github_mcp_server; then
        echo "  ❌ launchd service still running"
        CLEANUP_ISSUES=true
    else
        echo "  ✅ launchd service removed"
    fi
    
    if [ -f "$SERVICE_FILE" ]; then
        echo "  ❌ Service plist still exists: $SERVICE_FILE"
        CLEANUP_ISSUES=true
    else
        echo "  ✅ Service plist removed"
    fi
fi

# Verify directory removal
echo "🔍 Verifying directory removal..."
if [ -d "$INSTALL_DIR" ]; then
    echo "  ❌ Installation directory still exists: $INSTALL_DIR"
    CLEANUP_ISSUES=true
else
    echo "  ✅ Installation directory removed"
fi

# Verify log file removal
echo "🔍 Verifying log file removal..."
if [[ "$USE_SYSTEMD" == true ]]; then
    if [ -f "/var/log/github_mcp_server.log" ]; then
        echo "  ❌ Log file still exists: /var/log/github_mcp_server.log"
        CLEANUP_ISSUES=true
    else
        echo "  ✅ Log file removed"
    fi
else
    echo "  ✅ Log files removed with installation directory"
fi

# Check if service is still accessible
echo "🔍 Verifying service is not accessible..."
if curl -s http://localhost:8080/health >/dev/null 2>&1; then
    echo "  ❌ Service still responding on port 8080"
    echo "     You may need to manually kill the process:"
    echo "     lsof -ti:8080 | xargs kill -9"
    CLEANUP_ISSUES=true
else
    echo "  ✅ Service not accessible"
fi

# Check for any remaining processes
echo "🔍 Checking for remaining processes..."
if pgrep -f "github_mcp_server" > /dev/null; then
    echo "  ❌ GitHub MCP Server processes still running:"
    pgrep -f "github_mcp_server" | while read pid; do
        ps -p $pid -o pid,command
    done
    echo "     Run: pkill -f github_mcp_server"
    CLEANUP_ISSUES=true
else
    echo "  ✅ No remaining processes found"
fi

echo ""

# Final status
if [ "$CLEANUP_ISSUES" = true ]; then
    echo "⚠️  Uninstall completed with issues"
    echo "   Some items could not be removed automatically."
    echo "   See the verification output above for details."
    exit 1
else
    echo "✅ Uninstall completed successfully"
    echo "   All GitHub Agent components have been removed."
fi

echo ""
echo "To reinstall, run: ./scripts/install-services.sh"
