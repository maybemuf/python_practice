from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models.user import User
from app.services.auth_service import create_access_token


# 1. Happy path: a valid token → the user's data.
#    We request `client` (HTTP) and `auth_headers` (Bearer for test_user).
#    test_user is created automatically because auth_headers depends on it.
def test_read_me_returns_current_user(client: TestClient, auth_headers: dict):
    response = client.get("/users/me", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["username"] == "testuser"


# 2. Security check: response_model=UserPublic must not expose the password hash.
def test_read_me_does_not_leak_password_hash(client: TestClient, auth_headers: dict):
    response = client.get("/users/me", headers=auth_headers)

    assert "password_hash" not in response.json()


# 3. Without an Authorization header → 401 (oauth2_scheme kicks in).
#    Neither test_user nor auth_headers is needed here — just client.
def test_read_me_without_token_is_unauthorized(client: TestClient):
    response = client.get("/users/me")

    assert response.status_code == 401


# 4. Corrupted/forged token → UnauthorizedError (401).
def test_read_me_with_invalid_token(client: TestClient):
    response = client.get(
        "/users/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


# 5. Signature-valid token, but the user is not in the DB (deleted) → 401.
#    The token is no longer valid; the client must re-authenticate.
#    We don't use test_user here: we mint a token for a random UUID by hand.
def test_read_me_for_missing_user(client: TestClient):
    token = create_access_token(uuid4())
    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


# 6. Example of using `session` directly: assert DB state, not just the HTTP
#    response. Here we create our own user inside the test.
def test_read_me_reads_the_right_user(client: TestClient, session: Session):
    from app.services.auth_service import password_hash

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
