"""Configuration-related exceptions.

Covers configuration loading, merging, and validation: missing files or
directories, unparseable TOML, unset or invalid ``APP_ENV``, and Pydantic
validation failures.
"""

from typing import Optional

from show_butler.exceptions.base import ShowButlerError


class ConfigError(ShowButlerError):
    """Base exception for configuration-related errors."""

    def __init__(self, message: str, config_path: Optional[str] = None):
        """Initialize the error, optionally recording the offending path.

        Args:
            message: Human-readable error description.
            config_path: Path to the problematic config file or directory.
        """
        super().__init__(message)
        self.config_path = config_path


class ConfigFileError(ConfigError):
    """Raised when a configuration file cannot be found or parsed."""


class ConfigValidationError(ConfigError):
    """Raised when configuration fails Pydantic validation."""


class InvalidEnvironmentError(ConfigError):
    """Raised when the ``APP_ENV`` variable is unset or invalid.

    Named to avoid shadowing the built-in ``EnvironmentError`` (an alias of
    ``OSError``).
    """
