"""Device API endpoints for listing recognized devices and their status."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.devices.barcode_scanner import BarcodeScanner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices")

# Will be set during application startup
_scanner: BarcodeScanner | None = None


def set_scanner(scanner: BarcodeScanner) -> None:
    """Set the barcode scanner instance used by the endpoints."""
    global _scanner  # noqa: PLW0603
    _scanner = scanner


def _get_scanner() -> BarcodeScanner:
    """Get the current scanner or raise an error."""
    if _scanner is None:
        raise HTTPException(
            status_code=503,
            detail="Scanner not initialized",
        )
    return _scanner


# --- Response Models ---


class DeviceInfo(BaseModel):
    name: str
    type: str
    device_path: str
    connected: bool
    session_active: bool


class DevicesResponse(BaseModel):
    devices: list[DeviceInfo]


# --- Endpoints ---


@router.get("", response_model=DevicesResponse)
async def list_devices() -> DevicesResponse:
    """List all recognized devices and their connection status."""
    scanner = _get_scanner()
    devices = [
        DeviceInfo(
            name=scanner.name,
            type="barcode_scanner",
            device_path=scanner.device_path,
            connected=scanner.is_connected,
            session_active=scanner.session_active,
        )
    ]
    return DevicesResponse(devices=devices)
