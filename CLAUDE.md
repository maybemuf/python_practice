# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                              # install deps (dev group included)
uv run fastapi dev app/main.py       # run dev server (needs Postgres up + migrations applied)
uv run ruff check .                  # lint (must pass in CI)
uv run ruff check --fix .            # autofix lint
uv run pytest -q                     # full test suite
uv run pytest tests/test_text_service.py::test_pdf_dispatch   # single test
docker compose up -d db              # start Postgres (pgvector image)
uv run alembic upgrade head          # apply migrations
uv run alembic revision --autogenerate -m "msg"   # new migration
```

CI (`.github/workflows/ci.yml`) runs ruff then pytest on every PR. `libmagic1` is a system dependency of `python-magic`.

## Architecture

Layered FastAPI app: **routers are thin** (input parsing + one service call), **services hold all business logic** (no HTTP types), **models** are SQLModel tables + Pydantic DTOs + exceptions. Python 3.13, SQLModel/SQLAlchemy, Alembic, PostgreSQL (pgvector), managed with `uv`.

### Unified error handling
Every error is an `ApiException` subclass (`app/models/exceptions.py`) carrying a `status_code` and a machine-readable `type` (an `ApiExceptionType` enum). Global handlers in `app/main.py` convert them — plus FastAPI's 422 validation errors — into one JSON shape `{message, type, body}`. **Clients switch on `type`, never on `message`.** Raise these typed exceptions from services rather than `HTTPException`. Document a route's error statuses with `error_responses(401, 404, ...)` on the `responses=` param.

### Auth (`app/services/auth_service.py`)
JWT access tokens + rotating refresh tokens. Refresh rotation has **reuse detection**: presenting an already-revoked refresh token is treated as theft and revokes all of the user's tokens. OTP codes (email verification, password reset) are stored hashed (HMAC + `OTP_PEPPER`) with an attempt limit. Registration and password reset are **anti-enumeration** — they never reveal whether an account exists. DI chain for protected routes: `UserDep` (decodes JWT → loads user) → `VerifiedUserDep` (requires verified email).

### File storage (`app/services/storage/`)
`Storage` is a `Protocol`; `LocalStorage` is the only impl (swap for S3 without touching callers). Uploads detect type from **magic bytes, not the client Content-Type**, enforce `MAX_UPLOAD_SIZE` via streaming `MeteredReader`, guard against path traversal, and are isolated per owner (`users/<owner_id>/<file_id>.<ext>`). Owner-scoping is enforced in `get_user_file_obj` — someone else's file returns 404, not 403.

### Document/RAG pipeline (in progress)
Building retrieval-augmented generation over uploaded files:
- `app/services/text_service.py` — `extract_text(bytes, content_type) -> str`: text/csv decode, PDF via `pypdf`, office docs via `pdf_service.convert_to_pdf` (headless LibreOffice → PDF → pypdf). No OCR for images.
- `app/models/document_chunk.py` — `DocumentChunk` table with a pgvector `embedding` column (`EMBEDDING_DIM = 384`); query and stored-chunk vector dimensions must match. Cascade-deletes with its file/owner. Cosine distance operator `<=>` for search, scoped by `owner_id`.

## Conventions

- **Migrations**: models must be imported in `app/models/__init__.py` so they register in `SQLModel.metadata` (autogenerate reads it via `import app.models` in `alembic/env.py`). Constraint names follow the `naming_convention` set in `app/dependencies/session.py`. Never hand-edit files under `alembic/versions/` (ruff excludes them).
- **Tests** run on **in-memory SQLite** (`conftest.py` overrides `get_session`), so no Postgres is needed for the suite — but pgvector-specific SQL won't run there. Fixtures: `session`, `client`, `test_user`, `auth_headers`. Test env vars are set in `conftest.py` before `app.settings` imports. No `pytest-asyncio` — drive async code with `asyncio.run(...)`.
- **Settings** (`app/settings.py`) load from `.env`; required secrets (`JWT_SECRET`, `OTP_PEPPER`, `ANTHROPIC_API_KEY`, Postgres creds, `DEFAULT_ANTHROPIC_MODEL`) have no defaults and fail fast if missing.
- ruff line length 100; enabled rule sets: `E`, `F`, `I` (isort), `UP` (pyupgrade), `B` (bugbear).
