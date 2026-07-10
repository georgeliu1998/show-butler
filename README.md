# Show Butler

Personal app that tracks standup comedy shows for your favorite comedians in Houston / Texas,
emails you a weekly digest of new shows, prevents double-booking, and helps you book shows and
add them to Google Calendar. The name is intentionally generic so it can grow into a general
live-entertainment tracker later; v1 scope stays comedy-only.

## Features (planned)

- Weekly scrape of Houston/Texas comedy venues and favorite comedians' tour pages.
- Fuzzy name matching to your favorite comedians with stable dedupe against previously seen shows.
- Weekly digest email with once-a-year booking recommendations and anti-double-booking alerts.
- LLM-powered discovery of new comedians similar to your taste, from acts playing monitored venues.
- Year-to-date budget tracking against a configurable yearly budget.
- Small web UI to view the comedy calendar, mark shows watched/booked, and create Calendar invites.

Runs on Google Cloud (Cloud Run + Cloud Scheduler + Firestore), sized to stay within free tiers.

## Quick Start

### Prerequisites

- **Python 3.13+** (managed by uv)
- **uv** package manager ([installation guide](https://docs.astral.sh/uv/getting-started/installation/))

### Installation

```bash
git clone <repo-url>
cd show-butler
uv sync --extra dev
```

### Environment variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

## Development

```bash
# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=src/show_butler

# Lint, sort imports, and format
uv run ruff check --fix .
uv run ruff format .

# Type checking
uv run mypy src
```

## Project Structure

```
show-butler/
├── src/show_butler/    # Application package
├── tests/              # Test suite
├── pyproject.toml      # Project metadata, dependencies, tooling config
└── .env.example        # Template for local environment variables
```
