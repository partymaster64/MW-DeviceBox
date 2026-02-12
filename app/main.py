import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import devices, health, info, settings, watchtower
from app.config import settings as app_settings
from app.devices.barcode_scanner import BarcodeScanner
from app.devices.usb_power import UsbPowerController
from app.logging_config import setup_logging
from app.services.pos_polling import PosPollingService
from app.services.settings_store import SettingsStore

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown logic."""
    # Startup
    setup_logging(app_settings.LOG_LEVEL)
    logger.info(
        "Starting %s v%s",
        app_settings.DEVICE_NAME,
        app_settings.APP_VERSION,
    )

    # Initialize settings store (persistent JSON)
    settings_store = SettingsStore()

    # Initialize USB power controller (method from settings)
    usb_power = UsbPowerController(method=settings_store.usb_power.method)

    # Initialize barcode scanner (device discovery + session-based reading)
    scanner = BarcodeScanner()
    scanner.set_power_controller(usb_power)
    scanner.start()
    devices.set_scanner(scanner)

    # Initialize POS polling service
    pos_service = PosPollingService(
        scanner=scanner,
        settings_store=settings_store,
    )
    pos_service.start()

    # Inject dependencies into settings API
    settings.set_dependencies(settings_store, pos_service, usb_power)

    yield

    # Shutdown
    pos_service.stop()
    scanner.stop()
    logger.info("Shutdown complete")


app = FastAPI(
    title=app_settings.DEVICE_NAME,
    version=app_settings.APP_VERSION,
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(info.router)
app.include_router(devices.router)
app.include_router(watchtower.router)
app.include_router(settings.router)

# Serve static files (CSS, JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the web dashboard."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/settings", include_in_schema=False)
async def settings_page() -> FileResponse:
    """Serve the settings page."""
    return FileResponse(str(STATIC_DIR / "settings.html"))
