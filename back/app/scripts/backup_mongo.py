#!/usr/bin/env python3
"""
MongoDB backup script using mongodump.
Records backup status in system_status collection.
Run via cron or scheduler.
"""
import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import get_settings

async def run_backup() -> dict:
    settings = get_settings()
    uri = settings.MONGO_URI
    db_name = settings.DB_NAME

    # Backup directory
    backup_dir = os.getenv("BACKUP_DIR", "/tmp/mongo_backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = os.path.join(backup_dir, f"{db_name}_{timestamp}.archive.gz")

    # Run mongodump
    cmd = [
        "mongodump",
        f"--uri={uri}",
        f"--archive={archive_path}",
        "--gzip",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"mongodump failed: {result.stderr}")

        size = os.path.getsize(archive_path)

        # Record success in DB
        client = AsyncIOMotorClient(uri)
        db = client[db_name]
        await db.system_status.update_one(
            {"_id": "backup"},
            {"$set": {
                "last_backup_at": datetime.now(timezone.utc),
                "last_backup_path": archive_path,
                "last_backup_size_bytes": size,
                "last_backup_status": "success",
                "last_backup_error": None,
            }},
            upsert=True,
        )
        client.close()

        print(f"Backup successful: {archive_path} ({size / 1024 / 1024:.1f} MB)")
        return {"status": "success", "path": archive_path, "size_bytes": size}

    except Exception as exc:
        # Record failure
        try:
            client = AsyncIOMotorClient(uri)
            db = client[db_name]
            await db.system_status.update_one(
                {"_id": "backup"},
                {"$set": {
                    "last_backup_at": datetime.now(timezone.utc),
                    "last_backup_status": "failed",
                    "last_backup_error": str(exc),
                }},
                upsert=True,
            )
            client.close()
        except Exception:
            pass
        print(f"Backup failed: {exc}", file=sys.stderr)
        return {"status": "failed", "error": str(exc)}


if __name__ == "__main__":
    asyncio.run(run_backup())
