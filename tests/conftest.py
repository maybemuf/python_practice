import os

# Підставляємо тестові env ДО імпорту app/settings — інакше Settings()
# спробує прочитати .env або впаде через відсутні обовʼязкові поля.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-prod-0123456789")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.dependencies import get_session
from app.main import app
from app.models.user import User
from app.routers.auth import create_access_token, password_hash


@pytest.fixture(name="engine")
def engine_fixture():
    """In-memory SQLite на весь прогон. StaticPool тримає одне зʼєднання,
    щоб :memory:-БД не зникала між викликами в межах тесту."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine) -> Generator[Session, None, None]:
    """Свіжа сесія на кожен тест. Бо engine function-scoped — таблиці
    чисті в кожному тесті, повна ізоляція без ручного rollback."""
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session) -> Generator[TestClient, None, None]:
    """TestClient з підміненим get_session: усі роутери ходять у тестову БД."""
    def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="test_user")
def test_user_fixture(session: Session) -> User:
    """Готовий користувач у БД. Створюємо напряму через хеш пароля,
    а не через /register — фікстура не має залежати від роуту, який тестуємо."""
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
    """Валідний Bearer-заголовок для test_user — щоб захищені ендпоінти
    тестувати без проходження /login у кожному тесті."""
    token = create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}
