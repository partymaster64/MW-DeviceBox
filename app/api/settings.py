"""Settings API endpoints for managing POS connection configuration."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.pos_polling import PosPollingService
from app.services.settings_store import SettingsStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings")

# Set during application startup
_settings_store: SettingsStore | None = None
_pos_service: PosPollingService | None = None


def set_dependencies(
    settings_store: SettingsStore,
    pos_service: PosPollingService,
) -> None:
    """Inject dependencies from the application lifespan."""
    global _settings_store, _pos_service  # noqa: PLW0603
    _settings_store = settings_store
    _pos_service = pos_service


def _get_store() -> SettingsStore:
    if _settings_store is None:
        raise HTTPException(status_code=503, detail="Settings not initialized")
    return _settings_store


def _get_pos_service() -> PosPollingService:
    if _pos_service is None:
        raise HTTPException(status_code=503, detail="POS service not initialized")
    return _pos_service


# --- Request / Response models ---


class PosSettingsResponse(BaseModel):
    url: str
    token_set: bool  # Don't expose the actual token
    poll_interval: int


class PosSettingsUpdate(BaseModel):
    url: str | None = None
    token: str | None = None
    poll_interval: int | None = None


class PosStatusResponse(BaseModel):
    status: str
    detail: str
    session_id: str | None = None
    scanner_connected: bool


class PosTestRequest(BaseModel):
    url: str
    token: str


class PosTestResponse(BaseModel):
    success: bool
    message: str


# --- Endpoints ---


@router.get("/pos", response_model=PosSettingsResponse)
async def get_pos_settings() -> PosSettingsResponse:
    """Get current POS connection settings."""
    store = _get_store()
    pos = store.pos
    return PosSettingsResponse(
        url=pos.url,
        token_set=bool(pos.token),
        poll_interval=pos.poll_interval,
    )


@router.put("/pos", response_model=PosSettingsResponse)
async def update_pos_settings(body: PosSettingsUpdate) -> PosSettingsResponse:
    """Update POS connection settings."""
    store = _get_store()
    updated = store.update_pos(
        url=body.url,
        token=body.token,
        poll_interval=body.poll_interval,
    )
    logger.info("POS settings updated via API")
    return PosSettingsResponse(
        url=updated.url,
        token_set=bool(updated.token),
        poll_interval=updated.poll_interval,
    )


@router.post("/pos/test", response_model=PosTestResponse)
async def test_pos_connection(body: PosTestRequest) -> PosTestResponse:
    """Test the POS API connection with the provided credentials."""
    success, message = await asyncio.to_thread(
        PosPollingService.test_connection,
        body.url.rstrip("/"),
        body.token,
    )
    return PosTestResponse(success=success, message=message)


@router.get("/pos/status", response_model=PosStatusResponse)
async def get_pos_status() -> PosStatusResponse:
    """Get the current POS polling service status."""
    service = _get_pos_service()

    # Import here to avoid circular imports
    from app.api.devices import _get_scanner

    scanner = _get_scanner()

    return PosStatusResponse(
        status=service.status,
        detail=service.status_detail,
        session_id=service.current_session_id,
        scanner_connected=scanner.is_connected,
    )
