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


class DevicesResponse(BaseModel):
    devices: list[DeviceInfo]


class ScanEntryModel(BaseModel):
    barcode: str
    timestamp: str
    device: str


class LastScanResponse(BaseModel):
    scan: ScanEntryModel | None


class ScanHistoryResponse(BaseModel):
    scans: list[ScanEntryModel]
    total: int


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
        )
    ]
    return DevicesResponse(devices=devices)


@router.get("/scanner/last-scan", response_model=LastScanResponse)
async def get_last_scan() -> LastScanResponse:
    """Get the last scanned barcode."""
    scanner = _get_scanner()
    last = scanner.last_scan
    if last:
        return LastScanResponse(
            scan=ScanEntryModel(
                barcode=last.barcode,
                timestamp=last.timestamp,
                device=last.device,
            )
        )
    return LastScanResponse(scan=None)


@router.get("/scanner/history", response_model=ScanHistoryResponse)
async def get_scan_history() -> ScanHistoryResponse:
    """Get the barcode scan history (newest first)."""
    scanner = _get_scanner()
    history = scanner.history
    return ScanHistoryResponse(
        scans=[
            ScanEntryModel(
                barcode=e.barcode,
                timestamp=e.timestamp,
                device=e.device,
            )
            for e in history
        ],
        total=len(history),
    )
