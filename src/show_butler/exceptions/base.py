"""Base exception for Show Butler.

All application-specific exceptions inherit from :class:`ShowButlerError`, so
callers can catch every deliberate error the app raises with a single except
clause while still letting unexpected errors propagate.
"""


class ShowButlerError(Exception):
    """Base class for all Show Butler application errors."""
