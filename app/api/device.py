import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.devices.gpio_device import GPIODevice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/device")

# Will be set during application startup
_gpio_device: GPIODevice | None = None


def set_gpio_device(device: GPIODevice) -> None:
    """Set the GPIO device instance used by the endpoints."""
    global _gpio_device  # noqa: PLW0603
    _gpio_device = device


def _get_device() -> GPIODevice:
    """Get the current GPIO device or raise an error."""
    if _gpio_device is None:
        raise HTTPException(
            status_code=503,
            detail="GPIO device not initialized",
        )
    return _gpio_device


# --- Request / Response Models ---


class GPIOReadRequest(BaseModel):
    pin: int = Field(..., ge=0, description="GPIO pin number (BCM)")


class GPIOReadResponse(BaseModel):
    pin: int
    value: int


class GPIOWriteRequest(BaseModel):
    pin: int = Field(..., ge=0, description="GPIO pin number (BCM)")
    value: int = Field(..., ge=0, le=1, description="Pin value (0 or 1)")


class GPIOWriteResponse(BaseModel):
    success: bool


# --- Endpoints ---


@router.post("/gpio/read", response_model=GPIOReadResponse)
async def gpio_read(request: GPIOReadRequest) -> GPIOReadResponse:
    """Read the value of a GPIO pin."""
    device = _get_device()
    try:
        value = device.read_pin(request.pin)
        return GPIOReadResponse(pin=request.pin, value=value)
    except Exception as exc:
        logger.error("Failed to read GPIO pin %d: %s", request.pin, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read GPIO pin {request.pin}: {exc}",
        ) from exc


@router.post("/gpio/write", response_model=GPIOWriteResponse)
async def gpio_write(request: GPIOWriteRequest) -> GPIOWriteResponse:
    """Write a value to a GPIO pin."""
    device = _get_device()
    try:
        device.write_pin(request.pin, request.value)
        return GPIOWriteResponse(success=True)
    except Exception as exc:
        logger.error(
            "Failed to write GPIO pin %d with value %d: %s",
            request.pin,
            request.value,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write GPIO pin {request.pin}: {exc}",
        ) from exc
