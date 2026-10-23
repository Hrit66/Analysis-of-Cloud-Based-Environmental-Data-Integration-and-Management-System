from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGO_URI: str
    DB_NAME: str = "aqi_db"
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_REUSE_GRACE_SECONDS: int = 20
    MFA_CHALLENGE_EXPIRE_MINUTES: int = 5
    EMAIL_VERIFICATION_EXPIRE_MINUTES: int = 30
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    INVITE_EXPIRE_DAYS: int = 7
    FRONTEND_URL: str = "http://localhost:5173"
    TERMS_VERSION: str = "2026-10"
    ACADEMIC_DOMAIN_ALLOWLIST: str = "ac.in,edu,edu.in"
    INSTITUTIONS_JSON: str = ""
    GOVT_DOMAIN_SUFFIXES: str = "gov.in,nic.in"
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "no-reply@envplatform.local"
    SMTP_STARTTLS: bool = True
    FIRST_ADMIN_EMAIL: Optional[str] = None
    FIRST_ADMIN_PASSWORD: Optional[str] = None
    REGISTER_RATE_LIMIT: int = 5
    REGISTER_RATE_WINDOW_SECONDS: int = 900
    ORG_APPLY_RATE_LIMIT: int = 10
    ORG_APPLY_RATE_WINDOW_SECONDS: int = 900
    RESEND_RATE_LIMIT: int = 3
    RESEND_RATE_WINDOW_SECONDS: int = 900
    LOGIN_RATE_LIMIT: int = 30
    LOGIN_RATE_WINDOW_SECONDS: int = 900
    INVITE_RATE_LIMIT: int = 10
    INVITE_RATE_WINDOW_SECONDS: int = 3600
    PASSWORD_MIN_LENGTH: int = 10
    LOCKOUT_THRESHOLD: int = 5
    LOCKOUT_MINUTES: int = 15
    COOKIE_SECURE: Optional[bool] = None
    COOKIE_DOMAIN: Optional[str] = None
    COOKIE_SAMESITE: str = "lax"
    PLATFORM_ADMIN_EMAILS: str = ""
    FRONTEND_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
    ALLOW_ANONYMOUS_UPLOAD: bool = False
    ENVIRONMENT: str = "development"

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
