"""Thread-safe singleton decorator.

Creates one instance per unique set of constructor arguments. The wrapped
class's ``__init__`` runs only once per cached instance, so repeated
construction with the same arguments returns the already-initialized object
without resetting its state.
"""

import threading
from typing import Any, Callable, Dict, TypeVar

T = TypeVar("T")


def singleton(cls: type[T]) -> type[T]:
    """Make a class a per-arguments singleton.

    Instances are keyed by their constructor arguments, so callers passing the
    same arguments share one instance while different arguments get distinct
    instances. The original ``__init__`` runs only the first time an instance is
    created for a given key; later constructions return the cached, already
    initialized instance untouched (Python otherwise re-runs ``__init__`` on
    whatever ``__new__`` returns, which would wipe cached state).

    Args:
        cls: The class to wrap.

    Returns:
        The same class, with singleton behavior installed.
    """
    instances: Dict[tuple, Any] = {}
    lock = threading.Lock()
    original_init: Callable[..., None] = cls.__init__

    def _make_key(args: tuple, kwargs: dict) -> tuple:
        """Build a hashable key from constructor arguments."""
        return (args, tuple(sorted(kwargs.items())))

    def __new__(cls_ref: type, *args: Any, **kwargs: Any) -> Any:
        """Return the cached instance for these arguments, creating if needed."""
        key = _make_key(args, kwargs)
        instance = instances.get(key)
        if instance is None:
            with lock:
                instance = instances.get(key)
                if instance is None:
                    instance = object.__new__(cls_ref)
                    instances[key] = instance
        return instance

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        """Run the wrapped ``__init__`` only once per cached instance."""
        if getattr(self, "_singleton_initialized", False):
            return
        original_init(self, *args, **kwargs)
        self._singleton_initialized = True

    cls.__new__ = __new__  # type: ignore[assignment]
    cls.__init__ = __init__  # type: ignore[assignment]

    return cls
