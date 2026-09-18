import os
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
# pyrefly: ignore [missing-import]
from fastapi.security import OAuth2PasswordBearer
# pyrefly: ignore [missing-import]
from fastapi import Depends, HTTPException, status
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session
from app.deps import get_db
from app import models

from app.config import load_env

load_env()

# SECRET_KEY is required for signing and verifying access tokens. It must be
# provided in the environment or backend/.env and must be strong (at least
# 32 characters and not a known placeholder). Startup fails loudly if it is
# missing or weak so tokens are never signed with a predictable key.
_WEAK_SECRET_PLACEHOLDERS = frozenset(
    {
        "supersecretkey",
        "change-me-to-a-long-random-secret",
        "change-me-strong-password",
    }
)
MIN_SECRET_KEY_LENGTH = 32


def _require_secret_key() -> str:
    key = os.getenv("SECRET_KEY")
    if not key:
        raise RuntimeError(
            "SECRET_KEY is not set. Set a strong random SECRET_KEY in "
            "backend/.env or the process environment, e.g. generated with "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"`."
        )
    if key.strip().lower() in _WEAK_SECRET_PLACEHOLDERS:
        raise RuntimeError(
            "SECRET_KEY is set to a known placeholder. Generate a strong "
            "random SECRET_KEY in backend/.env, e.g. `python -c \"import "
            "secrets; print(secrets.token_hex(32))\"`."
        )
    if len(key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            f"SECRET_KEY is too weak ({len(key)} characters). Use at least "
            f"{MIN_SECRET_KEY_LENGTH} characters."
        )
    return key


SECRET_KEY = _require_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended. Contact support.",
        )
    return user

class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: models.User = Depends(get_current_user)):
        if current_user.role.value not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource"
            )
        return current_user
