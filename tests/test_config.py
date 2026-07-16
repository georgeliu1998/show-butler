"""Tests for the Show Butler configuration system."""

import shutil
from pathlib import Path

import pytest

from show_butler.config import AppConfig, ConfigLoader, ConfigManager
from show_butler.config import config as config_proxy
from show_butler.config.models import BudgetConfig, EmailConfig, LLMConfig, LoggingConfig
from show_butler.exceptions.config import (
    ConfigFileError,
    ConfigValidationError,
    EnvironmentError,
)

CONFIGS_DIR = Path(__file__).resolve().parents[1] / "configs"

PROD_SECRETS = {
    "GOOGLE_API_KEY": "test-google-key",
    "GMAIL_ADDRESS": "me@gmail.com",
    "GMAIL_APP_PASSWORD": "test-app-password",
    "GOOGLE_OAUTH_CLIENT_ID": "test-client-id",
    "GOOGLE_OAUTH_CLIENT_SECRET": "test-client-secret",
    "GCP_PROJECT_ID": "test-project",
    "WEB_UI_TOKEN": "test-web-token",
}


def _load(config_dir: Path = CONFIGS_DIR) -> AppConfig:
    """Load a fresh, uncached config from the given directory."""
    return ConfigManager(config_dir=config_dir).reload(config_dir=config_dir)


def _clear_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no secret env vars leak in from the host environment."""
    for key in PROD_SECRETS:
        monkeypatch.delenv(key, raising=False)


def _copy_configs(dest: Path) -> None:
    """Copy base.toml + dev.toml into a fresh directory (unique singleton key)."""
    for name in ("base.toml", "dev.toml"):
        shutil.copy(CONFIGS_DIR / name, dest / name)


# --- Loading & merging ---------------------------------------------------------


def test_loads_dev_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)

    cfg = _load()

    assert cfg.general.name == "show-butler"
    assert cfg.home.city == "Houston"
    assert cfg.home.state == "Texas"
    assert len(cfg.comedians) == 8
    assert len(cfg.venues) == 6
    assert cfg.budget.yearly_amount == 500.0
    assert cfg.agent_tasks.discovery.provider == "google"


def test_dev_overrides_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)

    cfg = _load()

    assert cfg.general.debug is True
    assert cfg.logging.level == "DEBUG"


def test_prod_overrides_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    for key, value in PROD_SECRETS.items():
        monkeypatch.setenv(key, value)

    cfg = _load()

    assert cfg.general.debug is False
    assert cfg.logging.level == "INFO"
    assert cfg.web.base_url.startswith("https://")


def test_comedian_aliases_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)

    cfg = _load()

    cheny = next(c for c in cfg.comedians if c.name == "Jason Cheny")
    assert "Jason Cheney" in cheny.aliases


def test_venue_home_market_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)

    cfg = _load()

    home_venues = {v.name for v in cfg.venues if v.home_market}
    assert home_venues == {"Houston Improv", "Punch Line Houston", "The Secret Group"}


# --- Caching contract ----------------------------------------------------------


def test_config_manager_caches_across_construction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reconstructing ConfigManager returns the same cached, non-reloaded config."""
    _copy_configs(tmp_path)
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)

    m1 = ConfigManager(config_dir=tmp_path)
    m2 = ConfigManager(config_dir=tmp_path)
    assert m1 is m2

    c1 = m1.load()
    c2 = ConfigManager(config_dir=tmp_path).load()
    assert c1 is c2


def test_lazy_proxy_caches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The `config` proxy returns the same cached AppConfig across accesses."""
    _copy_configs(tmp_path)
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)

    config_proxy.reload(config_dir=tmp_path)

    assert config_proxy.general is config_proxy.general
    assert config_proxy.home is config_proxy.home


# --- Secret injection ----------------------------------------------------------


def test_secret_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "abc123")
    monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
    monkeypatch.setenv("WEB_UI_TOKEN", "secret-token")

    cfg = _load()

    assert cfg.agent_tasks.discovery.api_key == "abc123"
    assert cfg.firestore.project_id == "my-project"
    assert cfg.web.token == "secret-token"


def test_recipient_defaults_to_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)
    monkeypatch.setenv("GMAIL_ADDRESS", "me@gmail.com")

    cfg = _load()

    assert cfg.email.sender_address == "me@gmail.com"
    assert cfg.email.recipient == "me@gmail.com"


# --- Environment validation ----------------------------------------------------


def test_missing_app_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    _clear_secret_env(monkeypatch)

    with pytest.raises(EnvironmentError):
        _load()


def test_invalid_app_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    _clear_secret_env(monkeypatch)

    with pytest.raises(EnvironmentError):
        _load()


def test_missing_env_toml_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    shutil.copy(CONFIGS_DIR / "base.toml", tmp_path / "base.toml")
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)

    with pytest.raises(ConfigFileError):
        _load(tmp_path)


def test_missing_base_toml_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    _clear_secret_env(monkeypatch)

    with pytest.raises(ConfigFileError):
        ConfigLoader(config_dir=tmp_path)


def test_prod_requires_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    _clear_secret_env(monkeypatch)

    with pytest.raises(ConfigValidationError):
        _load()


# --- Model-level validation ----------------------------------------------------


def test_merge_configs_is_deep() -> None:
    loader = ConfigLoader(config_dir=CONFIGS_DIR)
    merged = loader.merge_configs(
        {"a": {"x": 1, "y": 2}, "b": 1},
        {"a": {"y": 3}, "c": 4},
    )
    assert merged == {"a": {"x": 1, "y": 3}, "b": 1, "c": 4}


def test_budget_currency_normalized() -> None:
    budget = BudgetConfig(yearly_amount=100.0, currency="usd")
    assert budget.currency == "USD"


def test_budget_rejects_bad_currency() -> None:
    with pytest.raises(ValueError):
        BudgetConfig(yearly_amount=100.0, currency="dollars")


def test_logging_level_normalized() -> None:
    assert LoggingConfig(level="debug").level == "DEBUG"


def test_logging_level_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        LoggingConfig(level="verbose")


def test_llm_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        LLMConfig(provider="openai", model="gpt-4")


def test_llm_rejects_unknown_model() -> None:
    with pytest.raises(ValueError):
        LLMConfig(provider="google", model="gemini-1.0-ultra")


def test_llm_allows_test_model_names() -> None:
    cfg = LLMConfig(provider="google", model="test-model")
    assert cfg.model == "test-model"


def test_email_recipient_defaults_without_env() -> None:
    email = EmailConfig(sender_address="a@b.com")
    assert email.recipient == "a@b.com"
