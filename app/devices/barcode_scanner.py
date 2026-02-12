"""USB barcode scanner with session-based activation and USB power control.

The scanner thread runs in the background:
1. On startup, discovers the scanner to learn its USB device ID, then
   powers off the USB port (standby).
2. When a POS scan session activates, powers on the USB port, waits for
   device discovery, and reads barcodes until the session ends.
3. When the session deactivates, powers off the USB port again.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.devices.hid_reader import (
    SCANCODE_ENTER,
    SHIFT_MASK,
    _SCANCODE_MAP,
    _SCANCODE_MAP_SHIFTED,
    flush_buffer,
    read_report_with_timeout,
)
from app.devices.usb_discovery import find_barcode_scanner
from app.devices.usb_power import UsbPowerController

logger = logging.getLogger(__name__)

# How often to re-scan for the device when not connected (seconds)
DISCOVERY_INTERVAL = 3

# How long to wait after powering on before starting discovery (seconds)
POWER_ON_SETTLE_TIME = 1.5

# How often to check for session changes when idle
IDLE_CHECK_INTERVAL = 0.5

# Max discovery attempts after power on
MAX_DISCOVERY_ATTEMPTS = 5


@dataclass
class ScanEntry:
    """A single barcode scan result."""

    barcode: str
    timestamp: str
    device: str


@dataclass
class BarcodeScanner:
    """Manages a USB barcode scanner with auto-discovery, session-based
    reading, and USB power control."""

    _power_controller: UsbPowerController = field(
        default_factory=UsbPowerController, init=False, repr=False
    )
    _running: bool = field(default=False, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _device_path: str | None = field(default=None, init=False, repr=False)
    _device_name: str = field(default="Barcode Scanner", init=False, repr=False)
    _usb_device_id: str | None = field(default=None, init=False, repr=False)
    _power_state: str = field(default="unknown", init=False, repr=False)

    # Session state
    _session_active: bool = field(default=False, init=False, repr=False)
    _session_id: str | None = field(default=None, init=False, repr=False)
    _on_barcode: Callable[[ScanEntry], None] | None = field(
        default=None, init=False, repr=False
    )

    def set_power_controller(self, controller: UsbPowerController) -> None:
        """Inject the USB power controller."""
        self._power_controller = controller

    def start(self) -> None:
        """Start the background scanner thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._main_loop,
            daemon=True,
            name="barcode-scanner",
        )
        self._thread.start()
        logger.info("Barcode scanner thread started")

    def stop(self) -> None:
        """Stop the background scanner thread and power on USB (safe state)."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        # Power on USB on shutdown so the device is accessible
        if self._usb_device_id:
            self._power_controller.power_on(self._usb_device_id)
            self._power_state = "on"
        self._connected = False
        self._session_active = False
        logger.info("Barcode scanner stopped")

    # --- Session control ---

    def activate_session(
        self,
        session_id: str,
        on_barcode: Callable[[ScanEntry], None],
    ) -> None:
        """Activate a scan session -- powers on USB and starts scanning."""
        with self._lock:
            self._session_id = session_id
            self._on_barcode = on_barcode
            self._session_active = True
        logger.info("Scan session activated: %s", session_id)

    def deactivate_session(self) -> None:
        """Deactivate the current scan session -- will power off USB."""
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

    @property
    def power_state(self) -> str:
        """USB power state: 'on', 'off', or 'unknown'."""
        return self._power_state

    @property
    def usb_device_id(self) -> str | None:
        """Learned USB device ID, or None if not yet discovered."""
        return self._usb_device_id

    # --- Main loop ---

    def _main_loop(self) -> None:
        """Background loop with two phases:
        Phase 1: Initial discovery to learn USB device info.
        Phase 2: Session-driven power on/off + scanning.
        """
        # Phase 1: Discover scanner with USB powered on (default state)
        self._initial_discovery()

        # Phase 2: Session-driven operation
        while self._running:
            try:
                if self._session_active:
                    self._handle_active_session()
                else:
                    # USB should be off when no session
                    if self._power_state != "off" and self._usb_device_id:
                        self._power_off()
                    time.sleep(IDLE_CHECK_INTERVAL)
            except Exception as exc:
                logger.error("Scanner loop error: %s", exc)
                self._connected = False
                time.sleep(DISCOVERY_INTERVAL)

    def _initial_discovery(self) -> None:
        """Phase 1: Discover the scanner to learn its USB device ID and name.
        After discovery, power off the USB port."""
        logger.info("Initial scanner discovery (USB powered on)...")

        for attempt in range(10):
            if not self._running:
                return

            discovered = find_barcode_scanner()
            if discovered is not None:
                self._device_path = discovered.hidraw_path
                self._device_name = discovered.name
                self._usb_device_id = discovered.usb_device_id
                self._connected = True
                logger.info(
                    "Scanner discovered: %s at %s (usb_id=%s)",
                    discovered.name,
                    discovered.hidraw_path,
                    discovered.usb_device_id,
                )
                # Power off after learning the device info
                self._power_off()
                self._connected = False
                return

            logger.debug("Discovery attempt %d: no scanner found", attempt + 1)
            time.sleep(DISCOVERY_INTERVAL)

        logger.warning(
            "Initial discovery failed after 10 attempts. "
            "Scanner will be discovered when a session starts."
        )

    def _handle_active_session(self) -> None:
        """Handle an active scan session: power on, discover, read barcodes."""
        # Power on USB
        self._power_on()
        time.sleep(POWER_ON_SETTLE_TIME)

        # Wait for device to appear
        discovered = self._wait_for_device()
        if discovered is None:
            logger.warning("Scanner not found after power on")
            # Wait a bit before retrying
            time.sleep(DISCOVERY_INTERVAL)
            return

        self._device_path = discovered.hidraw_path
        self._device_name = discovered.name
        self._usb_device_id = discovered.usb_device_id
        self._connected = True

        # Read barcodes until session ends or device disconnects
        try:
            self._read_barcodes(discovered.hidraw_path)
        finally:
            self._connected = False
            # Power off when done
            self._power_off()

    def _wait_for_device(self) -> "DiscoveredDevice | None":
        """Wait for the scanner to appear after power on."""
        from app.devices.usb_discovery import DiscoveredDevice  # noqa: F811

        for attempt in range(MAX_DISCOVERY_ATTEMPTS):
            if not self._running or not self._session_active:
                return None

            discovered = find_barcode_scanner()
            if discovered is not None:
                return discovered

            logger.debug("Waiting for scanner (attempt %d/%d)...", attempt + 1, MAX_DISCOVERY_ATTEMPTS)
            time.sleep(1)

        return None

    def _read_barcodes(self, device_path: str) -> None:
        """Open HID device and read barcodes while session is active."""
        logger.info("Opening scanner %s for barcode reading", device_path)

        try:
            with open(device_path, "rb") as device:
                # Flush any stale data from before
                flushed = flush_buffer(device)
                if flushed > 0:
                    logger.debug("Flushed %d stale HID reports", flushed)

                barcode_chars: list[str] = []

                while self._running and self._session_active:
                    # Check device still exists
                    if not Path(device_path).exists():
                        logger.warning("Scanner device %s lost", device_path)
                        return

                    # Read with timeout so we can check flags
                    report = read_report_with_timeout(device, timeout=1.0)

                    if report is None:
                        if not Path(device_path).exists():
                            logger.warning("Scanner device %s lost during read", device_path)
                            return
                        continue

                    modifier = report[0]
                    scancode = report[2]

                    if scancode == 0:
                        continue

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

                            with self._lock:
                                callback = self._on_barcode
                            if callback:
                                try:
                                    callback(entry)
                                except Exception as exc:
                                    logger.error("Barcode callback error: %s", exc)
                        continue

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
        except OSError as exc:
            logger.warning("Scanner device error: %s", exc)

    # --- Power helpers ---

    def _power_on(self) -> None:
        """Power on the USB port."""
        success = self._power_controller.power_on(self._usb_device_id)
        if success:
            self._power_state = "on"
            logger.info("USB power ON (device_id=%s)", self._usb_device_id)
        else:
            logger.warning("USB power ON failed")

    def _power_off(self) -> None:
        """Power off the USB port."""
        success = self._power_controller.power_off(self._usb_device_id)
        if success:
            self._power_state = "off"
            logger.info("USB power OFF (device_id=%s)", self._usb_device_id)
        else:
            logger.warning("USB power OFF failed")
