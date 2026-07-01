# Practice API

A REST API built with **FastAPI**, featuring full authentication and file storage.
A learning project done with production-grade patterns.

## Features

- **JWT authentication** (access + refresh tokens).
- **Refresh-token rotation with reuse detection** — reusing a revoked token is
  treated as theft and revokes all of the user's tokens.
- **OTP flows** for email verification and password reset; codes are stored
  hashed (HMAC + pepper), with an attempt limit (anti-bruteforce).
- **Anti-enumeration** — registration/password reset don't reveal whether an
  account exists.
- **File storage**: type validation by magic bytes (not the client's
  `Content-Type`), size limit with streaming, path-traversal protection, and
  per-owner file isolation.
- **Unified error format** with a machine-readable `type` field (see below).
- Storage sits behind a `Protocol`, so local storage is easy to swap for S3.

## Stack

Python 3.13 · FastAPI · SQLModel (SQLAlchemy) · Alembic · PostgreSQL · pwdlib (argon2)
· PyJWT · pytest · ruff · uv.

## Architecture

Layered structure — thin routers, business logic in services:

```
app/
  main.py              # app, global exception handlers, /health
  settings.py          # config (pydantic-settings)
  routers/             # HTTP layer: only input parsing + service call
    auth.py  users.py  files.py
  services/            # business logic (no HTTP)
    auth_service.py    # register/login/rotate/reset/verify, token & OTP handling
    storage/           # Protocol + LocalStorage + MeteredReader
  dependencies/        # FastAPI DI: session, current_user, oauth2, logger
  models/              # SQLModel tables + Pydantic schemas (DTOs) + exceptions
```

## Running

```bash
# 1. Dependencies (uv)
uv sync

# 2. Config
cp .env.example .env        # generate secrets: openssl rand -hex 32

# 3. Start Postgres
docker compose up -d db

# 4. Migrations
uv run alembic upgrade head

# 5. Server
uv run fastapi dev app/main.py
```

Swagger UI: http://localhost:8000/docs · health check: `GET /health`.

Fully in Docker (API + DB): `docker compose up --build`.

## Tests and lint

```bash
uv run pytest        # 117 tests
uv run ruff check .  # lint
```

## Error format

Every error (including 422 validation) has a single shape — switch on `type`,
not on `message`:

```json
{
  "message": "Incorrect email or password",
  "type": "invalid-credentials",
  "body": null
}
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | register + issue tokens |
| POST | `/auth/login` | login (OAuth2 form-data) |
| POST | `/auth/refresh` | rotate refresh token |
| POST | `/auth/change-password` | change password (auth) |
| POST | `/auth/request-reset-password` | request a password-reset OTP |
| POST | `/auth/reset-password` | reset password via OTP |
| POST | `/auth/request-verify-email` | request an email-verification OTP (auth) |
| POST | `/auth/verify-email` | verify email via OTP (auth) |
| GET | `/users/me` | current user's profile |
| POST | `/files` | upload a file (verified) |
| GET | `/files` | list files with pagination |
| GET | `/files/{id}` | download content |
| GET | `/files/{id}/metadata` | file metadata |
| DELETE | `/files/{id}` | delete a file |

## Known limitations

- Email sending is not implemented — OTP codes are only logged (`logger.debug`).
  For real use, plug an email provider into `auth_service`.
