"""Shared guards so analytics endpoints never answer for the wrong dataset."""
from typing import Optional

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.authz import require_dataset_access
from app.services.pipeline_interface import derive_capabilities


async def require_dataset(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    capability: Optional[str] = None,
    *,
    user=None,
    write: bool = False,
) -> dict:
    dataset = await require_dataset_access(database, dataset_id, user, write=write)

    if capability:
        capabilities = dataset.get("capabilities") or derive_capabilities(
            dataset.get("original_columns") or [], dataset.get("dataset_type")
        )
        if capability not in capabilities:
            raise HTTPException(status_code=400, detail=f"Dataset has no {capability} data")

    return dataset
