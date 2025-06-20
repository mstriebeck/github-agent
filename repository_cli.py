#!/usr/bin/env python3

"""
Repository Management CLI for GitHub MCP Server

Provides command-line interface for managing multi-repository configurations.

Usage:
    python repository_cli.py list
    python repository_cli.py add <name> <path> [--description="..."]
    python repository_cli.py remove <name>
    python repository_cli.py validate
    python repository_cli.py init --example
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

from repository_manager import RepositoryManager, RepositoryConfig


def get_default_config_path() -> Path:
    """Get the default configuration file path"""
    # Priority order:
    # 1. Environment variable
    # 2. Local repositories.json file
    # 3. System location
    
    config_path = os.getenv("GITHUB_AGENT_REPO_CONFIG")
    if config_path:
        return Path(config_path)
    
    # Check for local repositories.json first
    local_config = Path("repositories.json")
    if local_config.exists():
        return local_config
    
    # Fall back to system location
    return Path.home() / ".local" / "share" / "github-agent" / "repositories.json"


def load_or_create_config(config_path: Path) -> Dict[str, Any]:
    """Load existing configuration or create empty structure"""
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading configuration file: {e}")
            sys.exit(1)
    else:
        return {"repositories": {}}


def save_config(config_path: Path, config_data: Dict[str, Any]) -> None:
    """Save configuration to file"""
    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=2)
        print(f"Configuration saved to {config_path}")
    except IOError as e:
        print(f"Error saving configuration: {e}")
        sys.exit(1)


def cmd_list(args):
    """List all configured repositories"""
    config_path = get_default_config_path()
    
    if not config_path.exists():
        print("No configuration file found.")
        print(f"Expected location: {config_path}")
        print("Use 'repository_cli.py init --example' to create a sample configuration.")
        return
    
    manager = RepositoryManager(config_path=str(config_path))
    if manager.load_configuration():
        repositories = manager.list_repositories()
        
        if not repositories:
            print("No repositories configured.")
        else:
            print(f"Configured repositories ({len(repositories)}):")
            print()
            
            for repo_name in repositories:
                repo_info = manager.get_repository_info(repo_name)
                if repo_info:
                    status = "✅" if repo_info["exists"] else "❌"
                    print(f"  {status} {repo_name}")
                    print(f"     Path: {repo_info['path']}")
                    if repo_info["description"]:
                        print(f"     Description: {repo_info['description']}")
                    # Show URL based on whether repository has dedicated port
                    repo_config = manager.get_repository(repo_name)
                    if repo_config and repo_config.port:
                        print(f"     Port: {repo_config.port}")
                        print(f"     URL: http://localhost:{repo_config.port}/mcp/")
                    else:
                        print(f"     URL: http://localhost:8080/mcp/{repo_name}/ (legacy single-port mode)")
                    print()
    else:
        print("Failed to load configuration. Check file format and permissions.")


def cmd_add(args):
    """Add a new repository to configuration"""
    config_path = get_default_config_path()
    config_data = load_or_create_config(config_path)
    
    # Validate repository name
    if not args.name.replace("-", "").replace("_", "").isalnum():
        print(f"Error: Repository name '{args.name}' contains invalid characters.")
        print("Names can only contain letters, numbers, hyphens, and underscores.")
        sys.exit(1)
    
    # Check if repository already exists
    if args.name in config_data["repositories"]:
        print(f"Error: Repository '{args.name}' already exists.")
        print("Use 'repository_cli.py remove' first if you want to replace it.")
        sys.exit(1)
    
    # Validate path
    repo_path = Path(args.path).resolve()
    if not repo_path.exists():
        print(f"Error: Path does not exist: {repo_path}")
        sys.exit(1)
    
    if not repo_path.is_dir():
        print(f"Error: Path is not a directory: {repo_path}")
        sys.exit(1)
    
    # Check if it's a git repository
    if not (repo_path / ".git").exists():
        print(f"Warning: Path does not appear to be a git repository: {repo_path}")
        response = input("Continue anyway? [y/N]: ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            sys.exit(0)
    
    # Add repository to configuration
    config_data["repositories"][args.name] = {
        "path": str(repo_path),
        "description": args.description or ""
    }
    
    save_config(config_path, config_data)
    print(f"Added repository '{args.name}'")
    print(f"  Path: {repo_path}")
    print(f"  URL: http://localhost:8080/mcp/{args.name}/")


def cmd_remove(args):
    """Remove a repository from configuration"""
    config_path = get_default_config_path()
    config_data = load_or_create_config(config_path)
    
    if args.name not in config_data["repositories"]:
        print(f"Error: Repository '{args.name}' not found.")
        print("Use 'repository_cli.py list' to see available repositories.")
        sys.exit(1)
    
    # Show what will be removed
    repo_info = config_data["repositories"][args.name]
    print(f"Will remove repository '{args.name}':")
    print(f"  Path: {repo_info['path']}")
    print(f"  Description: {repo_info.get('description', '(none)')}")
    print()
    
    response = input("Are you sure? [y/N]: ").strip().lower()
    if response != 'y':
        print("Cancelled.")
        sys.exit(0)
    
    # Remove repository
    del config_data["repositories"][args.name]
    save_config(config_path, config_data)
    print(f"Removed repository '{args.name}'")


def cmd_validate(args):
    """Validate repository configuration"""
    config_path = get_default_config_path()
    
    if not config_path.exists():
        print("No configuration file found.")
        print(f"Expected location: {config_path}")
        sys.exit(1)
    
    print(f"Validating configuration: {config_path}")
    print()
    
    manager = RepositoryManager(config_path=str(config_path))
    if manager.load_configuration():
        repositories = manager.list_repositories()
        print(f"✅ Configuration loaded successfully")
        print(f"✅ Found {len(repositories)} repositories")
        
        if manager.is_multi_repo_mode():
            print("✅ Running in multi-repository mode")
        else:
            print("ℹ️  Running in single-repository fallback mode")
        
        print()
        print("Repository validation:")
        
        all_valid = True
        for repo_name in repositories:
            repo_info = manager.get_repository_info(repo_name)
            if repo_info:
                if repo_info["exists"]:
                    print(f"  ✅ {repo_name}: {repo_info['path']}")
                else:
                    print(f"  ❌ {repo_name}: Path does not exist - {repo_info['path']}")
                    all_valid = False
            else:
                print(f"  ❌ {repo_name}: Failed to get repository info")
                all_valid = False
        
        if all_valid:
            print()
            print("🎉 All repositories are valid!")
        else:
            print()
            print("⚠️  Some repositories have issues. Fix them before using the server.")
            sys.exit(1)
    else:
        print("❌ Failed to load configuration")
        print("Check file format and repository paths.")
        sys.exit(1)


def cmd_init(args):
    """Initialize configuration file"""
    config_path = get_default_config_path()
    
    if config_path.exists() and not args.force:
        print(f"Configuration file already exists: {config_path}")
        print("Use --force to overwrite it.")
        sys.exit(1)
    
    if args.example:
        # Create example configuration
        example_config = {
            "repositories": {
                "my-project": {
                    "path": "/Users/yourusername/code/my-project",
                    "description": "Personal project repository"
                },
                "work-repo": {
                    "path": "/Users/yourusername/work/important-project",
                    "description": "Work-related repository"
                }
            }
        }
        
        save_config(config_path, example_config)
        print("Created example configuration.")
        print()
        print("Next steps:")
        print("1. Edit the configuration file to use your actual repository paths")
        print("2. Run 'repository_cli.py validate' to check the configuration")
        print("3. Run 'repository_cli.py list' to see your repositories")
    else:
        # Create empty configuration
        empty_config = {"repositories": {}}
        save_config(config_path, empty_config)
        print("Created empty configuration.")
        print()
        print("Next steps:")
        print("1. Add repositories with 'repository_cli.py add <name> <path>'")
        print("2. Run 'repository_cli.py list' to see your repositories")


def cmd_assign_ports(args):
    """Assign ports to repositories for multi-port architecture"""
    config_path = get_default_config_path()
    config_data = load_or_create_config(config_path)
    
    if not config_data["repositories"]:
        print("No repositories configured.")
        return
    
    # Auto-assign ports starting from 8081
    next_port = args.start_port
    assigned_ports = []
    
    for repo_name, repo_config in config_data["repositories"].items():
        if "port" not in repo_config or repo_config["port"] is None:
            repo_config["port"] = next_port
            assigned_ports.append((repo_name, next_port))
            next_port += 1
    
    if assigned_ports:
        save_config(config_path, config_data)
        print("Assigned ports to repositories:")
        for repo_name, port in assigned_ports:
            print(f"  {repo_name}: port {port} -> http://localhost:{port}/mcp/")
        print(f"\nConfiguration updated in {config_path}")
    else:
        print("All repositories already have ports assigned.")


def update_vscode_settings(repo_path: str, repo_name: str, port: int):
    """Update .vscode/settings.json in a repository with MCP server configuration"""
    try:
        vscode_dir = Path(repo_path) / ".vscode"
        settings_file = vscode_dir / "settings.json"
        
        # Create .vscode directory if it doesn't exist
        vscode_dir.mkdir(exist_ok=True)
        
        # Load existing settings or create new ones
        settings = {}
        if settings_file.exists():
            try:
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
            except (json.JSONDecodeError, IOError):
                print(f"Warning: Could not parse existing {settings_file}, creating new settings")
                settings = {}
        
        # Ensure amp.mcpServers exists
        if "amp.mcpServers" not in settings:
            settings["amp.mcpServers"] = {}
        
        # Add or update the GitHub MCP server configuration
        settings["amp.mcpServers"]["github-mcp-server"] = {
            "url": f"http://localhost:{port}/mcp/"
        }
        
        # Save settings
        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=2)
        
        print(f"  Updated .vscode/settings.json in {repo_name}")
        return True
        
    except Exception as e:
        print(f"  Warning: Could not update .vscode/settings.json in {repo_name}: {e}")
        return False


def cmd_setup_vscode(args):
    """Set up VSCode settings for all configured repositories"""
    config_path = get_default_config_path()
    config_data = load_or_create_config(config_path)
    
    if not config_data["repositories"]:
        print("No repositories configured.")
        return
    
    print("Setting up VSCode MCP server configuration for all repositories...")
    
    success_count = 0
    total_count = len(config_data["repositories"])
    
    for repo_name, repo_config in config_data["repositories"].items():
        repo_path = repo_config.get("path")
        repo_port = repo_config.get("port")
        
        if not repo_path:
            print(f"  Skipping {repo_name}: no path configured")
            continue
            
        if not repo_port:
            print(f"  Skipping {repo_name}: no port assigned (run 'assign-ports' first)")
            continue
            
        if not os.path.exists(repo_path):
            print(f"  Skipping {repo_name}: path does not exist ({repo_path})")
            continue
        
        if update_vscode_settings(repo_path, repo_name, repo_port):
            success_count += 1
    
    print(f"\nVSCode setup complete: {success_count}/{total_count} repositories configured")
    if success_count < total_count:
        print("Some repositories were skipped - check the output above for details")


def cmd_status(args):
    """Show status of master and worker processes"""
    try:
        import subprocess
        import json
        
        # Try to get status from master process
        result = subprocess.run(
            ["python3", "github_mcp_master.py", "status"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            status = json.loads(result.stdout)
            print("GitHub MCP Multi-Port Status:")
            print(f"Master running: {status['master']['running']}")
            print(f"Workers: {status['master']['workers_count']}")
            print()
            
            for repo_name, worker_info in status['workers'].items():
                status_icon = "🟢" if worker_info['running'] else "🔴"
                print(f"{status_icon} {repo_name} (port {worker_info['port']})")
                print(f"   Path: {worker_info['path']}")
                print(f"   Endpoint: {worker_info['endpoint']}")
                if worker_info['running']:
                    print(f"   PID: {worker_info['pid']}")
                    print(f"   Restarts: {worker_info['restart_count']}")
                print()
        else:
            print("Master process not running or not responding.")
            print("Use 'python github_mcp_master.py' to start.")
            
    except Exception as e:
        print(f"Error getting status: {e}")
        print("Make sure the master process is installed and accessible.")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="GitHub MCP Server Repository Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  repository_cli.py list                              # List all repositories
  repository_cli.py add my-proj /path/to/repo         # Add a repository
  repository_cli.py add work /work/repo --description="Work stuff"
  repository_cli.py remove my-proj                    # Remove a repository
  repository_cli.py validate                          # Validate configuration
  repository_cli.py init --example                    # Create example config
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List command
    parser_list = subparsers.add_parser('list', help='List all configured repositories')
    parser_list.set_defaults(func=cmd_list)
    
    # Add command
    parser_add = subparsers.add_parser('add', help='Add a new repository')
    parser_add.add_argument('name', help='Repository name (used in URLs)')
    parser_add.add_argument('path', help='Path to the git repository')
    parser_add.add_argument('--description', help='Description of the repository')
    parser_add.set_defaults(func=cmd_add)
    
    # Remove command
    parser_remove = subparsers.add_parser('remove', help='Remove a repository')
    parser_remove.add_argument('name', help='Repository name to remove')
    parser_remove.set_defaults(func=cmd_remove)
    
    # Validate command
    parser_validate = subparsers.add_parser('validate', help='Validate repository configuration')
    parser_validate.set_defaults(func=cmd_validate)
    
    # Init command
    parser_init = subparsers.add_parser('init', help='Initialize configuration file')
    parser_init.add_argument('--example', action='store_true', help='Create example configuration')
    parser_init.add_argument('--force', action='store_true', help='Overwrite existing configuration')
    parser_init.set_defaults(func=cmd_init)
    
    # Assign ports command
    parser_assign_ports = subparsers.add_parser('assign-ports', help='Assign ports to repositories for multi-port architecture')
    parser_assign_ports.add_argument('--start-port', type=int, default=8081, help='Starting port number (default: 8081)')
    parser_assign_ports.set_defaults(func=cmd_assign_ports)
    
    # Status command
    parser_status = subparsers.add_parser('status', help='Show status of master and worker processes')
    parser_status.set_defaults(func=cmd_status)
    
    # Setup VSCode command
    parser_setup_vscode = subparsers.add_parser('setup-vscode', help='Configure .vscode/settings.json for all repositories')
    parser_setup_vscode.set_defaults(func=cmd_setup_vscode)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    # Execute the command
    args.func(args)


if __name__ == "__main__":
    main()
