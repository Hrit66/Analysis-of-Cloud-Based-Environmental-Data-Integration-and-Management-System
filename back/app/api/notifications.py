from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

from app.api.auth import get_database, get_current_active_user
from app.models.user import UserInDB
from app.services import notifications as notif_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    cursor: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserInDB = Depends(get_current_active_user),
):
    return await notif_service.list_notifications(
        database, str(current_user.id), unread_only, cursor, limit
    )


@router.get("/unread-count")
async def get_unread_count(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserInDB = Depends(get_current_active_user),
):
    count = await notif_service.get_unread_count(database, str(current_user.id))
    return {"count": count}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserInDB = Depends(get_current_active_user),
):
    try:
        ObjectId(notification_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid notification ID")
    ok = await notif_service.mark_read(database, str(current_user.id), notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found or already read")
    return {"message": "Marked as read"}


@router.post("/read-all")
async def mark_all_read(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserInDB = Depends(get_current_active_user),
):
    count = await notif_service.mark_all_read(database, str(current_user.id))
    return {"marked": count}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserInDB = Depends(get_current_active_user),
):
    try:
        ObjectId(notification_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid notification ID")
    ok = await notif_service.delete_notification(database, str(current_user.id), notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Deleted"}


@router.get("/preferences")
async def get_preferences(
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserInDB = Depends(get_current_active_user),
):
    prefs = await notif_service.get_preferences(database, str(current_user.id))
    return {"preferences": prefs}


@router.put("/preferences")
async def update_preferences(
    updates: dict,
    database: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserInDB = Depends(get_current_active_user),
):
    # Validate keys
    from app.services.notifications import NOTIFICATION_TYPES
    for key in updates:
        if key not in NOTIFICATION_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown notification type: {key}")
        val = updates[key]
        if not isinstance(val, dict):
            raise HTTPException(status_code=400, detail=f"Preference for {key} must be an object")
        if "in_app" in val and not isinstance(val["in_app"], bool):
            raise HTTPException(status_code=400, detail="in_app must be boolean")
        if "email" in val and not isinstance(val["email"], bool):
            raise HTTPException(status_code=400, detail="email must be boolean")

    updated = await notif_service.update_preferences(database, str(current_user.id), updates)
    return {"preferences": updated}
