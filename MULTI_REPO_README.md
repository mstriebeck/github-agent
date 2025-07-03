# Multi-Repository GitHub MCP Server Setup Guide

This guide covers the detailed setup and configuration of the multi-port GitHub MCP Server architecture.

## 📋 Table of Contents

1. [System Requirements](#system-requirements)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Starting the Server](#starting-the-server)
5. [Client Configuration](#client-configuration)
6. [Monitoring and Logging](#monitoring-and-logging)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Configuration](#advanced-configuration)

---

## 🔧 System Requirements

### Prerequisites
- Python 3.8+
- Git repositories with GitHub remotes
- GitHub Personal Access Token (classic, with `repo` scope)
- Write access to `~/.local/share/github-agent/` directory

### Supported Platforms
- macOS
- Linux  
- Windows (with WSL)

---

## 📦 Installation

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/your-org/github-agent.git
cd github-agent

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Setup

```bash
# Required: Set your GitHub token
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional: Custom configuration location
export GITHUB_AGENT_REPO_CONFIG=/custom/path/repositories.json

# Optional: Enable development mode (hot reload)
export GITHUB_AGENT_DEV_MODE=true
```

### 3. Verify Installation

```bash
# Test the CLI
python3 repository_cli.py --help

# Test master process
python3 mcp_master.py status
```

---

## ⚙️ Configuration

### Initialize Configuration

```bash
# Create initial configuration structure
python3 repository_cli.py init --example
```

This creates a `repositories.json` file with example configuration:

```json
{
  "repositories": {
    "example-repo": {
      "path": "/path/to/your/repository",
      "port": 8081,
      "description": "Example repository for GitHub MCP"
    }
  }
}
```

### Add Your Repositories

```bash
# Add repositories one by one
python3 repository_cli.py add github-agent /Volumes/Code/github-agent \
  --description="GitHub Agent repository"

python3 repository_cli.py add my-project /Users/me/projects/my-project \
  --description="My awesome project"

# Add more repositories as needed
python3 repository_cli.py add website /var/www/website \
  --description="Company website"
```

### Assign Ports

```bash
# Auto-assign ports starting from 8081
python3 repository_cli.py assign-ports

# Or specify a custom starting port
python3 repository_cli.py assign-ports --start-port=9000
```

### Verify Configuration

```bash
# List all configured repositories
python3 repository_cli.py list

# Validate configuration
python3 repository_cli.py validate
```

Example output:
```
Configured repositories (3):

  ✅ github-agent
     Path: /Volumes/Code/github-agent
     Description: GitHub Agent repository
     Port: 8081
     URL: http://localhost:8081/mcp/

  ✅ my-project
     Path: /Users/me/projects/my-project
     Description: My awesome project
     Port: 8082
     URL: http://localhost:8082/mcp/

  ❌ website
     Path: /var/www/website
     Description: Company website
     Port: 8083
     URL: http://localhost:8083/mcp/
```

---

## 🚀 Starting the Server

### Start Multi-Port Architecture

```bash
# Start master process (spawns all workers)
python3 mcp_master.py
```

The master process will:
1. Load configuration from `repositories.json`
2. Validate all repository paths
3. Spawn worker processes for each repository
4. Monitor worker health and restart if needed

### Verify Services

```bash
# Check system status
python3 repository_cli.py status

# Test individual endpoints
curl http://localhost:8081/health
curl http://localhost:8082/health
curl http://localhost:8083/health

# Test MCP endpoints
curl http://localhost:8081/
curl http://localhost:8082/
```

### Background Operation

To run the server in the background:

```bash
# Using nohup
nohup python3 mcp_master.py > /dev/null 2>&1 &

# Using screen
screen -S github-mcp
python3 mcp_master.py
# Press Ctrl+A, then D to detach

# Using tmux
tmux new-session -d -s github-mcp 'python3 mcp_master.py'
```

---

## 🔌 Client Configuration

### MCP Client Setup

Each repository gets its own dedicated MCP endpoint. Configure your MCP clients to connect to the specific repository ports:

#### For Amp/Claude Desktop

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "github-agent": {
      "command": "curl",
      "args": ["-X", "GET", "http://localhost:8081/mcp/"]
    },
    "my-project": {
      "command": "curl", 
      "args": ["-X", "GET", "http://localhost:8082/mcp/"]
    }
  }
}
```

#### Direct HTTP Connections

```bash
# Connect to specific repository
curl -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{}}' \
     http://localhost:8081/mcp/
```

### Endpoint URLs

Each repository provides these endpoints:

- **Health Check**: `http://localhost:<port>/health`
- **Repository Info**: `http://localhost:<port>/`
- **MCP Protocol**: `http://localhost:<port>/mcp/` (GET for SSE, POST for JSON-RPC)

---

## 📊 Monitoring and Logging

### Log Files

Logs are stored in `~/.local/share/github-agent/logs/`:

```bash
# Master process logs
tail -f ~/.local/share/github-agent/logs/master.log

# Individual repository logs
tail -f ~/.local/share/github-agent/logs/github-agent.log
tail -f ~/.local/share/github-agent/logs/my-project.log

# Follow all logs
tail -f ~/.local/share/github-agent/logs/*.log
```

### System Status

```bash
# Comprehensive status check
python3 repository_cli.py status

# Check running processes
ps aux | grep github_mcp

# Check port usage
netstat -tlnp | grep 808
```

### Health Monitoring

Set up monitoring scripts:

```bash
#!/bin/bash
# health-check.sh

for port in 8081 8082 8083; do
  if curl -f -s "http://localhost:$port/health" > /dev/null; then
    echo "✅ Port $port: healthy"
  else
    echo "❌ Port $port: unhealthy"
  fi
done
```

---

## 🐛 Troubleshooting

### Common Issues

#### 1. Port Already in Use

```bash
# Check what's using the port
lsof -i :8081

# Kill process using port
kill -9 $(lsof -t -i:8081)

# Reassign ports
python3 repository_cli.py assign-ports --start-port=9000
```

#### 2. Repository Path Issues

```bash
# Check repository paths
python3 repository_cli.py validate

# Fix path issues
python3 repository_cli.py remove broken-repo
python3 repository_cli.py add fixed-repo /correct/path
```

#### 3. GitHub Token Issues

```bash
# Test token manually
curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user

# Check token scopes
curl -I -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user
```

#### 4. Worker Process Crashes

```bash
# Check worker logs
tail -n 50 ~/.local/share/github-agent/logs/<repo-name>.log

# Restart specific worker
pkill -f "mcp_worker.py --repo-name <repo-name>"
# Master will automatically restart it
```

### Debug Mode

Run individual components for debugging:

```bash
# Test single worker
python3 mcp_worker.py \
  --repo-name github-agent \
  --repo-path /Volumes/Code/github-agent \
  --port 8081 \
  --description "GitHub Agent repository"

# Test master without workers
python3 mcp_master.py status
```

---

## 🎛️ Advanced Configuration

### Custom Port Ranges

```bash
# Configure specific port ranges for different environments
python3 repository_cli.py assign-ports --start-port=8100  # Development
python3 repository_cli.py assign-ports --start-port=9100  # Staging
python3 repository_cli.py assign-ports --start-port=10100 # Production
```

### Multiple Configuration Files

```bash
# Development environment
export GITHUB_AGENT_REPO_CONFIG=./config/dev-repositories.json
python3 mcp_master.py

# Production environment  
export GITHUB_AGENT_REPO_CONFIG=/etc/github-agent/repositories.json
python3 mcp_master.py
```

### Process Management

```bash
# Create systemd service for production
sudo tee /etc/systemd/system/github-mcp.service << EOF
[Unit]
Description=GitHub MCP Multi-Port Server
After=network.target

[Service]
Type=simple
User=github-agent
WorkingDirectory=/opt/github-agent
Environment=GITHUB_TOKEN=your_token_here
ExecStart=/opt/github-agent/.venv/bin/python github_mcp_master.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable github-mcp
sudo systemctl start github-mcp
```

### Load Balancing

For high-availability setups, you can run multiple instances:

```bash
# Instance 1 (ports 8081-8090)
GITHUB_AGENT_REPO_CONFIG=config/instance1.json python3 mcp_master.py

# Instance 2 (ports 8091-8100)  
GITHUB_AGENT_REPO_CONFIG=config/instance2.json python3 mcp_master.py
```

---

## 🔄 Migration from Single-Port

### Step-by-Step Migration

1. **Stop existing service**:
   ```bash
   # macOS
   launchctl unload ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist
   
   # Linux
   sudo systemctl stop pr-agent
   ```

2. **Backup existing configuration**:
   ```bash
   cp ~/.local/share/github-agent/.env ~/backup-github-agent.env
   ```

3. **Set up multi-repository configuration**:
   ```bash
   python3 repository_cli.py init --example
   python3 repository_cli.py add main-repo /path/to/your/repo
   python3 repository_cli.py assign-ports
   ```

4. **Update client configurations** to use new dedicated ports instead of URL routing

5. **Start new architecture**:
   ```bash
   python3 mcp_master.py
   ```

6. **Verify functionality** with your MCP clients

---

## 📞 Support

If you encounter issues:

1. Check the [troubleshooting section](#troubleshooting)
2. Review logs in `~/.local/share/github-agent/logs/`
3. Validate configuration with `python3 repository_cli.py validate`
4. Test individual components in debug mode

For additional help, please refer to the main [README.md](README.md) or create an issue in the project repository.
