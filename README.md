# Practice API

REST API на **FastAPI** з повноцінною автентифікацією та файловим сховищем.
Навчальний проєкт, зроблений на продакшн-патернах.

## Можливості

- **JWT-автентифікація** (access + refresh токени).
- **Refresh-token rotation з reuse detection** — повторне використання відкликаного
  токена трактується як крадіжка й гасить усі токени користувача.
- **OTP-флоу** для верифікації email та скидання пароля; коди зберігаються
  захешованими (HMAC + pepper), з лімітом спроб (антибрутфорс).
- **Anti-enumeration** — реєстрація/скидання пароля не розкривають, чи існує акаунт.
- **Файлове сховище**: валідація типу по magic-байтах (не по клієнтському
  `Content-Type`), ліміт розміру зі стрімінгом, захист від path traversal,
  ізоляція файлів по власнику.
- **Єдиний формат помилок** з машиночитним полем `type` (див. нижче).
- Storage — за протоколом (`Protocol`), тож локальне сховище легко замінити на S3.

## Стек

Python 3.13 · FastAPI · SQLModel (SQLAlchemy) · Alembic · PostgreSQL · pwdlib (argon2)
· PyJWT · pytest · ruff · uv.

## Архітектура

Шарова структура — роутери тонкі, бізнес-логіка в сервісах:

```
app/
  main.py              # app, глобальні обробники помилок, /health
  settings.py          # конфіг (pydantic-settings)
  routers/             # HTTP-шар: тільки парсинг вводу + виклик сервісу
    auth.py  users.py  files.py
  services/            # бізнес-логіка (без HTTP)
    auth_service.py    # register/login/rotate/reset/verify, робота з токенами й OTP
    storage/           # Protocol + LocalStorage + MeteredReader
  dependencies/        # FastAPI DI: session, current_user, oauth2, logger
  models/              # SQLModel-таблиці + Pydantic-схеми (DTO) + винятки
```

## Запуск

```bash
# 1. Залежності (uv)
uv sync

# 2. Конфіг
cp .env.example .env        # згенеруй секрети: openssl rand -hex 32

# 3. Підняти Postgres
docker compose up -d db

# 4. Міграції
uv run alembic upgrade head

# 5. Сервер
uv run fastapi dev app/main.py
```

Swagger UI: http://localhost:8000/docs · health-check: `GET /health`.

Повністю в Docker (API + БД): `docker compose up --build`.

## Тести та лінт

```bash
uv run pytest        # 117 тестів
uv run ruff check .  # лінт
```

## Формат помилок

Усі помилки (включно з 422-валідацією) мають єдину форму — роби `switch` по `type`,
а не по `message`:

```json
{
  "message": "Incorrect email or password",
  "type": "invalid-credentials",
  "body": null
}
```

## Ендпоінти

| Метод | Шлях | Опис |
|-------|------|------|
| POST | `/auth/register` | реєстрація + видача токенів |
| POST | `/auth/login` | логін (OAuth2 form-data) |
| POST | `/auth/refresh` | ротація refresh-токена |
| POST | `/auth/change-password` | зміна пароля (auth) |
| POST | `/auth/request-reset-password` | запит OTP на скидання пароля |
| POST | `/auth/reset-password` | скидання пароля по OTP |
| POST | `/auth/request-verify-email` | запит OTP на верифікацію email (auth) |
| POST | `/auth/verify-email` | верифікація email по OTP (auth) |
| GET | `/users/me` | профіль поточного юзера |
| POST | `/files` | завантаження файлу (verified) |
| GET | `/files` | список файлів з пагінацією |
| GET | `/files/{id}` | завантаження вмісту |
| GET | `/files/{id}/metadata` | метадані файлу |
| DELETE | `/files/{id}` | видалення файлу |

## Відомі обмеження

- Відправка email не реалізована — OTP-коди лише логуються (`logger.debug`).
  Для реального використання підключіть email-провайдера в `auth_service`.
