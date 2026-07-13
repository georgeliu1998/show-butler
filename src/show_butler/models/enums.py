"""Shared enums for Show Butler."""

from enum import Enum


class Environment(Enum):
    """Application deployment environments.

    ``APP_ENV`` selects which ``{env}.toml`` overlay is merged on top of
    ``base.toml`` and how strictly secrets are validated (see the config
    models).
    """

    DEV = "dev"
    PROD = "prod"

    @property
    def full_name(self) -> str:
        """Return the long-form name for the environment."""
        mapping = {
            self.DEV: "development",
            self.PROD: "production",
        }
        return mapping[self]

    @classmethod
    def from_string(cls, env_str: str) -> "Environment":
        """Create an ``Environment`` from a short or full-form string.

        Args:
            env_str: One of ``dev``/``development`` or ``prod``/``production``
                (case-insensitive, surrounding whitespace ignored).

        Raises:
            ValueError: If the string does not name a known environment.
        """
        env_str = env_str.lower().strip()

        for env in cls:
            if env.value == env_str:
                return env

        full_form_mapping = {
            "development": cls.DEV,
            "production": cls.PROD,
        }
        if env_str in full_form_mapping:
            return full_form_mapping[env_str]

        valid_values = ", ".join([e.value for e in cls])
        raise ValueError(f"Invalid environment: '{env_str}'. Valid values: {valid_values}")
