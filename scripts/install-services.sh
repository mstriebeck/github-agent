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

echo "Installing PR Agent Server for $OS..."

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
cp pr_agent_server.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"

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

# Set ownership (Linux only)
if [[ "$USE_SYSTEMD" == true ]]; then
    echo "Setting file ownership..."
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
fi

# Create log file
echo "Creating log file..."
touch "$LOG_DIR/pr_agent_server.log"
if [[ "$USE_SYSTEMD" == true ]]; then
    chown "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR/pr_agent_server.log"
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
    
    cat > "$HOME/Library/LaunchAgents/com.github.pr-agent.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.github.pr-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/.venv/bin/python</string>
        <string>$INSTALL_DIR/pr_agent_server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/pr_agent_server.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/pr_agent_server.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF
    
    echo "Loading launchd service..."
    launchctl load "$HOME/Library/LaunchAgents/com.github.pr-agent.plist"
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
    echo "  tail -f $LOG_DIR/pr_agent_server.log"
else
    echo "To start the service (macOS):"
    echo "  launchctl start com.github.pr-agent"
    echo "  (Service auto-starts on login)"
    echo ""
    echo "To check status:"
    echo "  launchctl list | grep pr-agent"
    echo ""
    echo "To view logs:"
    echo "  tail -f $LOG_DIR/pr_agent_server.log"
    echo ""
    echo "To stop the service:"
    echo "  launchctl stop com.github.pr-agent"
    echo ""
    echo "To unload the service:"
    echo "  launchctl unload ~/Library/LaunchAgents/com.github.pr-agent.plist"
fi

echo ""
echo "Server will be available at:"
echo "  HTTP API: http://localhost:8080"
echo "  Health check: http://localhost:8080/health"
echo "  Status: http://localhost:8080/status"
