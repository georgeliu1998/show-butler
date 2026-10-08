"""IANA timezone validation shared by config and domain models."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def check_timezone(value: str) -> str:
    """Return ``value`` if it names an IANA timezone, else raise ``ValueError``."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown IANA timezone: '{value}'") from None
    return value
