import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import device, health, info
from app.config import settings
from app.devices.gpio_device import get_gpio_device
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown logic."""
    # Startup
    setup_logging(settings.LOG_LEVEL)
    logger.info(
        "Starting %s v%s (GPIO_ENABLED=%s)",
        settings.DEVICE_NAME,
        settings.APP_VERSION,
        settings.GPIO_ENABLED,
    )

    gpio_device = get_gpio_device(settings.GPIO_ENABLED)
    device.set_gpio_device(gpio_device)

    yield

    # Shutdown
    gpio_device.cleanup()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.DEVICE_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(info.router)
app.include_router(device.router)

# Serve static files (CSS, JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the web dashboard."""
    return FileResponse(str(STATIC_DIR / "index.html"))
