import pytest
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorDatabase
from unittest.mock import AsyncMock, MagicMock

from app.main import app
from app.database import db


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def mock_db():
    """Mock database for unit tests."""
    mock = AsyncMock(spec=AsyncIOMotorDatabase)
    return mock


@pytest.fixture
def sample_air_quality_df():
    import pandas as pd
    import numpy as np
    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=100, freq='H'),
        'location': ['Station A'] * 100,
        'pm25': np.random.normal(50, 10, 100),
        'pm10': np.random.normal(80, 15, 100),
        'no2': np.random.normal(30, 5, 100),
        'so2': np.random.normal(10, 2, 100),
        'co': np.random.normal(1.0, 0.2, 100),
        'o3': np.random.normal(40, 8, 100),
    })


@pytest.fixture
def sample_user_data():
    return {
        "email": "test@example.com",
        "password": "test_password_123",
        "full_name": "Test User",
    }