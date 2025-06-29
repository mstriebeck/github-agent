#!/usr/bin/env python3

"""
Repository Manager for Multi-Repository GitHub MCP Server

Handles loading, validating, and managing multiple repository configurations
for the GitHub MCP server's URL-based routing system.
"""

import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from git import InvalidGitRepositoryError, Repo


@dataclass
class RepositoryConfig:
    """Configuration for a single repository"""

    name: str
    path: str
    description: str
    language: str
    port: int | None = None

    def __post_init__(self):
        """Validate configuration after initialization"""
        if not self.name:
            raise ValueError("Repository name cannot be empty")
        if not self.path:
            raise ValueError("Repository path cannot be empty")

        # Validate language
        supported_languages = {"python", "swift"}
        if self.language not in supported_languages:
            raise ValueError(
                f"Unsupported language '{self.language}' for repository '{self.name}'. "
                f"Supported languages: {', '.join(sorted(supported_languages))}"
            )

        # Require absolute paths
        if not os.path.isabs(self.path):
            raise ValueError(f"Repository path must be absolute, got: {self.path}")

        # Expand user home if needed and normalize
        self.path = os.path.abspath(os.path.expanduser(self.path))


class RepositoryManager:
    """Manages multiple repository configurations for the MCP server"""

    def __init__(self, config_path: str | None = None):
        """
        Initialize repository manager

        Args:
            config_path: Path to repositories.json config file.
                        Defaults to ~/.local/share/github-agent/repositories.json
        """
        self.logger = logging.getLogger(__name__)

        # Determine config file path
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Check environment variable first
            env_config = os.getenv("GITHUB_AGENT_REPO_CONFIG")
            if env_config:
                self.config_path = Path(env_config)
            else:
                # Default location
                self.config_path = (
                    Path.home()
                    / ".local"
                    / "share"
                    / "github-agent"
                    / "repositories.json"
                )

        self.repositories: dict[str, RepositoryConfig] = {}
        self._fallback_repo: RepositoryConfig | None = None

        # Hot reload support
        self._last_modified: float | None = None
        self._reload_callbacks: list[Callable[[], None]] = []

    def load_configuration(self) -> bool:
        """
        Load repository configuration from file

        Returns:
            True if configuration loaded successfully, False otherwise
        """
        try:
            # Try to load configuration file
            if self.config_path.exists():
                self.logger.info(
                    f"Loading repository configuration from {self.config_path}"
                )
                with open(self.config_path) as f:
                    config_data = json.load(f)

                self._parse_configuration(config_data)
                self._validate_repositories()
                self.logger.info(
                    f"Successfully loaded {len(self.repositories)} repositories"
                )
                return True
            else:
                # Try fallback to single repository mode
                self.logger.info(
                    "No multi-repo config found, attempting single-repo fallback"
                )
                return self._load_fallback_configuration()

        except Exception as e:
            self.logger.error(f"Failed to load repository configuration: {e}")
            # Try fallback mode
            return self._load_fallback_configuration()

    def _parse_configuration(self, config_data: dict) -> None:
        """Parse configuration data into repository objects"""
        if "repositories" not in config_data:
            raise ValueError("Configuration must contain 'repositories' key")

        repositories_data = config_data["repositories"]
        if not isinstance(repositories_data, dict):
            raise ValueError("'repositories' must be a dictionary")

        self.repositories = {}
        for name, repo_data in repositories_data.items():
            if not isinstance(repo_data, dict):
                raise ValueError(
                    f"Repository '{name}' configuration must be a dictionary"
                )

            required_fields = ["path", "language"]
            for field in required_fields:
                if field not in repo_data:
                    raise ValueError(
                        f"Repository '{name}' missing required field: {field}"
                    )

            repo_config = RepositoryConfig(
                name=name,
                path=repo_data["path"],
                description=repo_data.get("description", ""),
                port=repo_data.get("port"),
                language=repo_data["language"],
            )

            self.repositories[name] = repo_config

    def _validate_repositories(self) -> None:
        """Validate all configured repositories"""
        for name, repo_config in self.repositories.items():
            try:
                # Check if path exists
                if not os.path.exists(repo_config.path):
                    raise ValueError(
                        f"Repository path does not exist: {repo_config.path}"
                    )

                # Check if it's a git repository
                try:
                    Repo(repo_config.path)
                except InvalidGitRepositoryError:
                    raise ValueError(
                        f"Path is not a git repository: {repo_config.path}"
                    ) from None

                # Check read permissions
                if not os.access(repo_config.path, os.R_OK):
                    raise ValueError(
                        f"No read access to repository: {repo_config.path}"
                    )

                self.logger.debug(
                    f"Validated repository '{name}' at {repo_config.path}"
                )

            except Exception as e:
                self.logger.error(f"Repository '{name}' validation failed: {e}")
                raise

    def _load_fallback_configuration(self) -> bool:
        """
        Load fallback configuration from LOCAL_REPO_PATH environment variable
        for backward compatibility
        """
        repo_path = os.getenv("LOCAL_REPO_PATH")
        if not repo_path:
            self.logger.error(
                "No repository configuration found and LOCAL_REPO_PATH not set"
            )
            return False

        try:
            # Create single repository configuration
            repo_config = RepositoryConfig(
                name="default",
                path=repo_path,
                description="Default repository from LOCAL_REPO_PATH",
                language="swift",
            )

            # Validate the repository
            if not os.path.exists(repo_config.path):
                raise ValueError(f"Repository path does not exist: {repo_config.path}")

            try:
                Repo(repo_config.path)
            except InvalidGitRepositoryError:
                raise ValueError(
                    f"Path is not a git repository: {repo_config.path}"
                ) from None

            self._fallback_repo = repo_config
            self.logger.info(
                f"Using fallback single repository mode: {repo_config.path}"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to configure fallback repository: {e}")
            return False

    def get_repository(self, repo_name: str) -> RepositoryConfig | None:
        """
        Get repository configuration by name

        Args:
            repo_name: Name of the repository

        Returns:
            RepositoryConfig if found, None otherwise
        """
        # Check multi-repo configuration first
        if repo_name in self.repositories:
            return self.repositories[repo_name]

        # Check fallback single repo mode
        if self._fallback_repo and repo_name == "default":
            return self._fallback_repo

        return None

    def list_repositories(self) -> list[str]:
        """
        Get list of all configured repository names

        Returns:
            List of repository names
        """
        if self.repositories:
            return list(self.repositories.keys())
        elif self._fallback_repo:
            return ["default"]
        else:
            return []

    def get_repository_info(self, repo_name: str) -> dict | None:
        """
        Get repository information dictionary

        Args:
            repo_name: Name of the repository

        Returns:
            Dictionary with repository info or None if not found
        """
        repo_config = self.get_repository(repo_name)
        if not repo_config:
            return None

        return {
            "name": repo_config.name,
            "path": repo_config.path,
            "description": repo_config.description,
            "port": repo_config.port,
            "exists": os.path.exists(repo_config.path),
        }

    def is_multi_repo_mode(self) -> bool:
        """Check if running in multi-repository mode"""
        return bool(self.repositories)

    def create_default_config(self, repo_configs: list[dict]) -> None:
        """
        Create a default configuration file

        Args:
            repo_configs: List of repository configuration dictionaries
                         Each should have 'name', 'path', and optional 'description'
        """
        config_data: dict[str, dict[str, dict[str, str]]] = {"repositories": {}}

        for repo_info in repo_configs:
            name = repo_info["name"]
            config_data["repositories"][name] = {
                "path": repo_info["path"],
                "description": repo_info.get("description", ""),
            }

        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write configuration
        with open(self.config_path, "w") as f:
            json.dump(config_data, f, indent=2)

        self.logger.info(f"Created configuration file: {self.config_path}")

    def add_reload_callback(self, callback: Callable[[], None]) -> None:
        """
        Add a callback function to be called when configuration is reloaded

        Args:
            callback: Function to call when configuration changes
        """
        self._reload_callbacks.append(callback)

    def check_for_config_changes(self) -> bool:
        """
        Check if configuration file has been modified and reload if necessary

        Returns:
            True if configuration was reloaded, False otherwise
        """
        if not self.config_path.exists():
            return False

        try:
            current_modified = self.config_path.stat().st_mtime

            # Initialize on first check
            if self._last_modified is None:
                self._last_modified = current_modified
                return False

            # Check if file was modified
            if current_modified > self._last_modified:
                self.logger.info(
                    f"Configuration file changed, reloading: {self.config_path}"
                )

                # Attempt to reload
                old_repos = (
                    set(self.repositories.keys()) if self.repositories else set()
                )

                if self.load_configuration():
                    self._last_modified = current_modified

                    new_repos = (
                        set(self.repositories.keys()) if self.repositories else set()
                    )
                    added = new_repos - old_repos
                    removed = old_repos - new_repos

                    if added:
                        self.logger.info(f"Added repositories: {list(added)}")
                    if removed:
                        self.logger.info(f"Removed repositories: {list(removed)}")

                    # Notify callbacks
                    for callback in self._reload_callbacks:
                        try:
                            callback()
                        except Exception as e:
                            self.logger.error(f"Error in reload callback: {e}")

                    return True
                else:
                    self.logger.error(
                        "Failed to reload configuration, keeping previous version"
                    )
                    # Reset modification time to avoid repeated reload attempts
                    self._last_modified = current_modified

            return False

        except OSError as e:
            self.logger.error(f"Error checking configuration file: {e}")
            return False

    def start_watching_config(self, check_interval: float = 1.0) -> None:
        """
        Start watching configuration file for changes (for development/testing)

        Args:
            check_interval: How often to check for changes in seconds
        """

        def watch_loop():
            while True:
                try:
                    self.check_for_config_changes()
                    time.sleep(check_interval)
                except Exception as e:
                    self.logger.error(f"Error in config watcher: {e}")
                    time.sleep(check_interval)

        thread = threading.Thread(target=watch_loop, daemon=True)
        thread.start()
        self.logger.info(f"Started watching configuration file: {self.config_path}")


def extract_repo_name_from_url(url_path: str) -> str | None:
    """
    Extract repository name from URL path

    Args:
        url_path: URL path like '/mcp/my-project/' or '/mcp/work-stuff'

    Returns:
        Repository name if valid format, None otherwise
    """
    # Remove leading/trailing slashes and split
    path_parts = url_path.strip("/").split("/")

    # Expected format: ['mcp', 'repo-name', ...]
    if len(path_parts) >= 2 and path_parts[0] == "mcp":
        return path_parts[1]

    return None


def validate_repo_name(repo_name: str) -> bool:
    """
    Validate repository name format

    Args:
        repo_name: Repository name to validate

    Returns:
        True if valid, False otherwise
    """
    if not repo_name:
        return False

    # Basic validation - alphanumeric, hyphens, underscores
    pattern = r"^[a-zA-Z0-9_-]+$"
    return bool(re.match(pattern, repo_name))
