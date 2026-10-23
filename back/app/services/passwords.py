"""Password policy helpers shared by every account-creation path."""
from __future__ import annotations

from fastapi import HTTPException

from app.config import get_settings

COMMON_PASSWORDS = {
    "1234567890", "123456789", "12345678", "password", "password1", "password123",
    "qwerty123", "qwertyuiop", "letmein123", "welcome123", "admin123", "admin1234",
    "iloveyou", "monkey123", "dragon123", "football", "baseball", "sunshine",
    "princess", "superman", "trustno1", "abc123456", "passw0rd", "p@ssw0rd",
    "test1234", "test@1234", "changeme", "changeme123", "secret123", "hello123",
    "india123", "bharat123", "student123", "researcher123", "college123",
}


def validate_password(password: str) -> str:
    settings = get_settings()
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters.",
        )
    if len(password) > 128:
        raise HTTPException(status_code=400, detail="Password must be 128 characters or fewer.")
    normalized = password.strip().lower()
    if normalized in COMMON_PASSWORDS:
        raise HTTPException(status_code=400, detail="Choose a less common password.")
    return password
