# GitHub MCP Server - Multi-Repository Support

This GitHub MCP server now supports multiple repositories through URL-based routing, allowing you to work with different repositories from a single Amp chat session.

## Quick Start

### 1. Initialize Configuration

Create a sample configuration:

```bash
python repository_cli.py init --example
```

This creates `~/.local/share/github-agent/repositories.json` with example entries.

### 2. Add Your Repositories

Add your actual repositories:

```bash
# Add your main project
python repository_cli.py add my-project /Users/yourusername/code/my-project --description="Personal project"

# Add a work repository
python repository_cli.py add work-stuff /Users/yourusername/work/important-project --description="Work project"
```

### 3. Validate Configuration

Check that everything is set up correctly:

```bash
python repository_cli.py validate
```

### 4. Start the Server

```bash
export GITHUB_TOKEN="your_github_token_here"
python github_mcp_server.py
```

### 5. Use Repository-Specific URLs

Each repository gets its own MCP endpoint:
- `http://localhost:8080/mcp/my-project/` → Your personal project
- `http://localhost:8080/mcp/work-stuff/` → Your work project

## Configuration

### Configuration File Location

The configuration file is stored at:
- `~/.local/share/github-agent/repositories.json` (default)
- Or set `GITHUB_AGENT_REPO_CONFIG` environment variable

### Configuration Format

```json
{
  "repositories": {
    "my-project": {
      "path": "/Users/yourusername/code/my-project",
      "description": "Personal project repository"
    },
    "work-stuff": {
      "path": "/Users/yourusername/work/important-project", 
      "description": "Work-related code"
    }
  }
}
```

### Repository Names

Repository names (the keys in the configuration):
- Become part of the URL: `/mcp/{name}/`
- Can only contain letters, numbers, hyphens, and underscores
- Should be short and memorable

## Repository Management CLI

### List Repositories

```bash
python repository_cli.py list
```

Shows all configured repositories with their paths, descriptions, and URLs.

### Add Repository

```bash
python repository_cli.py add <name> <path> [--description="..."]
```

Examples:
```bash
python repository_cli.py add my-app /home/user/projects/my-app
python repository_cli.py add work-api /work/api --description="Company API"
```

### Remove Repository

```bash
python repository_cli.py remove <name>
```

### Validate Configuration

```bash
python repository_cli.py validate
```

Checks that:
- Configuration file is valid JSON
- All repository paths exist
- All paths are git repositories
- No permission issues

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub personal access token | Required |
| `GITHUB_AGENT_REPO_CONFIG` | Path to repositories.json | `~/.local/share/github-agent/repositories.json` |
| `GITHUB_AGENT_DEV_MODE` | Enable hot reload of config | `false` |
| `SERVER_HOST` | Server bind address | `0.0.0.0` |
| `SERVER_PORT` | Server port | `8080` |

## Hot Reload (Development Mode)

Enable automatic configuration reloading:

```bash
export GITHUB_AGENT_DEV_MODE=true
python github_mcp_server.py
```

When enabled, the server watches the configuration file and automatically reloads when you:
- Add repositories with the CLI
- Remove repositories with the CLI  
- Manually edit the configuration file

## Backward Compatibility

### Single Repository Mode

If no configuration file exists, the server falls back to single-repository mode using:
- `LOCAL_REPO_PATH` environment variable
- Endpoint: `http://localhost:8080/mcp/default/`

### Migration from Single Repository

To migrate from the old single-repository setup:

1. Note your current `LOCAL_REPO_PATH`
2. Initialize multi-repo configuration: `python repository_cli.py init`
3. Add your repository: `python repository_cli.py add default $LOCAL_REPO_PATH`
4. Remove `LOCAL_REPO_PATH` from your environment
5. Restart the server

## Tools and Integration

### Available Tools

All GitHub tools work with repository context:
- `get_current_branch` - Get current branch for specific repository
- `get_current_commit` - Get current commit for specific repository  
- `find_pr_for_branch` - Find PR in specific repository
- `get_pr_comments` - Get PR comments from specific repository
- `post_pr_reply` - Reply to PR comment in specific repository

### Tool Descriptions

Tool descriptions include repository context:
- "Get current branch for my-project"
- "Find PR associated with branch in work-stuff"

### Error Handling

Clear error messages when:
- Repository name not found in URL
- Repository path doesn't exist  
- Git repository issues
- GitHub API problems

## Server Endpoints

### Repository-Specific MCP

- `GET /mcp/{repo-name}/` - SSE endpoint for repository
- `POST /mcp/{repo-name}/` - MCP JSON-RPC for repository

### Server Information

- `GET /` - Server status with repository list
- `GET /health` - Health check with repository count
- `GET /status` - Detailed status with repository info

## Troubleshooting

### "Repository not found" Error

1. Check repository name spelling in URL
2. Run `python repository_cli.py list` to see available repositories
3. Verify configuration with `python repository_cli.py validate`

### Configuration Issues

1. Check file exists: `~/.local/share/github-agent/repositories.json`
2. Validate JSON format: `python repository_cli.py validate`
3. Check file permissions
4. Verify repository paths exist

### Server Won't Start

1. Check GitHub token: `echo $GITHUB_TOKEN`
2. Validate configuration: `python repository_cli.py validate`
3. Check server logs for detailed error messages
4. Ensure port 8080 is not in use

### Hot Reload Not Working

1. Enable dev mode: `export GITHUB_AGENT_DEV_MODE=true`
2. Check server logs for watcher messages
3. Verify file permissions on configuration file

## Examples

### Development Setup

```bash
# Set up for development work
export GITHUB_TOKEN="ghp_your_token_here"
export GITHUB_AGENT_DEV_MODE=true

# Initialize configuration  
python repository_cli.py init

# Add your projects
python repository_cli.py add personal /Users/you/code/personal-project
python repository_cli.py add work /Users/you/work/company-project  
python repository_cli.py add oss /Users/you/opensource/cool-project

# Validate and start
python repository_cli.py validate
python github_mcp_server.py
```

### Production Setup

```bash
# Set up for production use
export GITHUB_TOKEN="ghp_your_token_here"

# Add production repositories
python repository_cli.py add frontend /production/frontend
python repository_cli.py add backend /production/backend
python repository_cli.py add infra /production/infrastructure

# Start server
python github_mcp_server.py
```

URLs will be:
- `http://localhost:8080/mcp/frontend/`
- `http://localhost:8080/mcp/backend/`  
- `http://localhost:8080/mcp/infra/`
