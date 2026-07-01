from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.exceptions import (
    OtpIsExpiredError,
    OtpIsIncorrectError,
    TooManyAttemptsError,
)
from app.models.otp import MAX_OTP_ATTEMPTS, OTPRequest, OTPType, hash_otp
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    create_db_refresh_token,
    create_otp_request,
    generate_refresh_token,
    get_user_with_email,
    hash_refresh_token,
    invalidate_previous_otp_requests,
    password_hash,
    verify_otp_request,
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
    # The password is not stored in plaintext, and the hash is valid.
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
    # test_user already sits in the DB with email test@example.com.
    body = {**VALID_BODY, "email": "test@example.com"}
    response = client.post("/auth/register", json=body)

    assert response.status_code == 409
    assert response.json()["type"] == "user-exists"


@pytest.mark.parametrize(
    "password",
    [
        "Short1",          # < 8 characters
        "password123",     # no uppercase letter
        "PASSWORD123",     # no lowercase letter
        "PasswordABC",     # no digit
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


def test_validation_error_uses_unified_shape(client: TestClient):
    # 422 is normalized to the unified shape {message, type, body}, not the default {detail}.
    response = client.post("/auth/register", json={"email": "x@example.com"})

    data = response.json()
    assert data["type"] == "validation-error"
    assert "message" in data
    assert isinstance(data["body"], list)  # field-level details
    assert "detail" not in data


# ---------------------------------------------------------------------------
# POST /auth/login   (OAuth2PasswordRequestForm -> form-data, not JSON!)
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

    # Same error as a wrong password — no user enumeration.
    assert response.status_code == 401
    assert response.json()["type"] == "invalid-credentials"


def test_login_missing_fields(client: TestClient):
    response = client.post("/auth/login", data={"username": "test@example.com"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Helpers (unit level)
# ---------------------------------------------------------------------------


def test_create_access_token_roundtrip():
    user_id = uuid4()
    payload = _decode(create_access_token(user_id))

    assert payload["sub"] == str(user_id)
    assert "exp" in payload


def test_create_access_token_expiry_in_future():
    exp = _decode(create_access_token(uuid4()))["exp"]

    expected = datetime.now(UTC).timestamp() + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert abs(exp - expected) < 10  # a few seconds of tolerance for execution time


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
    assert h1 != h2  # different salt
    assert password_hash.verify("Password123", h1)
    assert not password_hash.verify("WrongPass123", h1)


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


def _register(client: TestClient) -> dict:
    """Registers a user and returns the response body (with access + refresh)."""
    return client.post("/auth/register", json=VALID_BODY).json()


def _seed_token(
    session: Session,
    user_id: UUID,
    *,
    expires_in_minutes: int = 60,
    revoked: bool = False,
) -> str:
    """Inserts a RefreshToken row for the user and returns the plaintext token.
    Lets us build an expired/revoked state that's hard to reproduce via the API."""
    raw = generate_refresh_token()
    row = create_db_refresh_token(raw, user_id)
    row.expires_at = datetime.now(UTC) + timedelta(minutes=expires_in_minutes)
    if revoked:
        row.revoked_at = datetime.now(UTC)
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
    # Each login is a separate session: tokens differ (multi-device).
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

    assert new != old  # rotation: the new token differs from the old one


def test_refresh_new_access_token_valid(client: TestClient):
    registered = _register(client)
    user_id = registered["user"]["id"]

    data = client.post(
        "/auth/refresh", json={"refresh_token": registered["refresh_token"]}
    ).json()

    assert _decode(data["access_token"])["sub"] == user_id


def test_refresh_old_token_rejected_after_rotation(client: TestClient):
    old = _register(client)["refresh_token"]
    client.post("/auth/refresh", json={"refresh_token": old})  # rotation revokes old

    response = client.post("/auth/refresh", json={"refresh_token": old})

    assert response.status_code == 401
    assert response.json()["type"] == "invalid-refresh"


def test_refresh_reuse_revokes_all_user_tokens(client: TestClient):
    # Theft detection: reusing a revoked token revokes ALL of the user's tokens,
    # including the freshly issued one.
    old = _register(client)["refresh_token"]
    new = client.post("/auth/refresh", json={"refresh_token": old}).json()["refresh_token"]

    # The attacker resends the stolen old token.
    reuse = client.post("/auth/refresh", json={"refresh_token": old})
    assert reuse.status_code == 401

    # After that even the valid new token must be dead.
    after = client.post("/auth/refresh", json={"refresh_token": new})
    assert after.status_code == 401
    assert after.json()["type"] == "invalid-refresh"


def test_refresh_invalid_token_rejected(client: TestClient):
    response = client.post("/auth/refresh", json={"refresh_token": "totally-bogus"})

    assert response.status_code == 401
    assert response.json()["type"] == "invalid-refresh"


def test_refresh_unknown_wellformed_token_rejected(client: TestClient):
    # A well-formed token that's absent from the DB.
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
    # Two rows: the old one (revoked) and the new one (live).
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
    assert row.token_hash != raw  # the token itself is not stored in the DB


# ---------------------------------------------------------------------------
# Refresh helpers (unit level)
# ---------------------------------------------------------------------------


def test_hash_refresh_token_deterministic():
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hash_refresh_token(token)


def test_hash_refresh_token_differs_per_input():
    assert hash_refresh_token("a") != hash_refresh_token("b")


def test_generate_refresh_token_unique():
    tokens = {generate_refresh_token() for _ in range(100)}
    assert len(tokens) == 100  # cryptographically random — no collisions


# ---------------------------------------------------------------------------
# OTP helpers (shared by reset-password / verify-email)
# ---------------------------------------------------------------------------


def _seed_otp(
    session: Session,
    user_id: UUID,
    otp_type: OTPType,
    *,
    expires_in_minutes: int = 10,
) -> str:
    """Inserts an OTPRequest into the DB and returns the plaintext code (6 digits).
    The code is not returned via the API (only logged), so for flow tests we seed
    the OTP directly — same as _seed_token for refresh."""
    raw, otp = create_otp_request(otp_type=otp_type, user_id=user_id)
    otp.expires_at = datetime.now(UTC) + timedelta(minutes=expires_in_minutes)
    session.add(otp)
    session.commit()
    return raw


def _wrong_code(code: str) -> str:
    """A different well-formed code (so we catch a 400, not a 422)."""
    return "000000" if code != "000000" else "111111"


# ---------------------------------------------------------------------------
# POST /auth/change-password   (Bearer required)
# ---------------------------------------------------------------------------


def test_change_password_success(client: TestClient, auth_headers: dict):
    response = client.post(
        "/auth/change-password",
        headers=auth_headers,
        json={"old_password": "Password123", "new_password": "NewPassword123"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"


def test_change_password_updates_password(client: TestClient, auth_headers: dict):
    client.post(
        "/auth/change-password",
        headers=auth_headers,
        json={"old_password": "Password123", "new_password": "NewPassword123"},
    )

    creds = {"username": "test@example.com", "password": "Password123"}
    assert client.post("/auth/login", data=creds).status_code == 401
    new_creds = {"username": "test@example.com", "password": "NewPassword123"}
    assert client.post("/auth/login", data=new_creds).status_code == 200


def test_change_password_wrong_old(client: TestClient, auth_headers: dict):
    response = client.post(
        "/auth/change-password",
        headers=auth_headers,
        json={"old_password": "WrongPass123", "new_password": "NewPassword123"},
    )

    assert response.status_code == 400
    assert response.json()["type"] == "invalid-old-password"


def test_change_password_same_as_old(client: TestClient, auth_headers: dict):
    response = client.post(
        "/auth/change-password",
        headers=auth_headers,
        json={"old_password": "Password123", "new_password": "Password123"},
    )

    assert response.status_code == 400
    assert response.json()["type"] == "new-password-equals-old"


def test_change_password_weak_new_rejected(client: TestClient, auth_headers: dict):
    response = client.post(
        "/auth/change-password",
        headers=auth_headers,
        json={"old_password": "Password123", "new_password": "weak"},
    )

    assert response.status_code == 422


def test_change_password_requires_auth(client: TestClient):
    response = client.post(
        "/auth/change-password",
        json={"old_password": "Password123", "new_password": "NewPassword123"},
    )

    assert response.status_code == 401


def test_change_password_new_refresh_token_valid(client: TestClient, auth_headers: dict):
    # Regression: the freshly issued refresh must not be revoked along with the old ones.
    new_refresh = client.post(
        "/auth/change-password",
        headers=auth_headers,
        json={"old_password": "Password123", "new_password": "NewPassword123"},
    ).json()["refresh_token"]

    response = client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert response.status_code == 200


def test_change_password_revokes_existing_refresh_tokens(
    client: TestClient, session: Session, test_user: User, auth_headers: dict
):
    old_refresh = _seed_token(session, test_user.id)

    client.post(
        "/auth/change-password",
        headers=auth_headers,
        json={"old_password": "Password123", "new_password": "NewPassword123"},
    )

    response = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert response.status_code == 401
    assert response.json()["type"] == "invalid-refresh"


# ---------------------------------------------------------------------------
# POST /auth/request-reset-password   (anti-enumeration: always 200)
# ---------------------------------------------------------------------------


def test_request_reset_password_unknown_email_ok(client: TestClient):
    response = client.post(
        "/auth/request-reset-password", json={"email": "ghost@example.com"}
    )

    assert response.status_code == 200
    assert "message" in response.json()


def test_request_reset_password_unknown_email_creates_no_otp(
    client: TestClient, session: Session
):
    client.post("/auth/request-reset-password", json={"email": "ghost@example.com"})

    assert session.exec(select(OTPRequest)).all() == []


def test_request_reset_password_existing_creates_otp(
    client: TestClient, session: Session, test_user: User
):
    response = client.post(
        "/auth/request-reset-password", json={"email": "test@example.com"}
    )
    assert response.status_code == 200

    otps = session.exec(
        select(OTPRequest).where(OTPRequest.user_id == test_user.id)
    ).all()
    assert len(otps) == 1
    assert otps[0].otp_type == OTPType.PASSWORD_RECOVERY


def test_request_reset_password_same_message_regardless_of_user(
    client: TestClient, test_user: User
):
    # The response for an existing and a non-existent email must be identical.
    known = client.post(
        "/auth/request-reset-password", json={"email": "test@example.com"}
    ).json()
    unknown = client.post(
        "/auth/request-reset-password", json={"email": "ghost@example.com"}
    ).json()
    assert known == unknown


def test_request_reset_password_invalidates_previous(
    client: TestClient, session: Session, test_user: User
):
    client.post("/auth/request-reset-password", json={"email": "test@example.com"})
    client.post("/auth/request-reset-password", json={"email": "test@example.com"})

    otps = session.exec(
        select(OTPRequest).where(OTPRequest.user_id == test_user.id)
    ).all()
    active = [o for o in otps if o.invalidated_at is None and o.consumed_at is None]
    assert len(otps) == 2
    assert len(active) == 1  # only the latest code stays active


def test_request_reset_password_invalid_email_rejected(client: TestClient):
    response = client.post(
        "/auth/request-reset-password", json={"email": "not-an-email"}
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /auth/reset-password
# ---------------------------------------------------------------------------


def test_reset_password_success(client: TestClient, session: Session, test_user: User):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    response = client.post(
        "/auth/reset-password",
        json={"email": "test@example.com", "raw_code": code, "new_password": "NewPassword123"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]


def test_reset_password_changes_password(
    client: TestClient, session: Session, test_user: User
):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)
    client.post(
        "/auth/reset-password",
        json={"email": "test@example.com", "raw_code": code, "new_password": "NewPassword123"},
    )

    assert client.post(
        "/auth/login", data={"username": "test@example.com", "password": "Password123"}
    ).status_code == 401
    assert client.post(
        "/auth/login", data={"username": "test@example.com", "password": "NewPassword123"}
    ).status_code == 200


def test_reset_password_wrong_code(
    client: TestClient, session: Session, test_user: User
):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    response = client.post(
        "/auth/reset-password",
        json={
            "email": "test@example.com",
            "raw_code": _wrong_code(code),
            "new_password": "NewPassword123",
        },
    )

    assert response.status_code == 400
    assert response.json()["type"] == "otp-is-incorrect"


def test_reset_password_expired_code(
    client: TestClient, session: Session, test_user: User
):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY, expires_in_minutes=-1)

    response = client.post(
        "/auth/reset-password",
        json={"email": "test@example.com", "raw_code": code, "new_password": "NewPassword123"},
    )

    assert response.status_code == 400
    assert response.json()["type"] == "otp-is-expired"


def test_reset_password_unknown_email(client: TestClient):
    # No enumeration: a non-existent email gives the same result as a wrong code.
    response = client.post(
        "/auth/reset-password",
        json={"email": "ghost@example.com", "raw_code": "123456", "new_password": "NewPassword123"},
    )

    assert response.status_code == 400
    assert response.json()["type"] == "otp-is-incorrect"


def test_reset_password_consumes_code(
    client: TestClient, session: Session, test_user: User
):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)
    body = {"email": "test@example.com", "raw_code": code, "new_password": "NewPassword123"}

    assert client.post("/auth/reset-password", json=body).status_code == 200
    # Reusing the same code — the code is already consumed.
    second = client.post("/auth/reset-password", json=body)
    assert second.status_code == 400
    assert second.json()["type"] == "otp-is-incorrect"


def test_reset_password_verifies_email(
    client: TestClient, session: Session, test_user: User
):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    response = client.post(
        "/auth/reset-password",
        json={"email": "test@example.com", "raw_code": code, "new_password": "NewPassword123"},
    )

    assert response.json()["user"]["email_verified_at"] is not None


def test_reset_password_weak_new_rejected(client: TestClient):
    response = client.post(
        "/auth/reset-password",
        json={"email": "test@example.com", "raw_code": "123456", "new_password": "weak"},
    )

    assert response.status_code == 422


def test_reset_password_revokes_existing_refresh_tokens(
    client: TestClient, session: Session, test_user: User
):
    old_refresh = _seed_token(session, test_user.id)
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    client.post(
        "/auth/reset-password",
        json={"email": "test@example.com", "raw_code": code, "new_password": "NewPassword123"},
    )

    response = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/request-verify-email   (Bearer required)
# ---------------------------------------------------------------------------


def test_request_verify_email_creates_otp(
    client: TestClient, session: Session, test_user: User, auth_headers: dict
):
    response = client.post("/auth/request-verify-email", headers=auth_headers)
    assert response.status_code == 200

    otps = session.exec(
        select(OTPRequest).where(OTPRequest.user_id == test_user.id)
    ).all()
    assert len(otps) == 1
    assert otps[0].otp_type == OTPType.EMAIL_VERIFICATION


def test_request_verify_email_requires_auth(client: TestClient):
    response = client.post("/auth/request-verify-email")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /auth/verify-email   (Bearer required)
# ---------------------------------------------------------------------------


def test_verify_email_success(
    client: TestClient, session: Session, test_user: User, auth_headers: dict
):
    code = _seed_otp(session, test_user.id, OTPType.EMAIL_VERIFICATION)

    response = client.post(
        "/auth/verify-email", headers=auth_headers, json={"code": code}
    )

    assert response.status_code == 200
    assert response.json()["email_verified_at"] is not None


def test_verify_email_wrong_code(
    client: TestClient, session: Session, test_user: User, auth_headers: dict
):
    code = _seed_otp(session, test_user.id, OTPType.EMAIL_VERIFICATION)

    response = client.post(
        "/auth/verify-email", headers=auth_headers, json={"code": _wrong_code(code)}
    )

    assert response.status_code == 400
    assert response.json()["type"] == "otp-is-incorrect"


def test_verify_email_expired_code(
    client: TestClient, session: Session, test_user: User, auth_headers: dict
):
    code = _seed_otp(session, test_user.id, OTPType.EMAIL_VERIFICATION, expires_in_minutes=-1)

    response = client.post(
        "/auth/verify-email", headers=auth_headers, json={"code": code}
    )

    assert response.status_code == 400
    assert response.json()["type"] == "otp-is-expired"


def test_verify_email_rejects_password_recovery_otp(
    client: TestClient, session: Session, test_user: User, auth_headers: dict
):
    # Regression: a PASSWORD_RECOVERY code must not pass email verification.
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    response = client.post(
        "/auth/verify-email", headers=auth_headers, json={"code": code}
    )

    assert response.status_code == 400
    assert response.json()["type"] == "otp-is-incorrect"


def test_verify_email_consumes_code(
    client: TestClient, session: Session, test_user: User, auth_headers: dict
):
    code = _seed_otp(session, test_user.id, OTPType.EMAIL_VERIFICATION)

    assert client.post(
        "/auth/verify-email", headers=auth_headers, json={"code": code}
    ).status_code == 200
    # Reusing the same code — it is consumed.
    second = client.post("/auth/verify-email", headers=auth_headers, json={"code": code})
    assert second.status_code == 400


def test_verify_email_requires_auth(client: TestClient):
    response = client.post("/auth/verify-email", json={"code": "123456"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# OTP helpers (unit level)
# ---------------------------------------------------------------------------


def test_hash_otp_deterministic():
    assert hash_otp("123456") == hash_otp("123456")


def test_hash_otp_differs_per_input():
    assert hash_otp("123456") != hash_otp("654321")


def test_hash_otp_not_plaintext():
    assert hash_otp("123456") != "123456"


def test_create_otp_request_format():
    raw, otp = create_otp_request(otp_type=OTPType.PASSWORD_RECOVERY, user_id=uuid4())

    assert len(raw) == 6 and raw.isdigit()
    assert otp.code_hash == hash_otp(raw)
    assert otp.otp_type == OTPType.PASSWORD_RECOVERY
    assert otp.expires_at > datetime.now(UTC)


def test_otp_request_verify_matches():
    raw, otp = create_otp_request(otp_type=OTPType.EMAIL_VERIFICATION, user_id=uuid4())

    assert otp.verify(raw) is True
    assert otp.verify(_wrong_code(raw)) is False


def test_otp_request_is_expired():
    _, otp = create_otp_request(otp_type=OTPType.EMAIL_VERIFICATION, user_id=uuid4())
    assert otp.is_expired() is False

    otp.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert otp.is_expired() is True


def test_verify_otp_request_consumes(session: Session, test_user: User):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    verify_otp_request(
        session, test_user.id, otp_type=OTPType.PASSWORD_RECOVERY, raw_code=code
    )

    otp = session.exec(
        select(OTPRequest).where(OTPRequest.user_id == test_user.id)
    ).first()
    assert otp.consumed_at is not None


def test_verify_otp_request_wrong_code_raises(session: Session, test_user: User):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    with pytest.raises(OtpIsIncorrectError):
        verify_otp_request(
            session, test_user.id, otp_type=OTPType.PASSWORD_RECOVERY, raw_code=_wrong_code(code)
        )


def test_verify_otp_request_missing_raises(session: Session, test_user: User):
    with pytest.raises(OtpIsIncorrectError):
        verify_otp_request(
            session, test_user.id, otp_type=OTPType.PASSWORD_RECOVERY, raw_code="123456"
        )


def test_verify_otp_request_expired_raises(session: Session, test_user: User):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY, expires_in_minutes=-1)

    with pytest.raises(OtpIsExpiredError):
        verify_otp_request(
            session, test_user.id, otp_type=OTPType.PASSWORD_RECOVERY, raw_code=code
        )


def test_verify_otp_request_type_mismatch_raises(session: Session, test_user: User):
    # The code was issued for email verification but we check it as password-recovery.
    code = _seed_otp(session, test_user.id, OTPType.EMAIL_VERIFICATION)

    with pytest.raises(OtpIsIncorrectError):
        verify_otp_request(
            session, test_user.id, otp_type=OTPType.PASSWORD_RECOVERY, raw_code=code
        )


def test_invalidate_previous_otp_requests(session: Session, test_user: User):
    _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    invalidate_previous_otp_requests(
        session, otp_type=OTPType.PASSWORD_RECOVERY, user_id=test_user.id
    )
    session.commit()

    otp = session.exec(
        select(OTPRequest).where(OTPRequest.user_id == test_user.id)
    ).first()
    assert otp.invalidated_at is not None


# ---------------------------------------------------------------------------
# Rate limiting OTP (anti-bruteforce) — MAX_OTP_ATTEMPTS
# ---------------------------------------------------------------------------


def test_verify_otp_counts_failed_attempts(session: Session, test_user: User):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    with pytest.raises(OtpIsIncorrectError):
        verify_otp_request(
            session, test_user.id, OTPType.PASSWORD_RECOVERY, raw_code=_wrong_code(code)
        )

    otp = session.exec(
        select(OTPRequest).where(OTPRequest.user_id == test_user.id)
    ).first()
    assert otp.attempts == 1  # the failed attempt persists even after the exception


def test_verify_otp_locks_after_max_attempts(session: Session, test_user: User):
    code = _seed_otp(session, test_user.id, OTPType.PASSWORD_RECOVERY)

    # Exhaust the limit with failed attempts.
    for _ in range(MAX_OTP_ATTEMPTS):
        with pytest.raises(OtpIsIncorrectError):
            verify_otp_request(
                session, test_user.id, OTPType.PASSWORD_RECOVERY, raw_code=_wrong_code(code)
            )

    # The next attempt — even with the CORRECT code — is blocked.
    with pytest.raises(TooManyAttemptsError):
        verify_otp_request(session, test_user.id, OTPType.PASSWORD_RECOVERY, raw_code=code)

    otp = session.exec(
        select(OTPRequest).where(OTPRequest.user_id == test_user.id)
    ).first()
    assert otp.invalidated_at is not None  # the code was killed


def test_verify_email_too_many_attempts_returns_429(
    client: TestClient, session: Session, test_user: User, auth_headers: dict
):
    code = _seed_otp(session, test_user.id, OTPType.EMAIL_VERIFICATION)
    wrong = _wrong_code(code)

    for _ in range(MAX_OTP_ATTEMPTS):
        assert client.post(
            "/auth/verify-email", headers=auth_headers, json={"code": wrong}
        ).status_code == 400

    # Limit reached → 429, and the correct code no longer helps.
    response = client.post("/auth/verify-email", headers=auth_headers, json={"code": code})
    assert response.status_code == 429
    assert response.json()["type"] == "too-many-attempts"
