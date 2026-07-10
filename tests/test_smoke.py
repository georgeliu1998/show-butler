"""Smoke test verifying the package imports and exposes a version."""

import show_butler


def test_package_has_version() -> None:
    assert show_butler.__version__
