import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum number of scans to keep in history
MAX_HISTORY = 100


@dataclass
class ScanEntry:
    """A single barcode scan result."""

    barcode: str
    timestamp: str
    device: str


@dataclass
class BarcodeScanner:
    """Manages a USB barcode scanner running in a background thread."""

    device_path: str = "/dev/hidraw0"
    name: str = "Datalogic Touch 65"
    _running: bool = field(default=False, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _history: list[ScanEntry] = field(default_factory=list, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)

    def start(self) -> None:
        """Start the background scanner thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._scan_loop,
            daemon=True,
            name=f"scanner-{self.device_path}",
        )
        self._thread.start()
        logger.info("Barcode scanner started on %s", self.device_path)

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
        """Background loop that reads barcodes from the HID device."""
        while self._running:
            try:
                if not Path(self.device_path).exists():
                    if self._connected:
                        logger.warning("Scanner device %s disconnected", self.device_path)
                        self._connected = False
                    time.sleep(2)
                    continue

                self._connected = True
                logger.info("Scanner device %s connected, reading...", self.device_path)
                self._read_device()

            except PermissionError:
                logger.error(
                    "Permission denied for %s - ensure the container has access",
                    self.device_path,
                )
                self._connected = False
                time.sleep(5)
            except Exception as exc:
                logger.error("Scanner error on %s: %s", self.device_path, exc)
                self._connected = False
                time.sleep(2)

    def _read_device(self) -> None:
        """Read barcode data from the HID device using the usb_barcode_scanner library."""
        try:
            from usb_barcode_scanner.scanner import BarcodeReader

            reader = BarcodeReader(self.device_path)

            while self._running:
                if not Path(self.device_path).exists():
                    logger.warning("Scanner device %s lost", self.device_path)
                    self._connected = False
                    return

                try:
                    barcode = reader.read_barcode()
                except Exception:
                    # Device was disconnected during read
                    self._connected = False
                    return

                if barcode and barcode.strip():
                    barcode = barcode.strip()
                    entry = ScanEntry(
                        barcode=barcode,
                        timestamp=datetime.now().isoformat(timespec="seconds"),
                        device=self.name,
                    )
                    with self._lock:
                        self._history.append(entry)
                        if len(self._history) > MAX_HISTORY:
                            self._history = self._history[-MAX_HISTORY:]
                    logger.info("Barcode scanned: %s", barcode)

        except ImportError:
            logger.error(
                "usb_barcode_scanner library not installed. "
                "Install with: pip install usb-barcode-scanner-julz"
            )
            self._connected = False


class MockBarcodeScanner(BarcodeScanner):
    """Mock scanner for development without a real scanner device."""

    def __init__(self) -> None:
        super().__init__(device_path="/dev/null", name="Mock Scanner")
        self._connected = True
        # Add a sample scan entry
        self._history = [
            ScanEntry(
                barcode="4006381333931",
                timestamp=datetime.now().isoformat(timespec="seconds"),
                device="Mock Scanner",
            )
        ]
        logger.info("MockBarcodeScanner initialized")

    def start(self) -> None:
        logger.info("MockBarcodeScanner started (no real device)")

    def stop(self) -> None:
        logger.info("MockBarcodeScanner stopped")


def create_scanner(enabled: bool, device_path: str, name: str) -> BarcodeScanner:
    """Factory function to create the appropriate scanner instance.

    Args:
        enabled: If True, creates a real scanner. If False, creates a mock.
        device_path: Path to the HID device (e.g. /dev/hidraw0).
        name: Display name of the scanner.

    Returns:
        A BarcodeScanner instance.
    """
    if enabled:
        if Path(device_path).exists():
            return BarcodeScanner(device_path=device_path, name=name)
        else:
            logger.warning(
                "SCANNER_ENABLED is True but %s not found. Using real scanner "
                "anyway (will connect when device appears).",
                device_path,
            )
            return BarcodeScanner(device_path=device_path, name=name)
    return MockBarcodeScanner()
