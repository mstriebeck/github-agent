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
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from git import InvalidGitRepositoryError, Repo

from constants import (
    GITHUB_HTTPS_PREFIX,
    GITHUB_SSH_PREFIX,
    MINIMUM_PYTHON_MAJOR,
    MINIMUM_PYTHON_MINOR,
    MINIMUM_PYTHON_VERSION,
    SUPPORTED_LANGUAGES,
)


@dataclass
class RepositoryConfig:
    """Configuration for a single repository"""

    name: str
    path: str
    description: str
    language: str
    port: int
    python_path: str
    github_owner: str
    github_repo: str

    def __post_init__(self):
        """Validate configuration after initialization - basic validation only"""
        logger = logging.getLogger(__name__)

        logger.debug(f"Validating repository config for '{self.name}'")

        if not self.name:
            raise ValueError("Repository name cannot be empty")
        if not self.path:
            raise ValueError("Repository path cannot be empty")

        # Validate language
        if self.language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{self.language}' for repository '{self.name}'. "
                f"Supported languages: {', '.join(sorted(SUPPORTED_LANGUAGES))}"
            )

        # Require absolute paths
        if not os.path.isabs(self.path):
            raise ValueError(f"Repository path must be absolute, got: {self.path}")

        # Expand user home if needed and normalize
        self.path = os.path.abspath(os.path.expanduser(self.path))

        logger.debug(
            f"Basic validation completed for repository '{self.name}' at {self.path}"
        )

    @classmethod
    def create_repository_config(
        cls,
        name: str,
        path: str,
        description: str,
        language: str,
        port: int,
        python_path: str | None = None,
    ) -> "RepositoryConfig":
        """
        Factory method to create a repository configuration with all required fields initialized.

        Args:
            name: Repository name
            path: Repository path
            description: Repository description
            language: Programming language (defaults to python)
            port: MCP server port (required)
            python_path: Path to Python executable (will be auto-detected if None)

        Returns:
            Fully initialized RepositoryConfig

        Raises:
            ValueError: If validation fails
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Creating repository configuration for '{name}' at {path}")

        # Normalize path first for validation
        normalized_path = os.path.abspath(os.path.expanduser(path))

        # Extract GitHub information
        logger.debug(f"Extracting GitHub information for repository '{name}'")
        github_owner, github_repo = cls._extract_github_info(normalized_path, logger)

        # Validate and get Python path
        if python_path is None:
            logger.debug(f"Auto-detecting Python path for repository '{name}'")
            if language == "python":
                # For Python repos, try to find a suitable Python executable
                python_path = cls._find_python_executable(normalized_path, logger)
            else:
                # For non-Python repos, use system Python
                import sys

                python_path = sys.executable
                logger.debug(
                    f"Using system Python for non-Python repository: {python_path}"
                )

        logger.debug(f"Validating Python path for repository '{name}': {python_path}")
        validated_python_path = cls._validate_python_path(python_path, logger)

        # Port is required - no auto-assignment

        logger.info(
            f"Successfully created repository config for '{name}': "
            f"language={language}, port={port}, python_path={validated_python_path}, "
            f"github={github_owner}/{github_repo if github_owner else 'no-remote'}"
        )

        return cls(
            name=name,
            path=normalized_path,
            description=description,
            language=language,
            port=port,
            python_path=validated_python_path,
            github_owner=github_owner or "unknown",
            github_repo=github_repo or "unknown",
        )

    @staticmethod
    def _extract_github_info(
        repo_path: str, logger: logging.Logger
    ) -> tuple[str | None, str | None]:
        """Extract GitHub owner/repo from git remote origin"""
        try:
            logger.debug(f"Running git config command in {repo_path}")
            cmd = ["git", "config", "--get", "remote.origin.url"]
            output = subprocess.check_output(cmd, cwd=repo_path).decode().strip()

            logger.debug(f"Git remote URL: {output}")

            if not output:
                logger.warning(f"No git remote URL found for {repo_path}")
                return None, None

            if output.startswith(GITHUB_SSH_PREFIX):
                # SSH format: git@github.com:owner/repo.git
                _, path = output.split(":", 1)
                logger.debug(f"Detected SSH format GitHub URL, extracted path: {path}")
            elif GITHUB_HTTPS_PREFIX in output:
                # HTTPS format: https://github.com/owner/repo.git
                path = output.split("github.com/", 1)[-1]
                logger.debug(
                    f"Detected HTTPS format GitHub URL, extracted path: {path}"
                )
            else:
                logger.warning(f"Non-GitHub remote URL detected: {output}")
                return None, None

            # Remove .git suffix if present
            repo_path_clean = path.replace(".git", "")

            # Split into owner/repo
            if "/" not in repo_path_clean:
                logger.error(
                    f"Invalid GitHub repository path format: {repo_path_clean}"
                )
                return None, None

            owner, repo = repo_path_clean.split("/", 1)

            # Remove any additional path components
            if "/" in repo:
                repo = repo.split("/")[0]

            logger.info(f"✅ Successfully extracted GitHub info: {owner}/{repo}")
            return owner, repo

        except subprocess.CalledProcessError as e:
            logger.debug(f"No git remote configured for {repo_path}: {e}")
            return None, None
        except Exception as e:
            logger.warning(f"Failed to extract GitHub info from {repo_path}: {e}")
            return None, None

    @staticmethod
    def _find_python_executable(repo_path: str, logger: logging.Logger) -> str:
        """Find the best Python executable for a repository"""
        logger.debug(f"Searching for Python executable for repository at {repo_path}")

        # Check for virtual environment in the repository
        venv_paths = [
            os.path.join(repo_path, ".venv", "bin", "python"),
            os.path.join(repo_path, "venv", "bin", "python"),
            os.path.join(repo_path, ".env", "bin", "python"),
        ]

        for venv_path in venv_paths:
            if os.path.exists(venv_path) and os.access(venv_path, os.X_OK):
                logger.info(f"✅ Found virtual environment Python: {venv_path}")
                return venv_path

        # Fall back to system Python
        import sys

        system_python = sys.executable
        logger.debug(
            f"No virtual environment found, using system Python: {system_python}"
        )
        return system_python

    @staticmethod
    def _validate_python_path(python_path: str, logger: logging.Logger) -> str:
        """Validate python_path parameter with comprehensive logging"""
        logger.debug(f"Validating Python executable: {python_path}")

        if not isinstance(python_path, str):
            raise ValueError(
                f"python_path must be a string, got {type(python_path).__name__}"
            )

        if not python_path.strip():
            raise ValueError("python_path cannot be empty or whitespace")

        # Expand user home if needed and normalize
        normalized_path = os.path.abspath(os.path.expanduser(python_path.strip()))
        logger.debug(f"Normalized Python path: {normalized_path}")

        # Check if path exists
        if not os.path.exists(normalized_path):
            logger.error(f"❌ Python executable does not exist: {normalized_path}")
            raise ValueError(f"Python executable does not exist: {normalized_path}")

        # Check if it's executable
        if not os.access(normalized_path, os.X_OK):
            logger.error(f"❌ Python path is not executable: {normalized_path}")
            raise ValueError(f"Python path is not executable: {normalized_path}")

        logger.debug(f"Running version check for Python executable: {normalized_path}")

        # Verify it's actually a Python executable by running --version
        try:
            result = subprocess.run(
                [normalized_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.error(
                    f"❌ Python version check failed for {normalized_path}: return code {result.returncode}"
                )
                raise ValueError(
                    f"Python executable failed version check: {normalized_path}"
                )

            # Check if output contains "Python"
            version_output = result.stdout.strip() or result.stderr.strip()
            logger.debug(f"Python version output: {version_output}")

            if not version_output.startswith("Python"):
                logger.error(
                    f"❌ Executable does not appear to be Python: {normalized_path}, output: {version_output}"
                )
                raise ValueError(
                    f"Executable does not appear to be Python (version output: {version_output}): {normalized_path}"
                )

            # Parse and validate Python version
            version_match = re.search(r"Python (\d+)\.(\d+)\.(\d+)", version_output)
            if not version_match:
                logger.error(
                    f"❌ Could not parse Python version from output: {version_output}"
                )
                raise ValueError(
                    f"Could not parse Python version from: {version_output}"
                )

            major, minor, patch = map(int, version_match.groups())
            logger.debug(f"Detected Python version: {major}.{minor}.{patch}")

            if major < MINIMUM_PYTHON_MAJOR or (
                major == MINIMUM_PYTHON_MAJOR and minor < MINIMUM_PYTHON_MINOR
            ):
                logger.error(
                    f"❌ Python version {major}.{minor}.{patch} is below minimum required "
                    f"{MINIMUM_PYTHON_VERSION} for {normalized_path}"
                )
                raise ValueError(
                    f"Python version {major}.{minor}.{patch} is below minimum required "
                    f"{MINIMUM_PYTHON_VERSION}: {normalized_path}"
                )

            logger.info(
                f"✅ Python executable validated: {normalized_path} (version {major}.{minor}.{patch})"
            )

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Python version check timed out for {normalized_path}")
            raise ValueError(
                f"Python executable timed out during version check: {normalized_path}"
            ) from None
        except subprocess.SubprocessError as e:
            logger.error(
                f"❌ Failed to run Python version check for {normalized_path}: {e}"
            )
            raise ValueError(f"Failed to verify Python executable: {e}") from e

        return normalized_path


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
                    f"✅ Successfully loaded {len(self.repositories)} repositories"
                )
                return True
            else:
                self.logger.error(
                    f"❌ Configuration file not found: {self.config_path}"
                )
                return False

        except Exception as e:
            self.logger.error(f"❌ Failed to load repository configuration: {e}")
            return False

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

            self.logger.debug(
                f"Creating repository config for '{name}' from parsed data"
            )

            # Port is required in configuration
            if "port" not in repo_data:
                raise ValueError(f"Repository '{name}' must specify a 'port' field")

            repo_config = RepositoryConfig.create_repository_config(
                name=name,
                path=repo_data["path"],
                description=repo_data.get("description", ""),
                language=repo_data["language"],
                port=repo_data["port"],
                python_path=repo_data.get("python_path"),
            )

            self.repositories[name] = repo_config

    def _validate_repositories(self) -> None:
        """Validate all configured repositories"""
        self.logger.info(f"Validating {len(self.repositories)} repositories")

        # Check for port conflicts first
        self._validate_port_conflicts()

        for name, repo_config in self.repositories.items():
            try:
                self.logger.debug(
                    f"Validating repository '{name}' at {repo_config.path}"
                )

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

                self.logger.info(
                    f"✅ Validated repository '{name}' at {repo_config.path} "
                    f"(GitHub: {repo_config.github_owner}/{repo_config.github_repo}, "
                    f"Python: {repo_config.python_path}, Port: {repo_config.port})"
                )

            except Exception as e:
                self.logger.error(f"❌ Repository '{name}' validation failed: {e}")
                raise

    def _validate_port_conflicts(self) -> None:
        """Validate that no two repositories use the same port"""
        port_to_repo = {}

        for name, repo_config in self.repositories.items():
            port = repo_config.port
            if port in port_to_repo:
                raise ValueError(
                    f"Port conflict: repositories '{port_to_repo[port]}' and '{name}' "
                    f"both configured to use port {port}"
                )
            port_to_repo[port] = name

        self.logger.debug(
            f"✅ No port conflicts found among {len(self.repositories)} repositories"
        )

    def get_repository(self, repo_name: str) -> RepositoryConfig | None:
        """
        Get repository configuration by name

        Args:
            repo_name: Name of the repository

        Returns:
            RepositoryConfig if found, None otherwise
        """
        # Check multi-repo configuration
        if repo_name in self.repositories:
            return self.repositories[repo_name]

        return None

    def list_repositories(self) -> list[str]:
        """
        Get list of all configured repository names

        Returns:
            List of repository names
        """
        return list(self.repositories.keys())

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
            "language": repo_config.language,
            "python_path": repo_config.python_path,
            "github_owner": repo_config.github_owner,
            "github_repo": repo_config.github_repo,
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
            # Copy all provided fields, providing defaults for required fields if missing
            repo_config = {
                "path": repo_info["path"],
                "description": repo_info.get("description", ""),
                "language": repo_info.get("language", "python"),
            }

            # Add new required fields with defaults if not provided
            repo_config["port"] = repo_info.get("port", 8081)  # Default port
            repo_config["python_path"] = repo_info.get(
                "python_path", "/usr/bin/python3"
            )
            repo_config["github_owner"] = repo_info.get("github_owner", "unknown")
            repo_config["github_repo"] = repo_info.get("github_repo", name)

            config_data["repositories"][name] = repo_config

        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write configuration
        with open(self.config_path, "w") as f:
            json.dump(config_data, f, indent=2)

        self.logger.info(f"✅ Created configuration file: {self.config_path}")

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
                        self.logger.info(f"✅ Added repositories: {list(added)}")
                    if removed:
                        self.logger.info(f"❌ Removed repositories: {list(removed)}")

                    # Notify callbacks
                    for callback in self._reload_callbacks:
                        try:
                            callback()
                        except Exception as e:
                            self.logger.error(f"❌ Error in reload callback: {e}")

                    return True
                else:
                    self.logger.error(
                        "❌ Failed to reload configuration, keeping previous version"
                    )
                    # Reset modification time to avoid repeated reload attempts
                    self._last_modified = current_modified

            return False

        except OSError as e:
            self.logger.error(f"❌ Error checking configuration file: {e}")
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
                    self.logger.error(f"❌ Error in config watcher: {e}")
                    time.sleep(check_interval)

        thread = threading.Thread(target=watch_loop, daemon=True)
        thread.start()
        self.logger.info(f"✅ Started watching configuration file: {self.config_path}")


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
