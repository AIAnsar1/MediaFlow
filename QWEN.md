# MediaFlow — Project Context

## Project Overview

**MediaFlow** is a multi-platform Telegram bot manager and downloader built with Python 3.12+. It provides a self-hosted solution for managing a network of Telegram Media Downloader bots with a web-based administrative dashboard. Users can send links from platforms like Instagram, TikTok, YouTube, Pinterest, and VK to the Telegram bot and receive downloadable media content.

### Key Features
- **Universal Downloader** — Supports Instagram, TikTok, YouTube, Pinterest, VK, and more (via `yt-dlp` and `gallery-dl`).
- **Multi-Bot Hub** — Manage multiple Telegram bots from a single admin interface.
- **Real-time Metrics** — Dashboard with download stats, user growth, and platform popularity.
- **Broadcast System** — Mass messaging to all bot users.
- **Rate Limiting & Queue System** — Redis-backed async task queue (ARQ) for high-load stability.

### Technology Stack
| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Web Framework | Litestar (ASGI) |
| Bot Framework | aiogram |
| Database | SQLAlchemy 2.0 (PostgreSQL / SQLite) |
| Migrations | Alembic |
| Task Queue | ARQ (Redis) |
| Frontend | Jinja2 + Tailwind CSS |
| Package Manager | uv |
| Linting/Formatting | Ruff |
| Testing | pytest, pytest-asyncio, pytest-cov, pytest-timeout, pytest-xdist |
| Logging | Structlog, Loguru |

## Project Structure

```
MediaFlow/
├── app/                 # Litestar web application
│   ├── controllers/     # Route handlers (API + admin pages)
│   ├── handlers/        # Request processing logic
│   ├── middleware/       # ASGI middleware
│   ├── config.py        # Settings (pydantic-settings)
│   ├── lifecycle.py     # App factory + lifespan
│   └── logging.py       # Structlog configuration
├── bot/                 # Telegram bot (aiogram)
│   ├── keyboards.py     # Inline/reply keyboards
│   └── processor.py     # Message processing
├── database/            # Alembic migrations
│   ├── connection.py    # DB connection management
│   ├── env.py           # Alembic env
│   └── versions/        # Migration files
├── i18n/                # Internationalization files
├── models/              # SQLAlchemy ORM models
├── repositories/        # Data access layer
├── schemas/             # Pydantic DTO schemas
├── services/            # Business logic layer
│   ├── media/           # Media-specific services
│   ├── ad.py            # Broadcast/ad service
│   ├── auth.py          # Admin authentication
│   ├── bot_manager.py   # Multi-bot management
│   ├── cache.py         # Redis cache service
│   ├── downloader.py    # Download orchestration
│   ├── metrics.py       # Stats & metrics
│   └── rate_limiter.py  # Rate limiting
├── workers/             # ARQ background workers
│   ├── tasks.py         # Task definitions
│   ├── worker.py        # Worker settings + cron jobs
│   └── scheduler.py     # Task scheduling
├── storage/             # Runtime storage (logs, temp files)
├── resources/           # Static resources (templates, etc.)
├── scripts/             # Utility scripts
├── tests/               # Test suite (unit, integration, e2e)
├── main.py              # Entry point (server / worker)
├── pyproject.toml       # Dependencies + tool configs
└── alembic.ini          # Alembic configuration
```

## Building & Running

### Prerequisites
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- Redis (for task queue and caching)
- PostgreSQL (optional — SQLite works for development)

### Setup
```bash
# Clone and create virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your settings
```

### Running
```bash
# Start the web server (default)
python main.py
# or explicitly:
python main.py server

# Start the ARQ background worker
python main.py worker
```

The admin panel is available at `http://127.0.0.1:8000/admin`.

### Docker
```bash
docker build -t mediaflow .
docker run -p 8000:8000 --env-file .env mediaflow
```

### Database Migrations
```bash
# Generate a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

## Testing

```bash
# Run all tests
uv run pytest

# Run only unit tests
uv run pytest tests/unit/

# Run integration tests (requires Redis running)
uv run pytest tests/integration/

# Run E2E tests (requires PostgreSQL + Redis)
uv run pytest tests/e2e/

# With coverage
uv run pytest --cov --cov-report=html

# Run tests in parallel
uv run pytest -n auto
```

Test markers: `slow`, `integration`, `e2e`, `performance`

## Linting & Formatting

```bash
# Lint with Ruff
uv run ruff check .

# Format with Ruff
uv run ruff format .
```

Ruff is configured in `pyproject.toml` with line length 320 and ignores for S101 (assert), S104, B008, E501, F401, ANN001.

## Development Conventions

- **Architecture**: Layered architecture — `models` (ORM) → `repositories` (data access) → `services` (business logic) → `controllers` (HTTP handlers) → `schemas` (Pydantic DTOs).
- **Async-first**: The entire codebase is async (Litestar, aiogram, ARQ, asyncpg).
- **Testing**: Tests are split into `unit/`, `integration/`, and `e2e/` directories. pytest-asyncio is in `auto` mode. Use `fakeredis` for unit tests to avoid Redis dependency.
- **Environment**: All configuration is managed through `pydantic-settings` in `app/config.py`. Use `.env.example` as the template.
- **Logging**: Uses Structlog via `app/logging.py`. Get loggers with `get_logger("module_name")`.
- **CI/CD**: GitHub Actions runs unit tests, integration tests (with real Redis), and E2E tests (with PostgreSQL + Redis) on push/PR.

## Key Entry Points

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point — starts Granian server or ARQ worker |
| `app/__init__.py` | Exports the Litestar `app` instance |
| `app/lifecycle.py` | App factory and lifespan management |
| `workers/worker.py` | ARQ WorkerSettings with cron jobs |
| `database/connection.py` | Database session management |
