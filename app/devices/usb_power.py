"""USB power control for barcode scanners and other USB devices.

Supports two strategies:
- **bind/unbind**: Detaches the USB device driver via sysfs. Per-device,
  safe for other USB devices. No actual power loss but device becomes
  invisible to the OS.
- **uhubctl**: Real power cut via USB hub power switching. On Raspberry
  Pi 5 this affects ALL USB ports simultaneously (hardware limitation).

The method is selected via the settings store.
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SYSFS_USB_DRIVER = Path("/sys/bus/usb/drivers/usb")

# Raspberry Pi 5 requires commands on both bus 1 and 3
_RPI5_UHUBCTL_LOCATIONS = ["1", "3"]


class UsbPowerController:
    """Controls USB device power via bind/unbind or uhubctl."""

    def __init__(self, method: str = "bind_unbind") -> None:
        """Initialize the controller.

        Args:
            method: One of "bind_unbind", "uhubctl", or "none".
        """
        self._method = method
        self._uhubctl_available: bool | None = None
        logger.info("USB power controller initialized (method=%s)", method)

    @property
    def method(self) -> str:
        return self._method

    @method.setter
    def method(self, value: str) -> None:
        if value not in ("bind_unbind", "uhubctl", "none"):
            logger.warning("Unknown USB power method '%s', defaulting to bind_unbind", value)
            value = "bind_unbind"
        self._method = value
        logger.info("USB power method changed to %s", value)

    def is_uhubctl_available(self) -> bool:
        """Check if uhubctl is installed and usable."""
        if self._uhubctl_available is None:
            self._uhubctl_available = shutil.which("uhubctl") is not None
            if self._uhubctl_available:
                logger.info("uhubctl found at %s", shutil.which("uhubctl"))
            else:
                logger.info("uhubctl not found on this system")
        return self._uhubctl_available

    def power_on(self, usb_device_id: str | None = None) -> bool:
        """Power on a USB device.

        Args:
            usb_device_id: The USB device ID (e.g. "1-1.2") for bind/unbind.
                          Ignored for uhubctl method.

        Returns:
            True if the operation succeeded (or method is "none").
        """
        if self._method == "none":
            return True

        if self._method == "uhubctl":
            return self._uhubctl_power(on=True)

        # bind_unbind
        if not usb_device_id:
            logger.warning("Cannot power on: no USB device ID known")
            return False
        return self._bind(usb_device_id)

    def power_off(self, usb_device_id: str | None = None) -> bool:
        """Power off a USB device.

        Args:
            usb_device_id: The USB device ID (e.g. "1-1.2") for bind/unbind.
                          Ignored for uhubctl method.

        Returns:
            True if the operation succeeded (or method is "none").
        """
        if self._method == "none":
            return True

        if self._method == "uhubctl":
            return self._uhubctl_power(on=False)

        # bind_unbind
        if not usb_device_id:
            logger.warning("Cannot power off: no USB device ID known")
            return False
        return self._unbind(usb_device_id)

    # --- bind/unbind strategy ---

    def _bind(self, usb_device_id: str) -> bool:
        """Re-attach a USB device to the kernel driver."""
        bind_path = SYSFS_USB_DRIVER / "bind"
        try:
            bind_path.write_text(usb_device_id)
            logger.info("USB bind: %s", usb_device_id)
            return True
        except OSError as exc:
            # ENODEV means already bound -- that's fine
            if "No such device" in str(exc):
                logger.debug("USB device %s already bound", usb_device_id)
                return True
            logger.error("USB bind failed for %s: %s", usb_device_id, exc)
            return False

    def _unbind(self, usb_device_id: str) -> bool:
        """Detach a USB device from the kernel driver."""
        unbind_path = SYSFS_USB_DRIVER / "unbind"
        try:
            unbind_path.write_text(usb_device_id)
            logger.info("USB unbind: %s", usb_device_id)
            return True
        except OSError as exc:
            if "No such device" in str(exc):
                logger.debug("USB device %s already unbound", usb_device_id)
                return True
            logger.error("USB unbind failed for %s: %s", usb_device_id, exc)
            return False

    # --- uhubctl strategy ---

    def _uhubctl_power(self, on: bool) -> bool:
        """Toggle USB power using uhubctl (affects ALL ports on RPi5)."""
        if not self.is_uhubctl_available():
            logger.error("uhubctl not available, cannot control USB power")
            return False

        action = "1" if on else "0"
        action_name = "on" if on else "off"
        success = True

        for location in _RPI5_UHUBCTL_LOCATIONS:
            try:
                result = subprocess.run(
                    ["uhubctl", "-l", location, "-a", action],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    logger.warning(
                        "uhubctl -l %s -a %s failed (rc=%d): %s",
                        location,
                        action,
                        result.returncode,
                        result.stderr.strip(),
                    )
                    success = False
                else:
                    logger.info("uhubctl: USB power %s (location %s)", action_name, location)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
                logger.error("uhubctl execution failed: %s", exc)
                success = False

        return success
