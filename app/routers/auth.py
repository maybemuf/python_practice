from typing import Annotated

from fastapi import APIRouter, Body, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic.networks import EmailStr

from app.dependencies import SessionDep
from app.dependencies.user import UserDep
from app.models import UserPublic
from app.models.change_password import ChangePasswordBody, ResetPasswordBody
from app.models.exceptions import error_responses
from app.models.otp import OtpRawCodeStr
from app.models.user import AuthResponse, UserCreate
from app.services import auth_service

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.post("/register", responses=error_responses(409, 422))
def register_user(body: UserCreate, session: SessionDep) -> AuthResponse:
    """Registers a user and immediately issues a token pair (access + refresh)."""
    return auth_service.register(session, body)


@router.post("/login", responses=error_responses(401, 422))
def login_user(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
) -> AuthResponse:
    """Login with email + password (form-data, OAuth2). Returns a token pair."""
    return auth_service.login(session, form_data.username, form_data.password)


@router.post("/refresh", responses=error_responses(401))
def rotate_refresh_token(
    refresh_token: Annotated[str, Body(embed=True)],
    session: SessionDep,
) -> AuthResponse:
    """Rotates the refresh token: the old one is revoked, a new one is issued.
    Reusing a revoked token revokes all of the user's tokens."""
    return auth_service.rotate_refresh(session, refresh_token)


@router.post("/change-password", responses=error_responses(400, 401, 422))
def change_user_password(
    body: ChangePasswordBody,
    session: SessionDep,
    current_user: UserDep,
) -> AuthResponse:
    """Password change by an authenticated user. Revokes all previous refresh tokens."""
    return auth_service.change_password(session, current_user, body)


@router.post("/request-reset-password", responses=error_responses(422))
def request_reset_user_password(
    email: Annotated[EmailStr, Body(embed=True)],
    session: SessionDep,
):
    """Initiates a password reset. The response is identical for any email
    (anti-enumeration) — a code is sent only if the account exists."""
    auth_service.request_reset_password(session, email)
    return {"message": "If an account with that email exists, a reset code has been sent."}


@router.post("/reset-password", responses=error_responses(400, 422, 429))
def reset_user_password(body: ResetPasswordBody, session: SessionDep) -> AuthResponse:
    """Password reset via OTP code. Success also verifies the email."""
    return auth_service.reset_password(session, body)


@router.post("/request-verify-email", responses=error_responses(401))
def send_verify_email_otp(session: SessionDep, user: UserDep):
    """Sends an OTP code to verify the current user's email."""
    auth_service.request_verify_email(session, user)


@router.post("/verify-email", responses=error_responses(400, 401, 422, 429))
def verify_user_email(
    code: Annotated[OtpRawCodeStr, Body(embed=True)],
    session: SessionDep,
    user: UserDep,
) -> UserPublic:
    """Verifies the email using an OTP code."""
    return auth_service.verify_email(session, user, code)
