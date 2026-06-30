from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models.file import FileObject, FileStatus
from app.models.user import User
from app.routers.auth import create_access_token, password_hash


# --- Інфраструктура ----------------------------------------------------------


class FakeStorage:
    """In-memory реалізація Storage-протоколу для тестів: жодного диску,
    усе тримаємо в dict {key: bytes}. Так тести швидкі й ізольовані."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, key: str, source, content_type: str) -> None:
        # читаємо ЧЕРЕЗ переданий MeteredReader, щоб він порахував size/checksum
        buf = bytearray()
        while chunk := await source.read(1024 * 1024):
            buf.extend(chunk)
        self.files[key] = bytes(buf)

    async def open_stream(self, key: str):
        yield self.files[key]  # для тесту досить одного шматка

    async def exists(self, key: str) -> bool:
        return key in self.files

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)

    def url_for(self, key: str) -> str:
        return f"/files/{key}"


@pytest.fixture(name="fake_storage")
def fake_storage_fixture(monkeypatch) -> FakeStorage:
    """Підміняємо модульний singleton `storage`, який роутер імпортував до себе."""
    storage = FakeStorage()
    monkeypatch.setattr("app.routers.files.storage", storage)
    return storage


@pytest.fixture(name="verified_user")
def verified_user_fixture(session: Session) -> User:
    """Верифікований власник файлів — бо файлові ендпоінти за VerifiedUserDep.
    Conftest-овий test_user НЕ верифікований, тож тут потрібен свій."""
    user = User(
        email="owner@example.com",
        username="owner",
        password_hash=password_hash.hash("Password123"),
        email_verified_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture(name="verified_headers")
def verified_headers_fixture(verified_user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(verified_user.id)}"}


def _seed_file(
    session: Session,
    fake_storage: FakeStorage,
    owner_id,
    *,
    content: bytes = b"hello file\n",
    filename: str = "report.txt",
    content_type: str = "text/plain",
    store_on_disk: bool = True,
) -> FileObject:
    """Кладе FileObject у БД і (опційно) байти у фейкове сховище.
    store_on_disk=False симулює розсинхрон БД↔сховище."""
    file_id = uuid4()
    key = f"users/{owner_id}/{file_id}.txt"
    if store_on_disk:
        fake_storage.files[key] = content
    obj = FileObject(
        id=file_id,
        owner_id=owner_id,
        storage_key=key,
        original_filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        checksum="0" * 64,
        status=FileStatus.SAVED,
    )
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def _other_user(session: Session) -> User:
    user = User(
        email="stranger@example.com",
        username="stranger",
        password_hash=password_hash.hash("Password123"),
        email_verified_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# --- UPLOAD ------------------------------------------------------------------


def test_upload_file_success(
    client: TestClient, verified_headers: dict, fake_storage: FakeStorage
):
    content = b"this is a plain text file\n"
    response = client.post(
        "/files",
        headers=verified_headers,
        files={"file": ("notes.txt", content, "text/plain")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["original_filename"] == "notes.txt"
    assert data["content_type"] == "text/plain"
    assert data["size_bytes"] == len(content)
    assert data["status"] == FileStatus.SAVED.value
    # байти реально потрапили у сховище
    assert content in fake_storage.files.values()


def test_upload_does_not_leak_internal_fields(
    client: TestClient, verified_headers: dict, fake_storage: FakeStorage
):
    response = client.post(
        "/files",
        headers=verified_headers,
        files={"file": ("notes.txt", b"plain text body\n", "text/plain")},
    )

    data = response.json()
    # FilePublic не повинен віддавати внутрішні поля
    assert "storage_key" not in data
    assert "owner_id" not in data
    assert "checksum" not in data


def test_upload_unsupported_type_is_rejected(
    client: TestClient, verified_headers: dict, fake_storage: FakeStorage
):
    # libmagic визначить це як application/octet-stream → не в ALLOWED_CONTENT_TYPES
    binary = bytes(range(256)) * 4
    response = client.post(
        "/files",
        headers=verified_headers,
        files={"file": ("payload.bin", binary, "application/octet-stream")},
    )

    assert response.status_code == 415
    assert fake_storage.files == {}  # нічого не збережено


def test_upload_requires_verified_user(
    client: TestClient, auth_headers: dict, fake_storage: FakeStorage
):
    # auth_headers → conftest-овий test_user, який НЕ верифікований
    response = client.post(
        "/files",
        headers=auth_headers,
        files={"file": ("notes.txt", b"plain text\n", "text/plain")},
    )

    assert response.status_code == 403


def test_upload_without_auth_is_unauthorized(
    client: TestClient, fake_storage: FakeStorage
):
    response = client.post(
        "/files",
        files={"file": ("notes.txt", b"plain text\n", "text/plain")},
    )

    assert response.status_code == 401


# --- DOWNLOAD ----------------------------------------------------------------


def test_download_file_success(
    client: TestClient,
    verified_headers: dict,
    verified_user: User,
    fake_storage: FakeStorage,
    session: Session,
):
    content = b"downloadable content\n"
    file = _seed_file(
        session, fake_storage, verified_user.id, content=content, filename="doc.txt"
    )

    response = client.get(f"/files/{file.id}", headers=verified_headers)

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("text/plain")
    assert "doc.txt" in response.headers["content-disposition"]
    assert response.headers["content-length"] == str(len(content))


def test_download_other_users_file_is_404(
    client: TestClient,
    verified_headers: dict,
    fake_storage: FakeStorage,
    session: Session,
):
    stranger = _other_user(session)
    file = _seed_file(session, fake_storage, stranger.id)

    response = client.get(f"/files/{file.id}", headers=verified_headers)

    # 404, а не 403 — не підтверджуємо існування чужого файлу
    assert response.status_code == 404


def test_download_nonexistent_file_is_404(
    client: TestClient, verified_headers: dict, fake_storage: FakeStorage
):
    response = client.get(f"/files/{uuid4()}", headers=verified_headers)

    assert response.status_code == 404


def test_download_missing_in_storage_is_404(
    client: TestClient,
    verified_headers: dict,
    verified_user: User,
    fake_storage: FakeStorage,
    session: Session,
):
    # запис у БД є, а файлу у сховищі нема (розсинхрон) → 404 ще ДО стріму
    file = _seed_file(session, fake_storage, verified_user.id, store_on_disk=False)

    response = client.get(f"/files/{file.id}", headers=verified_headers)

    assert response.status_code == 404


# --- DELETE ------------------------------------------------------------------


def test_delete_file_success(
    client: TestClient,
    verified_headers: dict,
    verified_user: User,
    fake_storage: FakeStorage,
    session: Session,
):
    file = _seed_file(session, fake_storage, verified_user.id)
    key = file.storage_key

    response = client.delete(f"/files/{file.id}", headers=verified_headers)

    assert response.status_code == 204
    assert session.get(FileObject, file.id) is None  # зник з БД
    assert key not in fake_storage.files  # зник зі сховища


def test_delete_other_users_file_is_404(
    client: TestClient,
    verified_headers: dict,
    fake_storage: FakeStorage,
    session: Session,
):
    stranger = _other_user(session)
    file = _seed_file(session, fake_storage, stranger.id)

    response = client.delete(f"/files/{file.id}", headers=verified_headers)

    assert response.status_code == 404
    # чужий файл не зачеплено
    assert session.get(FileObject, file.id) is not None
    assert file.storage_key in fake_storage.files


# --- LIST --------------------------------------------------------------------


def test_list_returns_only_own_files(
    client: TestClient,
    verified_headers: dict,
    verified_user: User,
    fake_storage: FakeStorage,
    session: Session,
):
    _seed_file(session, fake_storage, verified_user.id, filename="a.txt")
    _seed_file(session, fake_storage, verified_user.id, filename="b.txt")
    stranger = _other_user(session)
    _seed_file(session, fake_storage, stranger.id, filename="secret.txt")

    response = client.get("/files", headers=verified_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = {item["original_filename"] for item in data}
    assert names == {"a.txt", "b.txt"}


def test_list_respects_pagination(
    client: TestClient,
    verified_headers: dict,
    verified_user: User,
    fake_storage: FakeStorage,
    session: Session,
):
    for i in range(3):
        _seed_file(session, fake_storage, verified_user.id, filename=f"f{i}.txt")

    response = client.get("/files?limit=2&offset=0", headers=verified_headers)

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_does_not_leak_storage_key(
    client: TestClient,
    verified_headers: dict,
    verified_user: User,
    fake_storage: FakeStorage,
    session: Session,
):
    _seed_file(session, fake_storage, verified_user.id)

    response = client.get("/files", headers=verified_headers)

    assert response.status_code == 200
    assert all("storage_key" not in item for item in response.json())


# --- METADATA ----------------------------------------------------------------


def test_metadata_success(
    client: TestClient,
    verified_headers: dict,
    verified_user: User,
    fake_storage: FakeStorage,
    session: Session,
):
    file = _seed_file(session, fake_storage, verified_user.id, filename="meta.txt")

    response = client.get(f"/files/{file.id}/metadata", headers=verified_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(file.id)
    assert data["original_filename"] == "meta.txt"
    assert "storage_key" not in data


def test_metadata_other_users_file_is_404(
    client: TestClient,
    verified_headers: dict,
    fake_storage: FakeStorage,
    session: Session,
):
    stranger = _other_user(session)
    file = _seed_file(session, fake_storage, stranger.id)

    response = client.get(f"/files/{file.id}/metadata", headers=verified_headers)

    assert response.status_code == 404
