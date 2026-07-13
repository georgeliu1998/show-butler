"""Thread-safe singleton decorator with reload capability.

Creates one instance per unique set of constructor arguments, and adds a
``reload_singleton`` method so tests can force a fresh instance without
leaking state across cases.
"""

import threading
from typing import Any, Dict, TypeVar

T = TypeVar("T")


def singleton(cls: type[T]) -> type[T]:
    """Make a class a per-arguments singleton.

    Instances are keyed by their constructor arguments, so callers passing the
    same arguments share one instance while different arguments get distinct
    instances. A ``reload_singleton`` method is attached for testing.

    Args:
        cls: The class to wrap.

    Returns:
        The same class, with singleton behavior installed.
    """
    instances: Dict[tuple, Any] = {}
    lock = threading.Lock()

    def _make_key(*args: Any, **kwargs: Any) -> tuple:
        """Build a hashable key from constructor arguments."""
        kwargs_items = tuple(sorted(kwargs.items()))
        return (args, kwargs_items)

    def __new__(cls_ref: type, *args: Any, **kwargs: Any) -> Any:
        """Return the cached instance for these arguments, creating if needed."""
        _reload = kwargs.pop("_singleton_reload", False)
        key = _make_key(*args, **kwargs)

        if key not in instances or _reload:
            with lock:
                if key not in instances or _reload:
                    instance = object.__new__(cls)
                    instances[key] = instance

        return instances[key]

    def reload_singleton(self: Any, *args: Any, **kwargs: Any) -> Any:
        """Create and cache a fresh instance, replacing any existing one.

        With no arguments, reuses the arguments that created ``self`` (when
        known). Primarily intended for resetting state between tests.
        """
        if not args and not kwargs and hasattr(self, "_singleton_key"):
            original_args, original_kwargs_items = self._singleton_key
            kwargs = dict(original_kwargs_items)
            args = original_args

        reload_kwargs = kwargs.copy()
        reload_kwargs["_singleton_reload"] = True

        new_instance: Any = cls.__new__(cls, *args, **reload_kwargs)
        type(new_instance).__init__(new_instance, *args, **kwargs)
        new_instance._singleton_key = _make_key(*args, **kwargs)

        return new_instance

    cls.__new__ = __new__  # type: ignore[assignment]
    cls.reload_singleton = reload_singleton  # type: ignore[attr-defined]

    return cls
