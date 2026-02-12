import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.devices.usb_discovery import find_barcode_scanner

logger = logging.getLogger(__name__)

# Maximum number of scans to keep in history
MAX_HISTORY = 100

# How often to re-scan for the device when not connected (seconds)
DISCOVERY_INTERVAL = 3


@dataclass
class ScanEntry:
    """A single barcode scan result."""

    barcode: str
    timestamp: str
    device: str


@dataclass
class BarcodeScanner:
    """Manages a USB barcode scanner with auto-discovery and background reading."""

    _running: bool = field(default=False, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _history: list[ScanEntry] = field(default_factory=list, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _device_path: str | None = field(default=None, init=False, repr=False)
    _device_name: str = field(default="Barcode Scanner", init=False, repr=False)

    def start(self) -> None:
        """Start the background scanner thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._scan_loop,
            daemon=True,
            name="barcode-scanner",
        )
        self._thread.start()
        logger.info("Barcode scanner thread started (auto-discovery active)")

    def stop(self) -> None:
        """Stop the background scanner thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._connected = False
        logger.info("Barcode scanner stopped")

    @property
    def is_connected(self) -> bool:
        """Check if the scanner device is currently connected."""
        return self._connected

    @property
    def device_path(self) -> str:
        """Current device path or 'auto' if not yet discovered."""
        return self._device_path or "auto"

    @property
    def name(self) -> str:
        """Display name of the scanner."""
        return self._device_name

    @property
    def last_scan(self) -> ScanEntry | None:
        """Get the most recent scan entry."""
        with self._lock:
            return self._history[-1] if self._history else None

    @property
    def history(self) -> list[ScanEntry]:
        """Get a copy of the scan history (newest first)."""
        with self._lock:
            return list(reversed(self._history))

    def _scan_loop(self) -> None:
        """Background loop: discover scanner, read barcodes, reconnect on disconnect."""
        while self._running:
            try:
                # Auto-discover the scanner
                discovered = find_barcode_scanner()

                if discovered is None:
                    if self._connected:
                        logger.warning("Scanner disconnected")
                        self._connected = False
                        self._device_path = None
                    time.sleep(DISCOVERY_INTERVAL)
                    continue

                self._device_path = discovered.hidraw_path
                self._device_name = discovered.name
                self._connected = True
                logger.info(
                    "Scanner found: %s at %s",
                    discovered.name,
                    discovered.hidraw_path,
                )

                # Read barcodes until device disconnects
                self._read_device(discovered.hidraw_path)

            except PermissionError:
                logger.error(
                    "Permission denied for %s - ensure the container has device access",
                    self._device_path,
                )
                self._connected = False
                time.sleep(5)
            except Exception as exc:
                logger.error("Scanner error: %s", exc)
                self._connected = False
                time.sleep(DISCOVERY_INTERVAL)

    def _read_device(self, device_path: str) -> None:
        """Read barcode data from the HID device using the usb_barcode_scanner library."""
        try:
            from usb_barcode_scanner.scanner import BarcodeReader
        except ImportError:
            logger.error(
                "usb_barcode_scanner library not installed. "
                "Install with: pip install usb-barcode-scanner-julz. "
                "Scanner thread will stop."
            )
            self._connected = False
            self._running = False
            return

        try:
            reader = BarcodeReader(device_path)
        except Exception as exc:
            logger.error("Failed to open scanner at %s: %s", device_path, exc)
            self._connected = False
            return

        while self._running:
            # Check if device still exists
            if not Path(device_path).exists():
                logger.warning("Scanner device %s lost", device_path)
                self._connected = False
                self._device_path = None
                return

            try:
                barcode = reader.read_barcode()
            except Exception:
                # Device was disconnected during read
                self._connected = False
                self._device_path = None
                return

            if barcode and barcode.strip():
                barcode = barcode.strip()
                entry = ScanEntry(
                    barcode=barcode,
                    timestamp=datetime.now().isoformat(timespec="seconds"),
                    device=self._device_name,
                )
                with self._lock:
                    self._history.append(entry)
                    if len(self._history) > MAX_HISTORY:
                        self._history = self._history[-MAX_HISTORY:]
                logger.info("Barcode scanned: %s", barcode)
