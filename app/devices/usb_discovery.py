"""USB device auto-discovery via sysfs.

Scans /sys/class/hidraw/ to find HID devices matching known USB vendor/product
IDs and returns the corresponding /dev/hidraw* path plus the USB device ID
needed for bind/unbind power control.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SYSFS_HIDRAW = Path("/sys/class/hidraw")

# Pattern to match USB device directory names like "1-1", "1-1.2", "3-1.4"
_USB_DEVICE_ID_RE = re.compile(r"^\d+-[\d.]+$")


@dataclass(frozen=True)
class KnownDevice:
    """A known USB device identified by vendor and product ID."""

    vendor_id: str
    product_id: str
    name: str
    device_type: str


# Registry of known barcode scanners and other USB devices.
# Add new devices here to support auto-detection.
KNOWN_DEVICES: list[KnownDevice] = [
    KnownDevice(
        vendor_id="05f9",
        product_id="2214",
        name="Datalogic Touch 65",
        device_type="barcode_scanner",
    ),
]


@dataclass(frozen=True)
class DiscoveredDevice:
    """A discovered USB device with its /dev path and USB device ID."""

    hidraw_path: str
    vendor_id: str
    product_id: str
    name: str
    device_type: str
    usb_device_id: str  # e.g. "1-1.2" for bind/unbind power control


def _read_sysfs_attr(path: Path) -> str | None:
    """Read a single-line sysfs attribute file."""
    try:
        return path.read_text().strip()
    except (OSError, PermissionError):
        return None


def _find_usb_info_for_hidraw(
    hidraw_name: str,
) -> tuple[str, str, str] | None:
    """Walk the sysfs tree for a hidraw device to find USB vendor/product ID
    and the USB device directory name.

    Args:
        hidraw_name: e.g. "hidraw0"

    Returns:
        Tuple of (vendor_id, product_id, usb_device_id) or None if not found.
        vendor_id and product_id are lowercase hex strings.
        usb_device_id is the sysfs directory name like "1-1.2".
    """
    sysfs_path = SYSFS_HIDRAW / hidraw_name

    if not sysfs_path.exists():
        return None

    try:
        real_path = sysfs_path.resolve()
    except OSError:
        return None

    current = real_path
    for _ in range(10):  # limit traversal depth
        vendor_file = current / "idVendor"
        product_file = current / "idProduct"

        if vendor_file.exists() and product_file.exists():
            vendor = _read_sysfs_attr(vendor_file)
            product = _read_sysfs_attr(product_file)
            if vendor and product:
                # The directory name at this level is the USB device ID
                # e.g. "1-1.2" from /sys/devices/.../1-1.2/
                usb_device_id = current.name
                if not _USB_DEVICE_ID_RE.match(usb_device_id):
                    # Fallback: walk up to find a proper USB device ID
                    usb_device_id = _find_usb_device_id_from_path(current)
                return (vendor.lower(), product.lower(), usb_device_id)

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def _find_usb_device_id_from_path(path: Path) -> str:
    """Extract the USB device ID from a sysfs path by finding
    a directory component that matches the USB device ID pattern.

    Falls back to the path name if no match is found.
    """
    current = path
    for _ in range(10):
        if _USB_DEVICE_ID_RE.match(current.name):
            return current.name
        parent = current.parent
        if parent == current:
            break
        current = parent
    return path.name


def discover_devices() -> list[DiscoveredDevice]:
    """Scan all hidraw devices and return those matching known USB IDs.

    Returns:
        List of discovered devices with their /dev paths and metadata.
    """
    discovered: list[DiscoveredDevice] = []

    if not SYSFS_HIDRAW.exists():
        logger.debug("sysfs hidraw path %s does not exist", SYSFS_HIDRAW)
        return discovered

    # Build a lookup dict from known devices
    known_lookup: dict[tuple[str, str], KnownDevice] = {
        (d.vendor_id, d.product_id): d for d in KNOWN_DEVICES
    }

    try:
        hidraw_entries = sorted(SYSFS_HIDRAW.iterdir())
    except OSError:
        return discovered

    for entry in hidraw_entries:
        hidraw_name = entry.name  # e.g. "hidraw0"
        info = _find_usb_info_for_hidraw(hidraw_name)

        if info is None:
            continue

        vendor_id, product_id, usb_device_id = info

        known = known_lookup.get((vendor_id, product_id))
        if known is not None:
            dev_path = f"/dev/{hidraw_name}"
            device = DiscoveredDevice(
                hidraw_path=dev_path,
                vendor_id=vendor_id,
                product_id=product_id,
                name=known.name,
                device_type=known.device_type,
                usb_device_id=usb_device_id,
            )
            discovered.append(device)
            logger.info(
                "Discovered %s (%s:%s) at %s [usb=%s]",
                known.name,
                vendor_id,
                product_id,
                dev_path,
                usb_device_id,
            )

    if not discovered:
        logger.debug("No known USB devices found")

    return discovered


def find_barcode_scanner() -> DiscoveredDevice | None:
    """Find the first connected barcode scanner.

    Returns:
        The discovered scanner device, or None if no scanner is found.
    """
    devices = discover_devices()
    for device in devices:
        if device.device_type == "barcode_scanner":
            return device
    return None
