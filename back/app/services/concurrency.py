import asyncio
from typing import Dict

# Global limit: max 2 concurrent processing jobs across all users
_GLOBAL_SEMAPHORE = asyncio.Semaphore(2)

# Per-user limit: max 1 concurrent job per user
_USER_SEMAPHORES: Dict[str, asyncio.Semaphore] = {}
_MAX_PER_USER = 1

async def acquire_upload_slot(user_id: str) -> None:
    """Acquire both global and per-user slots. Blocks until available."""
    # Get or create per-user semaphore
    user_sem = _USER_SEMAPHORES.setdefault(user_id, asyncio.Semaphore(_MAX_PER_USER))
    await user_sem.acquire()
    await _GLOBAL_SEMAPHORE.acquire()

def release_upload_slot(user_id: str) -> None:
    """Release both slots after job completes (success or failure)."""
    user_sem = _USER_SEMAPHORES.get(user_id)
    if user_sem:
        user_sem.release()
    _GLOBAL_SEMAPHORE.release()
