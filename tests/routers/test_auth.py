from datetime import datetime, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.user import User
from app.routers.auth import (
    authenticate_user,
    create_access_token,
    get_user_with_email,
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
