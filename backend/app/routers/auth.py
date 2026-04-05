"""
Authentication endpoints.

POST /auth/register → Create new user account
POST /auth/login    → Get access + refresh tokens
POST /auth/refresh  → Get new access token using refresh token
GET  /auth/me       → Get current user profile
"""

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from app.db.queries.users import create_user, get_user_by_email, get_user_by_id
from app.dependencies import get_db
from app.models.schemas import (
    TokenResponse,
    UserCreate,
    UserResponse,
)
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter()

# OAuth2 scheme — tells FastAPI where to find the token
# tokenUrl is the login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Dependency — Get Current User ─────────────────────────────────────────────

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: asyncpg.Pool = Depends(get_db),
) -> dict:
    """
    FastAPI dependency that extracts and validates the current user
    from the JWT token in the Authorization header.

    Usage in any protected endpoint:
        async def my_endpoint(
            current_user: dict = Depends(get_current_user)
        ):
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if not payload:
        raise credentials_exception

    if payload.get("type") != "access":
        raise credentials_exception

    user_id: str = payload.get("sub")
    if not user_id:
        raise credentials_exception

    user = await get_user_by_id(db, user_id)
    if not user:
        raise credentials_exception

    return user


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    payload: UserCreate,
    db: asyncpg.Pool = Depends(get_db),
):
    existing = await get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await create_user(db, {
        "email":           payload.email,
        "hashed_password": hash_password(payload.password),
        "full_name":       payload.full_name,
        "is_admin":        False,
    })

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and get tokens",
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: asyncpg.Pool = Depends(get_db),
):
    """
    OAuth2 password flow.
    Expects form data with username (email) and password.
    Returns access token + refresh token.
    """
    user = await get_user_by_email(db, form_data.username)

    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    access_token  = create_access_token(str(user["id"]), user["email"])
    refresh_token = create_refresh_token(str(user["id"]))

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
    }


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(
    token: str,
    db: asyncpg.Pool = Depends(get_db),
):
    payload = decode_token(token)

    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_id = payload.get("sub")
    user    = await get_user_by_id(db, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    access_token  = create_access_token(str(user["id"]), user["email"])
    refresh_token = create_refresh_token(str(user["id"]))

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
    }


@router.get(
    "/me",
    summary="Get current user profile",
)
async def get_me(
    current_user: dict = Depends(get_current_user),
):
    return {
        "id":         str(current_user["id"]),
        "email":      current_user["email"],
        "full_name":  current_user["full_name"],
        "is_admin":   current_user.get("is_admin", False),
        "created_at": current_user["created_at"].isoformat(),
    }