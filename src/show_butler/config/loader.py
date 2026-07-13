"""Configuration loader for Show Butler.

Loads and merges configuration from multiple sources in precedence order:

1. Base configuration (``base.toml``).
2. Environment-specific overrides (``{env}.toml``).
3. Environment variables (for secrets).
"""

import os
import tomllib
from pathlib import Path
from typing import Any, Dict, Optional

from show_butler.exceptions.config import ConfigError, ConfigFileError, EnvironmentError
from show_butler.models.enums import Environment


class ConfigLoader:
    """Loads raw configuration from TOML files and environment variables."""

    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize the loader.

        Args:
            config_dir: Directory containing the TOML config files. Defaults to
                ``configs`` in the project root.
        """
        self.config_dir = self._resolve_config_dir(config_dir)
        self._load_dotenv()
        self._validate_config_directory()

    def _resolve_config_dir(self, config_dir: Optional[Path]) -> Path:
        """Resolve the configuration directory to an absolute path."""
        if config_dir:
            return config_dir.resolve()

        # loader.py -> config -> show_butler -> src -> project root
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent.parent.parent
        return project_root / "configs"

    def _load_dotenv(self) -> None:
        """Load a local ``.env`` file in development only.

        Production is expected to inject secrets via Cloud Run env vars, so we
        never read ``.env`` there. Missing ``python-dotenv`` is tolerated.
        """
        try:
            from dotenv import load_dotenv
        except ImportError:
            return

        current_env = os.getenv("APP_ENV", "").lower()
        if current_env in ("dev", "development", ""):
            load_dotenv()

    def _validate_config_directory(self) -> None:
        """Ensure the config directory and ``base.toml`` exist.

        Raises:
            ConfigError: If the directory is missing.
            ConfigFileError: If ``base.toml`` is missing.
        """
        if not self.config_dir.exists():
            raise ConfigError(
                f"Configuration directory not found: {self.config_dir}",
                config_path=str(self.config_dir),
            )

        base_config = self.config_dir / "base.toml"
        if not base_config.exists():
            raise ConfigFileError(
                f"Base configuration file not found: {base_config}",
                config_path=str(base_config),
            )

    def get_environment(self) -> Environment:
        """Read and validate the current environment from ``APP_ENV``.

        Raises:
            EnvironmentError: If ``APP_ENV`` is unset or invalid.
        """
        env_str = os.getenv("APP_ENV", "").lower()
        if not env_str:
            valid_values = ", ".join([e.value for e in Environment])
            raise EnvironmentError(
                f"APP_ENV environment variable is not set. Valid values: {valid_values}"
            )

        try:
            return Environment.from_string(env_str)
        except ValueError as e:
            raise EnvironmentError(str(e))

    def load_toml_file(self, file_path: Path) -> Dict[str, Any]:
        """Load and parse a single TOML file.

        Raises:
            ConfigFileError: If the file is missing or cannot be parsed.
        """
        try:
            with open(file_path, "rb") as f:
                return tomllib.load(f)
        except FileNotFoundError:
            raise ConfigFileError(
                f"Configuration file not found: {file_path}", config_path=str(file_path)
            )
        except Exception as e:
            raise ConfigFileError(
                f"Failed to parse configuration file {file_path}: {e}",
                config_path=str(file_path),
            )

    def merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge ``override`` on top of ``base``.

        Nested tables merge key by key; scalar and list values are replaced
        wholesale by the override.
        """
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self.merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def load_secrets(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Inject secrets from environment variables into a config dict.

        Only sections that already exist in the merged config are touched, so
        typos in TOML aren't silently masked by env injection.
        """
        config = config.copy()

        agent_tasks = config.get("agent_tasks")
        if isinstance(agent_tasks, dict):
            for agent_config in agent_tasks.values():
                if not isinstance(agent_config, dict):
                    continue
                provider = str(agent_config.get("provider", "")).lower()
                if provider == "google":
                    agent_config["api_key"] = os.getenv("GOOGLE_API_KEY")
                elif provider == "anthropic":
                    agent_config["api_key"] = os.getenv("ANTHROPIC_API_KEY")

        if isinstance(config.get("email"), dict):
            config["email"]["sender_address"] = os.getenv("GMAIL_ADDRESS")
            config["email"]["app_password"] = os.getenv("GMAIL_APP_PASSWORD")

        if isinstance(config.get("gcal"), dict):
            config["gcal"]["client_id"] = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
            config["gcal"]["client_secret"] = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

        if isinstance(config.get("firestore"), dict):
            config["firestore"]["project_id"] = os.getenv("GCP_PROJECT_ID")

        if isinstance(config.get("web"), dict):
            config["web"]["token"] = os.getenv("WEB_UI_TOKEN")

        return config

    def load_raw_config(self) -> Dict[str, Any]:
        """Load the complete raw configuration from all sources.

        Returns:
            The merged base + environment overrides + secrets dictionary.

        Raises:
            ConfigError: If any step of loading fails.
        """
        try:
            env = self.get_environment()

            base_config_path = self.config_dir / "base.toml"
            config = self.load_toml_file(base_config_path)

            env_config_path = self.config_dir / f"{env.value}.toml"
            if env_config_path.exists():
                env_config = self.load_toml_file(env_config_path)
                config = self.merge_configs(config, env_config)
            else:
                raise ConfigFileError(
                    f"Environment configuration file not found: {env_config_path}",
                    config_path=str(env_config_path),
                )

            return self.load_secrets(config)

        except (ConfigError, ConfigFileError, EnvironmentError):
            raise
        except Exception as e:
            raise ConfigError(f"Unexpected error loading configuration: {e}")
