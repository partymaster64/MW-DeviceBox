import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import devices, health, info, watchtower
from app.config import settings
from app.devices.barcode_scanner import create_scanner
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown logic."""
    # Startup
    setup_logging(settings.LOG_LEVEL)
    logger.info(
        "Starting %s v%s (SCANNER_ENABLED=%s)",
        settings.DEVICE_NAME,
        settings.APP_VERSION,
        settings.SCANNER_ENABLED,
    )

    scanner = create_scanner(enabled=settings.SCANNER_ENABLED)
    scanner.start()
    devices.set_scanner(scanner)

    yield

    # Shutdown
    scanner.stop()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.DEVICE_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(info.router)
app.include_router(devices.router)
app.include_router(watchtower.router)

# Serve static files (CSS, JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the web dashboard."""
    return FileResponse(str(STATIC_DIR / "index.html"))
