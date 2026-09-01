"""Configuration package for Show Butler.

Provides layered TOML configuration (``base.toml`` + ``{env}.toml``) with
environment-variable secret injection and Pydantic validation.

Main exports:
- ``config``: lazy-loaded configuration instance for application use.
- ``ConfigManager``: singleton manager for advanced usage and testing.
- ``ConfigLoader``: low-level TOML/secret loader.
- ``AppConfig``: validated root model, useful for type hints.
"""

from show_butler.config.loader import ConfigLoader
from show_butler.config.manager import ConfigManager, config
from show_butler.config.models import AppConfig

__all__ = [
    "config",
    "ConfigManager",
    "ConfigLoader",
    "AppConfig",
]
