from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models.user import User
from app.routers.auth import create_access_token


# 1. Успішний сценарій: валідний токен → дані користувача.
#    Просимо `client` (HTTP) і `auth_headers` (Bearer для test_user).
#    test_user створюється автоматично, бо auth_headers від нього залежить.
def test_read_me_returns_current_user(client: TestClient, auth_headers: dict):
    response = client.get("/users/me", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["username"] == "testuser"


# 2. Перевірка безпеки: response_model=UserPublic не має віддавати хеш пароля.
def test_read_me_does_not_leak_password_hash(client: TestClient, auth_headers: dict):
    response = client.get("/users/me", headers=auth_headers)

    assert "password_hash" not in response.json()


# 3. Без заголовка Authorization → 401 (спрацьовує oauth2_scheme).
#    Тут НЕ потрібен ні test_user, ні auth_headers — лише client.
def test_read_me_without_token_is_unauthorized(client: TestClient):
    response = client.get("/users/me")

    assert response.status_code == 401


# 4. Зіпсований/підроблений токен → UnauthorizedError (401).
def test_read_me_with_invalid_token(client: TestClient):
    response = client.get(
        "/users/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


# 5. Валідний токен, але користувача в БД немає → UserNotFoundError (404).
#    Тут НЕ беремо test_user: робимо токен для випадкового UUID вручну.
def test_read_me_for_missing_user(client: TestClient):
    token = create_access_token(uuid4())
    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


# 6. Приклад використання `session` напряму: перевірити стан БД,
#    а не лише HTTP-відповідь. Тут створюємо свого користувача в тесті.
def test_read_me_reads_the_right_user(client: TestClient, session: Session):
    from app.routers.auth import password_hash

    user = User(
        email="alice@example.com",
        username="alice",
        password_hash=password_hash.hash("Password123"),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    token = create_access_token(user.id)
    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)
