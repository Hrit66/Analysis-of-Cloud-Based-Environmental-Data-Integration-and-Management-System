from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import db

router = APIRouter(prefix="/health", tags=["health"])


def get_database() -> AsyncIOMotorDatabase:
    return db.db


@router.get("")
async def health_check(database: AsyncIOMotorDatabase = Depends(get_database)):
    try:
        await database.command("ping")
        db_status = "connected"
    except Exception as e:
        db_status = f"disconnected: {str(e)}"
    
    return {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "database": db_status,
    }


@router.get("/ready")
async def readiness_check(database: AsyncIOMotorDatabase = Depends(get_database)):
    try:
        await database.command("ping")
        return {"ready": True}
    except:
        return {"ready": False}