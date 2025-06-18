#!/bin/bash
set -euo pipefail

echo "🚀 Setting up PR Reply Queue System..."

# Check if we're in a virtual environment, if not activate it
if [ -z "${VIRTUAL_ENV:-}" ]; then
    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv .venv
    fi
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Upgrade pip and install dependencies
echo "Installing Python dependencies..."
pip install -U pip
pip install -r requirements.txt

# Check for required environment variables
echo "Checking environment variables..."
if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "⚠️  GITHUB_TOKEN environment variable not set"
    echo "   Please set it in your .env file or environment"
fi

# Initialize the database
echo "Initializing database..."
python3 -c "
import sys
sys.path.append('.')
from pr_agent_server import init_db
init_db()
print('Database initialized successfully')
"

echo "✅ PR Agent Server setup complete!"
echo ""
echo "Next steps:"
echo "1. Make sure GITHUB_TOKEN is set in your .env file"
echo "2. Start the unified server: python3 github_mcp_server.py"
echo "3. Server will be available at http://localhost:8080"
echo ""
echo "The server includes:"
echo "- All PR management tools via HTTP API"
echo "- Built-in background worker for queue processing"
echo "- Management interface at /status and /queue"
