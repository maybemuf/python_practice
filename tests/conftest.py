import os

# Set test env vars BEFORE importing app/settings — otherwise Settings() will
# try to read .env or fail on the missing required fields.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-prod-0123456789")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.dependencies.session import get_session
from app.main import app
from app.models.user import User
from app.services.auth_service import create_access_token, password_hash


@pytest.fixture(name="engine")
def engine_fixture():
    """In-memory SQLite for the whole run. StaticPool keeps a single connection
    so the :memory: DB doesn't disappear between calls within a test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine) -> Generator[Session]:
    """A fresh session per test. Since the engine is function-scoped, tables
    are clean in every test — full isolation without manual rollback."""
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session) -> Generator[TestClient]:
    """TestClient with get_session overridden: all routers hit the test DB."""
    def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="test_user")
def test_user_fixture(session: Session) -> User:
    """A ready-made user in the DB. Created directly via a password hash rather
    than through /register — the fixture must not depend on the route under test."""
    user = User(
        email="test@example.com",
        username="testuser",
        password_hash=password_hash.hash("Password123"),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(test_user: User) -> dict[str, str]:
    """A valid Bearer header for test_user — so protected endpoints can be
    tested without going through /login in every test."""
    token = create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}
