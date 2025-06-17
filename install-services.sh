#!/bin/bash

# PR Agent Server Installation Script

set -e

# Configuration
SERVICE_USER="www-data"
SERVICE_GROUP="www-data"
INSTALL_DIR="/opt/github-agent"
LOG_DIR="/var/log"

echo "Installing PR Agent Server..."

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)" 
   exit 1
fi

# Create installation directory
echo "Creating installation directory..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/systemd"

# Copy files
echo "Copying service files..."
cp pr_agent_server.py "$INSTALL_DIR/"
cp pr_review_server.py "$INSTALL_DIR/"
cp pr_reply_worker.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"
cp requirements-http.txt "$INSTALL_DIR/"

# Copy .env if it exists, otherwise copy template
if [ -f ".env" ]; then
    echo "Copying environment file..."
    cp .env "$INSTALL_DIR/"
else
    echo "Copying environment template..."
    cp config/services.env "$INSTALL_DIR/.env"
    echo "*** IMPORTANT: Edit /opt/github-agent/.env with your GitHub token ***"
fi
chmod 600 "$INSTALL_DIR/.env"

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
cd "$INSTALL_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-http.txt

# Set ownership
echo "Setting file ownership..."
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"

# Create log file
echo "Creating log file..."
touch "$LOG_DIR/pr_agent_server.log"
chown "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR/pr_agent_server.log"

# Install systemd service file
echo "Installing systemd service file..."
cp systemd/pr-agent.service /etc/systemd/system/

# Reload systemd
echo "Reloading systemd..."
systemctl daemon-reload

# Enable service
echo "Enabling service..."
systemctl enable pr-agent.service

echo "Installation complete!"
echo ""
echo "Configuration:"
echo "  Edit /opt/github-agent/.env with your GitHub token and repo"
echo ""
echo "To start the service:"
echo "  sudo systemctl start pr-agent"
echo ""
echo "To check status:"
echo "  sudo systemctl status pr-agent"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u pr-agent -f"
echo ""
echo "Server will be available at:"
echo "  HTTP API: http://localhost:8080"
echo "  Health check: http://localhost:8080/health"
echo "  Status: http://localhost:8080/status"
