"""
Security utilities — password hashing and JWT token management.

WHY BCRYPT FOR PASSWORDS:
──────────────────────────
Bcrypt is a slow hashing algorithm by design.
Fast algorithms like MD5 or SHA256 can be brute-forced.
Bcrypt's slowness makes brute-force attacks computationally expensive.

WHY JWT FOR AUTH:
──────────────────
JWT (JSON Web Token) is stateless — the server does not store sessions.
Every request carries a signed token. The server verifies the signature.
This is critical for horizontal scaling — any API server can verify
any token without talking to a shared session store.

TOKEN STRUCTURE:
─────────────────
Access token:  short-lived (30 min) — used for API requests
Refresh token: long-lived (7 days) — used to get new access tokens

This means users stay logged in for 7 days without re-entering password,
but if an access token is stolen it expires in 30 minutes.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# Bcrypt context for password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password Utilities ────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """Hashes a plain text password using bcrypt."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Utilities ─────────────────────────────────────────────────────────────

def create_access_token(user_id: str, email: str) -> str:
    """
    Creates a short-lived JWT access token.

    Payload contains:
      sub  → user_id (standard JWT subject claim)
      email → user email
      type  → token type (access vs refresh)
      exp  → expiry timestamp
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        "sub":   user_id,
        "email": email,
        "type":  "access",
        "exp":   expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(user_id: str) -> str:
    """
    Creates a long-lived JWT refresh token.
    Contains minimal data — just enough to identify the user.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    payload = {
        "sub":  user_id,
        "type": "refresh",
        "exp":  expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> Optional[dict]:
    """
    Decodes and validates a JWT token.
    Returns the payload if valid, None if invalid or expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        return None