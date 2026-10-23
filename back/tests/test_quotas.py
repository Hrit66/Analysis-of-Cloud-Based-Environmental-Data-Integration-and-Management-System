"""Quota helpers must work with both Motor and simple test doubles."""
import pytest

from app.services.quotas import get_platform_storage_used


class FakeCursor:
    def __init__(self, docs):
        self._docs = iter(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._docs)
        except StopIteration:
            raise StopAsyncIteration


class FakeDocsDb:
    def __init__(self, docs):
        self.datasets = type("Collection", (), {"docs": docs})()


class FakeMotorCollection:
    def aggregate(self, pipeline):
        raise RuntimeError("aggregation unavailable")

    def find(self, query, projection):
        return FakeCursor([
            {"file_size_bytes": 12},
            {"file_size_bytes": 30},
        ])

    def __getattr__(self, name):
        raise TypeError("Motor-style dynamic attribute access")


class FakeMotorDb:
    def __init__(self):
        self.datasets = FakeMotorCollection()


@pytest.mark.asyncio
async def test_storage_uses_fake_docs_without_motor_attribute_lookup():
    fake = FakeDocsDb([
        {"status": "completed", "file_size_bytes": 10},
        {"status": "failed", "file_size_bytes": 99},
        {"status": "processing", "file_size_bytes": 5},
    ])
    assert await get_platform_storage_used(fake) == 15


@pytest.mark.asyncio
async def test_storage_falls_back_to_find_when_aggregate_fails():
    assert await get_platform_storage_used(FakeMotorDb()) == 42
