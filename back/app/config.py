from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    MONGO_URI: str
    DB_NAME: str = "aqi_db"
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ENVIRONMENT: str = "development"

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()