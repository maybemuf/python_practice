from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.routers.auth import (
    authenticate_user,
    create_access_token,
    create_db_refresh_token,
    generate_refresh_token,
    get_user_with_email,
    hash_refresh_token,
    password_hash,
)
from app.settings import settings


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------

VALID_BODY = {
    "email": "new@example.com",
    "username": "newuser",
    "password": "Password123",
}


def test_register_success(client: TestClient):
    response = client.post("/auth/register", json=VALID_BODY)

    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["user"]["email"] == "new@example.com"
    assert data["user"]["username"] == "newuser"


def test_register_persists_user(client: TestClient, session: Session):
    client.post("/auth/register", json=VALID_BODY)

    user = session.exec(select(User).where(User.email == "new@example.com")).first()
    assert user is not None
    assert user.username == "newuser"


def test_register_hashes_password(client: TestClient, session: Session):
    client.post("/auth/register", json=VALID_BODY)

    user = session.exec(select(User).where(User.email == "new@example.com")).first()
    # Пароль не зберігається у відкритому вигляді, і хеш валідний.
    assert user.password_hash != "Password123"
    assert password_hash.verify("Password123", user.password_hash)


def test_register_response_does_not_leak_hash(client: TestClient):
    response = client.post("/auth/register", json=VALID_BODY)

    assert "password_hash" not in response.json()["user"]


def test_register_token_subject_matches_user(client: TestClient):
    response = client.post("/auth/register", json=VALID_BODY)

    data = response.json()
    payload = _decode(data["access_token"])
    assert payload["sub"] == data["user"]["id"]


def test_register_duplicate_email_conflict(client: TestClient, test_user: User):
    # test_user вже сидить у БД з email test@example.com.
    body = {**VALID_BODY, "email": "test@example.com"}
    response = client.post("/auth/register", json=body)

    assert response.status_code == 409
    assert response.json()["type"] == "user-exists"


@pytest.mark.parametrize(
    "password",
    [
        "Short1",          # < 8 символів
        "password123",     # немає великої літери
        "PASSWORD123",     # немає малої літери
        "PasswordABC",     # немає цифри
    ],
)
def test_register_weak_password_rejected(client: TestClient, password: str):
    body = {**VALID_BODY, "password": password}
    response = client.post("/auth/register", json=body)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("email", "not-an-email"),
        ("username", "ab"),               # < 3
        ("username", "a" * 31),           # > 30
    ],
)
def test_register_invalid_fields_rejected(client: TestClient, field: str, value: str):
    body = {**VALID_BODY, field: value}
    response = client.post("/auth/register", json=body)

    assert response.status_code == 422


def test_register_missing_fields_rejected(client: TestClient):
    response = client.post("/auth/register", json={"email": "x@example.com"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /auth/login   (OAuth2PasswordRequestForm -> form-data, не JSON!)
# ---------------------------------------------------------------------------


def test_login_success(client: TestClient, test_user: User):
    response = client.post(
        "/auth/login",
        data={"username": "test@example.com", "password": "Password123"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert _decode(data["access_token"])["sub"] == str(test_user.id)


def test_login_wrong_password(client: TestClient, test_user: User):
    response = client.post(
        "/auth/login",
        data={"username": "test@example.com", "password": "WrongPass123"},
    )

    assert response.status_code == 401
    assert response.json()["type"] == "invalid-credentials"


def test_login_unknown_email(client: TestClient):
    response = client.post(
        "/auth/login",
        data={"username": "nobody@example.com", "password": "Password123"},
    )

    # Та сама помилка, що й при невірному паролі — без user enumeration.
    assert response.status_code == 401
    assert response.json()["type"] == "invalid-credentials"


def test_login_missing_fields(client: TestClient):
    response = client.post("/auth/login", data={"username": "test@example.com"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Хелпери (unit-рівень)
# ---------------------------------------------------------------------------


def test_create_access_token_roundtrip():
    user_id = uuid4()
    payload = _decode(create_access_token(user_id))

    assert payload["sub"] == str(user_id)
    assert "exp" in payload


def test_create_access_token_expiry_in_future():
    exp = _decode(create_access_token(uuid4()))["exp"]

    expected = datetime.now(timezone.utc).timestamp() + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert abs(exp - expected) < 10  # допуск кілька секунд на час виконання


def test_authenticate_user_valid(session: Session, test_user: User):
    user = authenticate_user(session, "test@example.com", "Password123")
    assert user is not None
    assert user.id == test_user.id


def test_authenticate_user_wrong_password(session: Session, test_user: User):
    assert authenticate_user(session, "test@example.com", "Nope12345") is None


def test_authenticate_user_unknown_email(session: Session):
    assert authenticate_user(session, "ghost@example.com", "Password123") is None


def test_get_user_with_email(session: Session, test_user: User):
    assert get_user_with_email(session, "test@example.com").id == test_user.id
    assert get_user_with_email(session, "missing@example.com") is None


def test_password_hash_salting():
    h1 = password_hash.hash("Password123")
    h2 = password_hash.hash("Password123")
    assert h1 != h2  # різна сіль
    assert password_hash.verify("Password123", h1)
    assert not password_hash.verify("WrongPass123", h1)


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


def _register(client: TestClient) -> dict:
    """Реєструє користувача й повертає тіло відповіді (з access+refresh)."""
    return client.post("/auth/register", json=VALID_BODY).json()


def _seed_token(
    session: Session,
    user_id: UUID,
    *,
    expires_in_minutes: int = 60,
    revoked: bool = False,
) -> str:
    """Кладе рядок RefreshToken для юзера й повертає plaintext-токен.
    Дозволяє зібрати протухлий/відкликаний стан, який важко відтворити через API."""
    raw = generate_refresh_token()
    row = create_db_refresh_token(raw, user_id)
    row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    if revoked:
        row.revoked_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    return raw


def test_register_returns_refresh_token(client: TestClient):
    data = _register(client)
    assert data["refresh_token"]


def test_login_returns_refresh_token(client: TestClient, test_user: User):
    response = client.post(
        "/auth/login",
        data={"username": "test@example.com", "password": "Password123"},
    )
    assert response.json()["refresh_token"]


def test_login_issues_independent_refresh_tokens(client: TestClient, test_user: User):
    # Кожен логін — окрема сесія: токени різні (мульти-девайс).
    creds = {"username": "test@example.com", "password": "Password123"}
    first = client.post("/auth/login", data=creds).json()["refresh_token"]
    second = client.post("/auth/login", data=creds).json()["refresh_token"]
    assert first != second


def test_refresh_success(client: TestClient):
    refresh_token = _register(client)["refresh_token"]

    response = client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"


def test_refresh_rotates_token(client: TestClient):
    old = _register(client)["refresh_token"]

    new = client.post("/auth/refresh", json={"refresh_token": old}).json()["refresh_token"]

    assert new != old  # ротація: новий токен не дорівнює старому


def test_refresh_new_access_token_valid(client: TestClient):
    registered = _register(client)
    user_id = registered["user"]["id"]

    data = client.post(
        "/auth/refresh", json={"refresh_token": registered["refresh_token"]}
    ).json()

    assert _decode(data["access_token"])["sub"] == user_id


def test_refresh_old_token_rejected_after_rotation(client: TestClient):
    old = _register(client)["refresh_token"]
    client.post("/auth/refresh", json={"refresh_token": old})  # ротація відкликає old

    response = client.post("/auth/refresh", json={"refresh_token": old})

    assert response.status_code == 401
    assert response.json()["type"] == "invalid-refresh"


def test_refresh_reuse_revokes_all_user_tokens(client: TestClient):
    # Детект крадіжки: повторне використання відкликаного токена гасить
    # ВСІ токени юзера, включно зі свіжо-виданим.
    old = _register(client)["refresh_token"]
    new = client.post("/auth/refresh", json={"refresh_token": old}).json()["refresh_token"]

    # Зловмисник повторно шле вкрадений старий токен.
    reuse = client.post("/auth/refresh", json={"refresh_token": old})
    assert reuse.status_code == 401

    # Після цього навіть валідний новий токен має бути мертвий.
    after = client.post("/auth/refresh", json={"refresh_token": new})
    assert after.status_code == 401
    assert after.json()["type"] == "invalid-refresh"


def test_refresh_invalid_token_rejected(client: TestClient):
    response = client.post("/auth/refresh", json={"refresh_token": "totally-bogus"})

    assert response.status_code == 401
    assert response.json()["type"] == "invalid-refresh"


def test_refresh_unknown_wellformed_token_rejected(client: TestClient):
    # Правильний за форматом, але відсутній у БД токен.
    response = client.post(
        "/auth/refresh", json={"refresh_token": generate_refresh_token()}
    )

    assert response.status_code == 401
    assert response.json()["type"] == "invalid-refresh"


def test_refresh_expired_token_rejected(
    client: TestClient, session: Session, test_user: User
):
    expired = _seed_token(session, test_user.id, expires_in_minutes=-1)

    response = client.post("/auth/refresh", json={"refresh_token": expired})

    assert response.status_code == 401
    assert response.json()["type"] == "invalid-refresh"


def test_refresh_revoked_token_rejected(
    client: TestClient, session: Session, test_user: User
):
    revoked = _seed_token(session, test_user.id, revoked=True)

    response = client.post("/auth/refresh", json={"refresh_token": revoked})

    assert response.status_code == 401
    assert response.json()["type"] == "invalid-refresh"


def test_refresh_missing_body_rejected(client: TestClient):
    response = client.post("/auth/refresh", json={})

    assert response.status_code == 422


def test_refresh_persists_rotated_state(
    client: TestClient, session: Session
):
    registered = _register(client)
    old_raw = registered["refresh_token"]
    user_id = UUID(registered["user"]["id"])

    client.post("/auth/refresh", json={"refresh_token": old_raw})

    rows = session.exec(
        select(RefreshToken).where(RefreshToken.user_id == user_id)
    ).all()
    # Два рядки: старий (відкликаний) і новий (живий).
    assert len(rows) == 2
    old_row = next(r for r in rows if r.token_hash == hash_refresh_token(old_raw))
    new_row = next(r for r in rows if r.token_hash != hash_refresh_token(old_raw))
    assert old_row.revoked_at is not None
    assert new_row.revoked_at is None


def test_refresh_token_stored_as_hash_not_plaintext(
    client: TestClient, session: Session
):
    raw = _register(client)["refresh_token"]

    row = session.exec(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    ).first()
    assert row is not None
    assert row.token_hash != raw  # сам токен у БД не лежить


# ---------------------------------------------------------------------------
# Хелпери refresh (unit-рівень)
# ---------------------------------------------------------------------------


def test_hash_refresh_token_deterministic():
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hash_refresh_token(token)


def test_hash_refresh_token_differs_per_input():
    assert hash_refresh_token("a") != hash_refresh_token("b")


def test_generate_refresh_token_unique():
    tokens = {generate_refresh_token() for _ in range(100)}
    assert len(tokens) == 100  # криптовипадкові — колізій немає
