"""Pydantic models for Show Butler configuration.

These models define the structure, defaults, and validation rules for every
configuration section. ``AppConfig`` is the validated root that the rest of the
app consumes. TOML files (``base.toml`` + ``{env}.toml``) populate everything
except secrets, which the loader injects from environment variables.
"""

import os
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from show_butler.models.enums import Environment

# Providers and models supported for the LLM-backed discovery task. The app
# targets Google AI Studio's free tier, so Gemini is the default; the list is
# kept small on purpose and can grow when a new task actually needs it.
_VALID_PROVIDERS: frozenset = frozenset({"google", "anthropic"})

_VALID_MODELS_BY_PROVIDER: Dict[str, set] = {
    "google": {
        "gemini-3.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    },
    "anthropic": {
        "claude-haiku-4-5",
        "claude-sonnet-4-6",
        "claude-opus-4-7",
    },
}


def _is_prod() -> bool:
    """Return whether the app is running in the production environment."""
    return os.getenv("APP_ENV", "").lower() in (Environment.PROD.value, "production")


def _validate_provider_name(v: str) -> str:
    """Validate and normalize an LLM provider name to lowercase."""
    if v.lower() not in _VALID_PROVIDERS:
        raise ValueError(f"Provider must be one of: {', '.join(sorted(_VALID_PROVIDERS))}")
    return v.lower()


def _validate_model_name(v: str, provider: str) -> str:
    """Validate that a model is supported for its provider.

    Test-style model names (prefixed ``test``) bypass the check so fixtures
    don't need to track real model identifiers.
    """
    if v.startswith("test"):
        return v

    provider = provider.lower()
    valid_models = _VALID_MODELS_BY_PROVIDER.get(provider)
    if valid_models and v not in valid_models:
        raise ValueError(
            f"Model '{v}' not supported for provider '{provider}'. "
            f"Valid models: {', '.join(sorted(valid_models))}"
        )
    return v


class _StrictModel(BaseModel):
    """Base for config models that rejects unknown keys.

    Pydantic v2 defaults to ``extra="ignore"``, which would silently drop a
    typo'd TOML key (e.g. ``warning_threshhold``). Forbidding extras turns such
    mistakes into loud validation errors, which is the point of a validated
    config layer.
    """

    model_config = ConfigDict(extra="forbid")


class GeneralConfig(_StrictModel):
    """Application metadata and general settings."""

    name: str = Field(..., description="Application name")
    tagline: str = Field(..., description="Short application tagline")
    version: str = Field(..., description="Application version")
    debug: bool = Field(default=False, description="Enable debug mode")


class LoggingConfig(_StrictModel):
    """Logging configuration settings."""

    level: str = Field(default="INFO", description="Logging level")
    format: str = Field(
        default="%(asctime)s %(name)s [%(levelname)s] %(message)s",
        description="Log message format string",
    )

    @field_validator("level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Normalize and validate the logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {', '.join(sorted(valid_levels))}")
        return v.upper()


class HomeConfig(_StrictModel):
    """The user's home market, used to flag "in town" versus "in state" shows."""

    city: str = Field(..., description="Home city (e.g. Houston)")
    state: str = Field(..., description="Home state (e.g. Texas)")


class ComedianConfig(_StrictModel):
    """A tracked favorite comedian.

    ``aliases`` capture spelling variants and stage names so fuzzy matching can
    recognize the same person across sources. ``priority`` orders recommendations
    when several favorites have shows the same week (higher wins).
    """

    name: str = Field(..., description="Canonical comedian name")
    aliases: List[str] = Field(
        default_factory=list, description="Alternate spellings / stage names"
    )
    priority: int = Field(default=0, ge=0, description="Ranking weight; higher is more important")


class VenueConfig(_StrictModel):
    """A monitored venue and the scraper that knows how to read its site.

    ``scraper_id`` links the venue to a source implementation in ``src/sources``.
    ``home_market`` distinguishes in-town venues from in-state ones so the digest
    can group them.
    """

    name: str = Field(..., description="Venue display name")
    city: str = Field(..., description="Venue city")
    state: str = Field(..., description="Venue state")
    url: str = Field(..., description="Venue shows/calendar page URL")
    scraper_id: str = Field(..., description="Identifier of the source scraper for this venue")
    home_market: bool = Field(
        default=False, description="Whether the venue is in the user's home city"
    )


class ScheduleConfig(_StrictModel):
    """When the weekly check runs (used by Cloud Scheduler wiring)."""

    timezone: str = Field(default="America/Chicago", description="IANA timezone for the schedule")
    cron: str = Field(default="0 9 * * 1", description="Cron expression for the weekly run")


class MatchingConfig(_StrictModel):
    """Fuzzy name-matching thresholds for identifying favorite comedians."""

    fuzzy_threshold: int = Field(
        default=85,
        ge=0,
        le=100,
        description="Minimum rapidfuzz score (0-100) to treat a scraped name as a favorite",
    )


class RecommendationConfig(_StrictModel):
    """Rules for the once-a-year and anti-double-booking recommendation engine."""

    rebook_after_days: int = Field(
        default=365,
        gt=0,
        description="Only recommend a comedian not watched/booked within this many days",
    )


class DiscoveryConfig(_StrictModel):
    """Thresholds for LLM-backed new-comedian discovery.

    The LLM model/provider itself lives under ``agent_tasks.discovery``; this
    section only holds the non-LLM knobs.
    """

    enabled: bool = Field(default=True, description="Toggle weekly new-comedian discovery")
    top_n: int = Field(default=3, gt=0, description="Number of new-comedian suggestions to surface")
    min_score: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (0-1) for a suggestion to be included",
    )


class LLMConfig(_StrictModel):
    """Provider, model, and sampling settings for a single LLM task."""

    provider: str = Field(..., description="LLM provider")
    model: str = Field(..., description="Model identifier")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: int = Field(default=1024, gt=0, description="Maximum tokens to generate")
    api_key: Optional[str] = Field(
        default=None, description="API key for the provider (injected from env var)"
    )

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate that the provider is supported."""
        return _validate_provider_name(v)

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        """Validate that the model is supported for the chosen provider."""
        return _validate_model_name(v, info.data.get("provider", ""))

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: Optional[str], info) -> Optional[str]:  # type: ignore[no-untyped-def]
        """Require an API key in production; leave optional elsewhere.

        In dev the key comes from ``.env`` when actually calling the LLM, so its
        absence should not block loading config for tests or offline work.
        """
        if _is_prod() and not v:
            provider = info.data.get("provider", "unknown")
            raise ValueError(
                f"API key is required for the {provider} provider in production. "
                f"Set {str(provider).upper()}_API_KEY in the environment."
            )
        return v


class AgentTasksConfig(_StrictModel):
    """Per-task LLM configuration.

    Only the discovery task uses an LLM in v1; more tasks can be added here as
    the app grows.
    """

    discovery: LLMConfig = Field(..., description="LLM config for new-comedian discovery")


class RetryConfig(_StrictModel):
    """Same-provider retry/backoff shape for LLM calls."""

    max_attempts: int = Field(
        default=3, ge=1, description="Attempts before giving up on an LLM call"
    )
    wait_exponential_jitter: bool = Field(
        default=True, description="Use exponential backoff with jitter between attempts"
    )


class LLMSettingsConfig(_StrictModel):
    """Global (task-independent) LLM settings."""

    retry: RetryConfig = Field(
        default_factory=RetryConfig, description="Default retry/backoff for LLM calls"
    )


class BudgetConfig(_StrictModel):
    """Yearly ticket-spend budget and the warning threshold for alerts.

    Spend is tracked per calendar year against ``yearly_amount``; an
    approaching-budget alert fires once year-to-date spend crosses
    ``warning_threshold`` (a fraction of the budget).
    """

    yearly_amount: float = Field(..., gt=0, description="Yearly ticket budget")
    currency: str = Field(default="USD", description="ISO 4217 currency code")
    warning_threshold: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        description="Fraction of the budget that triggers an approaching-budget alert",
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Normalize and sanity-check the currency code."""
        v = v.upper()
        if len(v) != 3 or not v.isalpha():
            raise ValueError("Currency must be a 3-letter ISO 4217 code (e.g. USD)")
        return v


class EmailConfig(_StrictModel):
    """Gmail SMTP settings for the weekly digest email.

    ``sender_address`` and ``app_password`` are secrets injected from the
    environment (``GMAIL_ADDRESS`` / ``GMAIL_APP_PASSWORD``); everything else is
    plain config.
    """

    smtp_host: str = Field(default="smtp.gmail.com", description="SMTP server host")
    smtp_port: int = Field(default=587, gt=0, le=65535, description="SMTP server port")
    sender_address: Optional[str] = Field(
        default=None, description="Gmail address to send from (from env var)"
    )
    app_password: Optional[str] = Field(
        default=None, description="Gmail app password (from env var)"
    )
    recipient: Optional[str] = Field(
        default=None,
        description="Address that receives the digest; defaults to the sender (self-digest)",
    )

    @model_validator(mode="after")
    def apply_defaults_and_validate(self) -> "EmailConfig":
        """Default the recipient to the sender and require creds in production."""
        if not self.recipient:
            self.recipient = self.sender_address

        if _is_prod() and not (self.sender_address and self.app_password):
            raise ValueError("GMAIL_ADDRESS and GMAIL_APP_PASSWORD are required in production.")
        return self


class GCalConfig(_StrictModel):
    """Google Calendar OAuth settings for creating invites on booking.

    ``client_id``/``client_secret`` are secrets injected from the environment
    (``GOOGLE_OAUTH_CLIENT_ID`` / ``GOOGLE_OAUTH_CLIENT_SECRET``).
    """

    calendar_id: str = Field(default="primary", description="Target calendar ID")
    token_path: str = Field(default="token.json", description="Path to the cached OAuth user token")
    scopes: List[str] = Field(
        default_factory=lambda: ["https://www.googleapis.com/auth/calendar.events"],
        description="OAuth scopes requested for calendar access",
    )
    client_id: Optional[str] = Field(default=None, description="OAuth client ID (from env var)")
    client_secret: Optional[str] = Field(
        default=None, description="OAuth client secret (from env var)"
    )

    @model_validator(mode="after")
    def validate_secrets(self) -> "GCalConfig":
        """Require OAuth credentials in production, mirroring other secrets."""
        if _is_prod() and not (self.client_id and self.client_secret):
            raise ValueError(
                "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are required in production."
            )
        return self


class FirestoreConfig(_StrictModel):
    """Firestore state backend settings.

    ``project_id`` is injected from ``GCP_PROJECT_ID``. Collection names are
    configurable so dev and prod can be isolated in the same project if desired.
    """

    project_id: Optional[str] = Field(default=None, description="GCP project ID (from env var)")
    database: str = Field(default="(default)", description="Firestore database ID")
    seen_shows_collection: str = Field(
        default="seen_shows", description="Collection of previously seen shows"
    )
    watch_history_collection: str = Field(
        default="watch_history", description="Collection of watch records"
    )
    bookings_collection: str = Field(
        default="bookings", description="Collection of booking records"
    )

    @model_validator(mode="after")
    def validate_project(self) -> "FirestoreConfig":
        """Require a project ID in production, where Firestore is the backend."""
        if _is_prod() and not self.project_id:
            raise ValueError("GCP_PROJECT_ID is required in production.")
        return self


class WebConfig(_StrictModel):
    """Web UI settings.

    ``base_url`` is used to build action links in the digest email; ``token`` is
    a shared secret protecting the UI, injected from ``WEB_UI_TOKEN``.
    """

    base_url: str = Field(
        default="http://localhost:8000", description="Public base URL of the web UI"
    )
    token: Optional[str] = Field(
        default=None, description="Shared access token for the web UI (from env var)"
    )

    @model_validator(mode="after")
    def validate_token(self) -> "WebConfig":
        """Require an access token in production so the UI isn't left open."""
        if _is_prod() and not self.token:
            raise ValueError("WEB_UI_TOKEN is required in production.")
        return self


class AppConfig(_StrictModel):
    """Root configuration model aggregating every section."""

    general: GeneralConfig = Field(..., description="General application configuration")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="Logging settings")
    home: HomeConfig = Field(..., description="Home city/state")
    comedians: List[ComedianConfig] = Field(..., description="Tracked favorite comedians")
    venues: List[VenueConfig] = Field(..., description="Monitored venues")
    schedule: ScheduleConfig = Field(
        default_factory=ScheduleConfig, description="Weekly run schedule"
    )
    matching: MatchingConfig = Field(
        default_factory=MatchingConfig, description="Fuzzy name-matching thresholds"
    )
    recommendation: RecommendationConfig = Field(
        default_factory=RecommendationConfig, description="Recommendation rules"
    )
    discovery: DiscoveryConfig = Field(
        default_factory=DiscoveryConfig, description="New-comedian discovery thresholds"
    )
    agent_tasks: AgentTasksConfig = Field(..., description="Per-task LLM configuration")
    llm: LLMSettingsConfig = Field(
        default_factory=LLMSettingsConfig, description="Global LLM settings"
    )
    budget: BudgetConfig = Field(..., description="Yearly ticket budget")
    email: EmailConfig = Field(..., description="Gmail SMTP digest settings")
    gcal: GCalConfig = Field(default_factory=GCalConfig, description="Google Calendar settings")
    firestore: FirestoreConfig = Field(
        default_factory=FirestoreConfig, description="Firestore state backend settings"
    )
    web: WebConfig = Field(default_factory=WebConfig, description="Web UI settings")
