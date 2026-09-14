import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import bcrypt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserSession

# Session lifetime from environment variable (default 24 hours)
SESSION_EXPIRE_HOURS = int(os.getenv("SESSION_EXPIRE_HOURS", "24"))

# HTTPBearer scheme provides the 'Authorize' button in Swagger UI (/docs)
security = HTTPBearer(
    auto_error=False,
    description="Enter your session token obtained from /api/v1/auth/login",
)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_user_session(db: Session, user: User) -> UserSession:
    """Create a new database-backed session for a user."""
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_EXPIRE_HOURS)

    user_session = UserSession(
        session_token=token,
        user_id=user.id,
        expires_at=expires_at,
        is_active=True,
    )
    db.add(user_session)
    db.commit()
    db.refresh(user_session)
    return user_session


def terminate_session(db: Session, session_token: str) -> bool:
    """Deactivate an active session token."""
    session_record = (
        db.query(UserSession)
        .filter(UserSession.session_token == session_token, UserSession.is_active.is_(True))
        .first()
    )
    if session_record:
        session_record.is_active = False
        db.commit()
        return True
    return False


def get_current_session(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db),
) -> Tuple[User, UserSession]:
    """Dependency that verifies the user session token.
    
    Extracts Bearer token from the Authorization header.
    Validates that the session exists, is marked active, and has not expired.
    Raises HTTP 401 Unauthorized if invalid or missing.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Please log in first.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    session_record = (
        db.query(UserSession)
        .filter(UserSession.session_token == token)
        .first()
    )

    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not session_record.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been terminated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(timezone.utc)
    # Ensure timezone comparison compatibility
    session_expiry = session_record.expires_at
    if session_expiry.tzinfo is None:
        session_expiry = session_expiry.replace(tzinfo=timezone.utc)

    if session_expiry < now:
        session_record.is_active = False
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == session_record.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or disabled.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user, session_record


def require_authenticated_user(
    auth_data: Tuple[User, UserSession] = Depends(get_current_session),
) -> User:
    """Dependency returning the authenticated User object."""
    user, _ = auth_data
    return user
