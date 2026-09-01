"""High-level configuration management for Show Butler.

Provides a singleton ``ConfigManager`` that loads and validates configuration
into an ``AppConfig``, plus a lazy proxy (``config``) that defers loading until
the first attribute access.
"""

from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from show_butler.config.loader import ConfigLoader
from show_butler.config.models import AppConfig
from show_butler.exceptions.config import ConfigError, ConfigValidationError
from show_butler.utils.singleton import singleton


@singleton
class ConfigManager:
    """Loads, validates, and caches the application configuration."""

    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize the manager.

        Args:
            config_dir: Optional override for the configuration directory.
        """
        self.config_dir = config_dir
        self._config: Optional[AppConfig] = None
        self._loader: Optional[ConfigLoader] = None

    def _get_loader(self) -> ConfigLoader:
        """Return the cached loader, creating it on first use.

        ``config_dir`` only changes via ``__init__`` or ``reload``; both leave
        ``_loader`` unset, so a simple ``is None`` check is sufficient and avoids
        comparing an unresolved ``config_dir`` (often ``None``) against the
        loader's always-resolved absolute path.
        """
        if self._loader is None:
            self._loader = ConfigLoader(config_dir=self.config_dir)
        return self._loader

    def load(self) -> AppConfig:
        """Load and validate configuration, caching the result.

        Raises:
            ConfigValidationError: If validation fails.
            ConfigError: If loading fails for any other reason.
        """
        if self._config is None:
            try:
                loader = self._get_loader()
                raw_config = loader.load_raw_config()
                self._config = AppConfig(**raw_config)
            except ValidationError as e:
                raise ConfigValidationError(f"Configuration validation failed: {e}") from e
            except ConfigError:
                raise
            except Exception as e:
                raise ConfigError(f"Unexpected error during configuration loading: {e}") from e

        return self._config

    def get_config(self) -> AppConfig:
        """Return the validated configuration (alias for :meth:`load`)."""
        return self.load()

    def reload(self, config_dir: Optional[Path] = None) -> AppConfig:
        """Clear the cache and load configuration afresh.

        Args:
            config_dir: Optional new configuration directory.
        """
        if config_dir is not None:
            self.config_dir = config_dir

        self._config = None
        self._loader = None
        return self.load()


class LazyConfigProxy:
    """Lazy-loading proxy so importing the module never triggers a load."""

    def __init__(self) -> None:
        """Initialize the proxy with no configured directory override."""
        self._current_config_dir: Optional[Path] = None

    def _get_manager(self) -> ConfigManager:
        """Return the manager for the current (possibly overridden) directory."""
        if self._current_config_dir is not None:
            return ConfigManager(config_dir=self._current_config_dir)
        return ConfigManager()

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        """Resolve attribute access against the loaded configuration."""
        config = self._get_manager().load()
        return getattr(config, name)

    def reload(self, config_dir: Optional[Path] = None) -> AppConfig:
        """Reload configuration through the proxy.

        Args:
            config_dir: Optional new configuration directory to switch to.
        """
        if config_dir is not None:
            self._current_config_dir = config_dir
            return ConfigManager(config_dir=config_dir).reload(config_dir=config_dir)
        return self._get_manager().reload()


# Global lazy proxy for application-wide use.
config = LazyConfigProxy()
