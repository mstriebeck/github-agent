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

if [ -z "${GITHUB_REPO:-}" ]; then
    echo "⚠️  GITHUB_REPO environment variable not set"
    echo "   Please set it in your .env file (format: owner/repo)"
fi

# Initialize the database
echo "Initializing database..."
python3 -c "
import sys
sys.path.append('.')
from pr_review_server import init_db
init_db()
print('Database initialized successfully')
"

echo "✅ PR Reply Queue setup complete!"
echo ""
echo "Next steps:"
echo "1. Make sure GITHUB_TOKEN and GITHUB_REPO are set in your .env file"
echo "2. Start the MCP server: python3 pr_review_server.py"
echo "3. Start the background worker: python3 pr_reply_worker.py"
echo ""
echo "The queue database is stored in pr_replies.db"
