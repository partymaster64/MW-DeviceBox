"""USB barcode scanner with session-based activation.

The scanner thread always runs for device auto-discovery (so the GUI
can show connection status), but only reads barcodes when a POS scan
session is active.  When no session is active, the HID buffer is
periodically flushed so stale data does not leak into the next session.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.devices.hid_reader import (
    HID_REPORT_SIZE,
    SCANCODE_ENTER,
    SHIFT_MASK,
    _SCANCODE_MAP,
    _SCANCODE_MAP_SHIFTED,
    flush_buffer,
    read_report_with_timeout,
)
from app.devices.usb_discovery import find_barcode_scanner

logger = logging.getLogger(__name__)

# How often to re-scan for the device when not connected (seconds)
DISCOVERY_INTERVAL = 3

# How often to check for session changes when device is connected but idle
IDLE_CHECK_INTERVAL = 0.5


@dataclass
class ScanEntry:
    """A single barcode scan result."""

    barcode: str
    timestamp: str
    device: str


@dataclass
class BarcodeScanner:
    """Manages a USB barcode scanner with auto-discovery and session-based reading."""

    _running: bool = field(default=False, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _device_path: str | None = field(default=None, init=False, repr=False)
    _device_name: str = field(default="Barcode Scanner", init=False, repr=False)

    # Session state
    _session_active: bool = field(default=False, init=False, repr=False)
    _session_id: str | None = field(default=None, init=False, repr=False)
    _on_barcode: Callable[[ScanEntry], None] | None = field(
        default=None, init=False, repr=False
    )

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
        self._session_active = False
        logger.info("Barcode scanner stopped")

    # --- Session control ---

    def activate_session(
        self,
        session_id: str,
        on_barcode: Callable[[ScanEntry], None],
    ) -> None:
        """Activate a scan session.

        When active, scanned barcodes are forwarded via the callback.

        Args:
            session_id: Unique session identifier from the POS system.
            on_barcode: Callback invoked with each ScanEntry.
        """
        with self._lock:
            self._session_id = session_id
            self._on_barcode = on_barcode
            self._session_active = True
        logger.info("Scan session activated: %s", session_id)

    def deactivate_session(self) -> None:
        """Deactivate the current scan session."""
        with self._lock:
            was_active = self._session_active
            self._session_active = False
            self._session_id = None
            self._on_barcode = None
        if was_active:
            logger.info("Scan session deactivated")

    # --- Properties ---

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
    def session_active(self) -> bool:
        """Whether a scan session is currently active."""
        return self._session_active

    @property
    def session_id(self) -> str | None:
        """Current session ID, or None."""
        return self._session_id

    # --- Background loop ---

    def _scan_loop(self) -> None:
        """Background loop: discover scanner, manage device lifecycle."""
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

                # Manage the device (discovery + session-based reading)
                self._manage_device(discovered.hidraw_path)

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

    def _manage_device(self, device_path: str) -> None:
        """Keep the HID device open; read barcodes only during active sessions.

        This method holds the device file open so we can:
        - Flush stale data when idle
        - Immediately start reading when a session becomes active
        - Detect device disconnects promptly
        """
        logger.info("Managing scanner device %s", device_path)

        try:
            with open(device_path, "rb") as device:
                barcode_chars: list[str] = []

                while self._running:
                    # Check device still exists
                    if not Path(device_path).exists():
                        logger.warning("Scanner device %s lost", device_path)
                        self._connected = False
                        self._device_path = None
                        return

                    if not self._session_active:
                        # No active session: flush any buffered data and wait
                        flushed = flush_buffer(device)
                        if flushed > 0:
                            logger.debug("Flushed %d stale HID reports", flushed)
                        barcode_chars.clear()
                        time.sleep(IDLE_CHECK_INTERVAL)
                        continue

                    # Session is active: read with timeout
                    report = read_report_with_timeout(device, timeout=1.0)

                    if report is None:
                        # Timeout or disconnect -- check if device still exists
                        if not Path(device_path).exists():
                            logger.warning("Scanner device %s lost during read", device_path)
                            self._connected = False
                            self._device_path = None
                            return
                        # Just a timeout, loop back to check flags
                        continue

                    modifier = report[0]
                    scancode = report[2]

                    # Skip key release reports
                    if scancode == 0:
                        continue

                    # Enter key = barcode complete
                    if scancode == SCANCODE_ENTER:
                        barcode = "".join(barcode_chars).strip()
                        barcode_chars.clear()

                        if barcode:
                            entry = ScanEntry(
                                barcode=barcode,
                                timestamp=datetime.now().isoformat(timespec="seconds"),
                                device=self._device_name,
                            )
                            logger.info("Barcode scanned: %s", barcode)

                            # Forward via callback
                            with self._lock:
                                callback = self._on_barcode
                            if callback:
                                try:
                                    callback(entry)
                                except Exception as exc:
                                    logger.error("Barcode callback error: %s", exc)
                        continue

                    # Decode character
                    shifted = bool(modifier & SHIFT_MASK)
                    char_map = _SCANCODE_MAP_SHIFTED if shifted else _SCANCODE_MAP
                    char = char_map.get(scancode)
                    if char:
                        barcode_chars.append(char)

        except PermissionError:
            logger.error(
                "Permission denied reading %s - ensure container has device access",
                device_path,
            )
            self._connected = False
            self._device_path = None
        except OSError as exc:
            logger.warning("Scanner device error: %s", exc)
            self._connected = False
            self._device_path = None
