#!/usr/bin/env python3

"""
Setup script for GitHub MCP Server Multi-Repository Configuration

This script helps you migrate from single-repository setup or configure
multi-repository support from scratch.
"""

import os
import sys
import subprocess
from pathlib import Path


def check_requirements():
    """Check that required dependencies are available"""
    try:
        import repository_manager
        import github_mcp_server
        print("✅ GitHub MCP Server modules found")
        return True
    except ImportError as e:
        print(f"❌ Missing required modules: {e}")
        print("Make sure you're in the correct directory with the server files.")
        return False


def check_github_token():
    """Check if GitHub token is configured"""
    token = os.getenv("GITHUB_TOKEN")
    if token:
        print("✅ GitHub token configured")
        return True
    else:
        print("❌ GITHUB_TOKEN environment variable not set")
        print("Please set your GitHub personal access token:")
        print("export GITHUB_TOKEN='ghp_your_token_here'")
        return False


def detect_existing_repo():
    """Detect if there's an existing LOCAL_REPO_PATH configuration"""
    repo_path = os.getenv("LOCAL_REPO_PATH")
    if repo_path:
        if Path(repo_path).exists():
            print(f"📁 Found existing repository: {repo_path}")
            return repo_path
        else:
            print(f"⚠️  LOCAL_REPO_PATH points to non-existent path: {repo_path}")
    
    return None


def setup_config_directory():
    """Ensure configuration directory exists"""
    config_dir = Path.home() / ".local" / "share" / "github-agent"
    config_dir.mkdir(parents=True, exist_ok=True)
    print(f"📂 Configuration directory: {config_dir}")
    return config_dir


def run_cli_command(args):
    """Run repository CLI command"""
    try:
        result = subprocess.run([sys.executable, "repository_cli.py"] + args, 
                              capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr


def migration_flow():
    """Handle migration from single-repository setup"""
    print("\n🔄 Migration from Single Repository Setup")
    print("=" * 50)
    
    existing_repo = detect_existing_repo()
    if not existing_repo:
        print("No existing LOCAL_REPO_PATH found.")
        return fresh_setup_flow()
    
    print(f"\nMigrating repository: {existing_repo}")
    
    # Ask for repository name
    while True:
        repo_name = input("\nEnter a name for this repository [default]: ").strip()
        if not repo_name:
            repo_name = "default"
        
        if repo_name.replace("-", "").replace("_", "").isalnum():
            break
        else:
            print("Repository name can only contain letters, numbers, hyphens, and underscores.")
    
    # Ask for description
    description = input("Enter a description (optional): ").strip()
    
    # Initialize configuration
    print("\n📝 Creating configuration...")
    success, output = run_cli_command(["init"])
    if not success:
        print(f"❌ Failed to initialize configuration: {output}")
        return False
    
    # Add repository
    add_args = ["add", repo_name, existing_repo]
    if description:
        add_args.extend(["--description", description])
    
    success, output = run_cli_command(add_args)
    if not success:
        print(f"❌ Failed to add repository: {output}")
        return False
    
    print(f"✅ Added repository '{repo_name}'")
    
    # Validate
    success, output = run_cli_command(["validate"])
    if not success:
        print(f"❌ Configuration validation failed: {output}")
        return False
    
    print("✅ Configuration validated successfully")
    
    print(f"\n🎉 Migration complete!")
    print(f"Your repository is now available at: http://localhost:8080/mcp/{repo_name}/")
    print(f"\nNext steps:")
    print(f"1. Remove LOCAL_REPO_PATH from your environment")
    print(f"2. Start the server: python github_mcp_server.py")
    print(f"3. Add more repositories with: python repository_cli.py add <name> <path>")
    
    return True


def fresh_setup_flow():
    """Handle fresh multi-repository setup"""
    print("\n🆕 Fresh Multi-Repository Setup")
    print("=" * 40)
    
    # Check if config already exists
    config_path = Path.home() / ".local" / "share" / "github-agent" / "repositories.json"
    if config_path.exists():
        print("Configuration file already exists.")
        response = input("Do you want to continue and add more repositories? [y/N]: ").strip().lower()
        if response != 'y':
            print("Setup cancelled.")
            return False
    else:
        # Initialize with example
        print("Creating example configuration...")
        success, output = run_cli_command(["init", "--example"])
        if not success:
            print(f"❌ Failed to create configuration: {output}")
            return False
        print("✅ Example configuration created")
    
    print("\nNow let's add your repositories:")
    print("(Press Enter without typing anything to finish)")
    
    while True:
        print()
        repo_name = input("Repository name: ").strip()
        if not repo_name:
            break
        
        if not repo_name.replace("-", "").replace("_", "").isalnum():
            print("Repository name can only contain letters, numbers, hyphens, and underscores.")
            continue
        
        repo_path = input("Repository path: ").strip()
        if not repo_path:
            continue
        
        # Expand home directory
        repo_path = os.path.expanduser(repo_path)
        
        if not Path(repo_path).exists():
            print(f"⚠️  Path does not exist: {repo_path}")
            continue
        
        description = input("Description (optional): ").strip()
        
        # Add repository
        add_args = ["add", repo_name, repo_path]
        if description:
            add_args.extend(["--description", description])
        
        success, output = run_cli_command(add_args)
        if success:
            print(f"✅ Added repository '{repo_name}'")
        else:
            print(f"❌ Failed to add repository: {output}")
    
    # Validate final configuration
    print("\n🔍 Validating configuration...")
    success, output = run_cli_command(["validate"])
    if not success:
        print(f"❌ Configuration validation failed: {output}")
        return False
    
    print("✅ Configuration validated successfully")
    
    # Show summary
    success, output = run_cli_command(["list"])
    if success:
        print("\n📋 Your configured repositories:")
        print(output)
    
    print("🎉 Setup complete!")
    print("\nNext steps:")
    print("1. Start the server: python github_mcp_server.py")
    print("2. Each repository will be available at: http://localhost:8080/mcp/{name}/")
    print("3. Add more repositories anytime with: python repository_cli.py add <name> <path>")
    
    return True


def main():
    """Main setup flow"""
    print("GitHub MCP Server - Multi-Repository Setup")
    print("=" * 45)
    
    # Check requirements
    if not check_requirements():
        sys.exit(1)
    
    if not check_github_token():
        sys.exit(1)
    
    # Set up configuration directory
    setup_config_directory()
    
    # Determine setup type
    existing_repo = detect_existing_repo()
    
    if existing_repo:
        print("\n🔍 Detected existing single-repository setup")
        response = input("Do you want to migrate to multi-repository setup? [Y/n]: ").strip().lower()
        if response in ('', 'y', 'yes'):
            success = migration_flow()
        else:
            print("Setup cancelled. Your existing setup will continue to work.")
            success = True
    else:
        print("\n🔍 No existing repository configuration found")
        response = input("Do you want to set up multi-repository configuration? [Y/n]: ").strip().lower()
        if response in ('', 'y', 'yes'):
            success = fresh_setup_flow()
        else:
            print("Setup cancelled.")
            success = True
    
    if success:
        print("\n" + "=" * 45)
        print("Setup completed successfully!")
        
        # Offer to enable dev mode
        print("\n💡 Development tip:")
        print("Set GITHUB_AGENT_DEV_MODE=true to enable automatic configuration reloading")
        print("This will watch your config file and reload when you add/remove repositories")
    else:
        print("\n❌ Setup failed. Please check the errors above and try again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
