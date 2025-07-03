#!/bin/bash

# PR Agent Server Installation Script
# Supports Linux (systemd) and macOS (launchd)

set -e

# Detect OS
OS="$(uname)"
case $OS in
  'Linux')
    echo "Detected Linux system"
    SERVICE_USER="www-data"
    SERVICE_GROUP="www-data"
    INSTALL_DIR="/opt/github-agent"
    LOG_DIR="/var/log"
    USE_SYSTEMD=true
    ;;
  'Darwin')
    echo "Detected macOS system"
    SERVICE_USER="$(whoami)"
    SERVICE_GROUP="staff"
    INSTALL_DIR="$HOME/.local/share/github-agent"
    LOG_DIR="$HOME/.local/share/github-agent/logs"
    USE_SYSTEMD=false
    ;;
  *)
    echo "Unsupported OS: $OS"
    echo "This script supports Linux and macOS only"
    exit 1
    ;;
esac

echo "Installing GitHub MCP Server for $OS..."

# Check if running as root (Linux only)
if [[ "$USE_SYSTEMD" == true && $EUID -ne 0 ]]; then
   echo "On Linux, this script must be run as root (use sudo)" 
   exit 1
fi

# Create installation directory
echo "Creating installation directory..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$LOG_DIR"

# Copy files
echo "Copying service files..."
# Remove existing files if they exist to avoid permission issues
[ -f "$INSTALL_DIR/mcp_master.py" ] && rm -f "$INSTALL_DIR/mcp_master.py"
[ -f "$INSTALL_DIR/github_mcp_worker.py" ] && rm -f "$INSTALL_DIR/github_mcp_worker.py"
[ -f "$INSTALL_DIR/requirements.txt" ] && rm -f "$INSTALL_DIR/requirements.txt"
cp mcp_master.py "$INSTALL_DIR/"
cp github_mcp_worker.py "$INSTALL_DIR/"
cp github_tools.py "$INSTALL_DIR/"
cp repository_manager.py "$INSTALL_DIR/"
cp repository_cli.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"

# Copy configuration if it exists
if [ -f "repositories.json" ]; then
    echo "Copying repository configuration..."
    cp repositories.json "$INSTALL_DIR/"
fi

# Copy .env if it exists, otherwise copy template
if [ -f ".env" ]; then
    echo "Copying environment file..."
    cp .env "$INSTALL_DIR/"
else
    echo "Copying environment template..."
    cp config/services.env "$INSTALL_DIR/.env"
    echo "*** IMPORTANT: Edit $INSTALL_DIR/.env with your GitHub token ***"
fi
chmod 600 "$INSTALL_DIR/.env"

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
cd "$INSTALL_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set up repository configuration
echo "Setting up repository configuration..."
if [ ! -f "repositories.json" ]; then
    echo "Creating initial repository configuration..."
    python repository_cli.py init --example
    
    # If we're in a git repository, try to add it
    ORIGINAL_DIR="$(dirname "$(dirname "$0")")"
    if [ -d "$ORIGINAL_DIR/.git" ]; then
        REPO_NAME=$(basename "$ORIGINAL_DIR")
        echo "Adding current repository: $REPO_NAME"
        python repository_cli.py remove example-repo 2>/dev/null || true
        python repository_cli.py add "$REPO_NAME" "$ORIGINAL_DIR" --description="$REPO_NAME repository"
    fi
    
    # Assign ports
    python repository_cli.py assign-ports
    echo "Repository configuration created. Add more repositories with:"
    echo "  $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/repository_cli.py add <name> <path>"
else
    echo "Repository configuration already exists"
    # Ensure ports are assigned
    python repository_cli.py assign-ports 2>/dev/null || true
fi

# Set ownership (Linux only)
if [[ "$USE_SYSTEMD" == true ]]; then
    echo "Setting file ownership..."
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
fi

# Create log file
echo "Creating log file..."
touch "$LOG_DIR/github_mcp_server.log"
if [[ "$USE_SYSTEMD" == true ]]; then
    chown "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR/github_mcp_server.log"
fi

# Install service (OS-specific)
if [[ "$USE_SYSTEMD" == true ]]; then
    # Linux: Install systemd service
    echo "Installing systemd service file..."
    cp systemd/pr-agent.service /etc/systemd/system/
    
    # Reload systemd
    echo "Reloading systemd..."
    systemctl daemon-reload
    
    # Enable service
    echo "Enabling service..."
    systemctl enable pr-agent.service
else
    # macOS: Create launchd plist
    echo "Creating launchd service for macOS..."
    mkdir -p "$HOME/Library/LaunchAgents"
    
    # Stop and unload existing service if it exists
    if [ -f "$HOME/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist" ]; then
        echo "Stopping existing service..."
        launchctl stop com.mstriebeck.github_mcp_server 2>/dev/null || true
        launchctl unload "$HOME/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist"
    fi
    
    cat > "$HOME/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mstriebeck.github_mcp_server</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/.venv/bin/python</string>
        <string>$INSTALL_DIR/mcp_master.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/github_mcp_server.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/github_mcp_server.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ExitTimeOut</key>
    <integer>180</integer>
</dict>
</plist>
EOF
    
    echo "Loading launchd service..."
    launchctl load "$HOME/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist"
fi

echo "Installation complete!"
echo ""
echo "Configuration:"
echo "  Edit $INSTALL_DIR/.env with your GitHub token"
echo ""

if [[ "$USE_SYSTEMD" == true ]]; then
    echo "To start the service (Linux):"
    echo "  sudo systemctl start pr-agent"
    echo ""
    echo "To check status:"
    echo "  sudo systemctl status pr-agent"
    echo ""
    echo "To view logs:"
    echo "  sudo journalctl -u pr-agent -f"
    echo "  tail -f $LOG_DIR/github_mcp_server.log"
else
    echo "Service management (macOS):"
    echo "  Start: launchctl start com.mstriebeck.github_mcp_server"
    echo "  (Service auto-starts on login and auto-restarts if it stops)"
    echo ""
    echo "To check status:"
    echo "  launchctl list | grep github_mcp_server"
    echo ""
    echo "To view logs:"
    echo "  tail -f $LOG_DIR/github_mcp_server.log"
    echo ""
    echo "To restart the service (temporary stop - will auto-restart):"
    echo "  launchctl stop com.mstriebeck.github_mcp_server"
    echo ""
    echo "To permanently stop the service:"
    echo "  launchctl unload ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist"
    echo ""
    echo "To reload the service:"
    echo "  launchctl load ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist"
fi

echo ""
echo "Multi-port GitHub MCP Server will be available at:"
echo "  Repository management: $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/repository_cli.py"
echo "  Add repositories: $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/repository_cli.py add <name> <path>"
echo "  Check status: $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/repository_cli.py status"
echo ""
echo "Each repository will get its own port starting from 8081:"
echo "  Repository 1: http://localhost:8081/mcp/ (health: http://localhost:8081/health)"
echo "  Repository 2: http://localhost:8082/mcp/ (health: http://localhost:8082/health)"
