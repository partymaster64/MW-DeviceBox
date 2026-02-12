from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/info")
async def info() -> dict:
    """Return device name and application version."""
    return {
        "device_name": settings.DEVICE_NAME,
        "version": settings.APP_VERSION,
    }
