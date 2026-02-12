"""USB device auto-discovery via sysfs.

Scans /sys/class/hidraw/ to find HID devices matching known USB vendor/product
IDs and returns the corresponding /dev/hidraw* path.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SYSFS_HIDRAW = Path("/sys/class/hidraw")


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
    """A discovered USB device with its /dev path."""

    hidraw_path: str
    vendor_id: str
    product_id: str
    name: str
    device_type: str


def _read_sysfs_attr(path: Path) -> str | None:
    """Read a single-line sysfs attribute file."""
    try:
        return path.read_text().strip()
    except (OSError, PermissionError):
        return None


def _find_usb_ids_for_hidraw(hidraw_name: str) -> tuple[str, str] | None:
    """Walk the sysfs tree for a hidraw device to find its USB vendor/product ID.

    Args:
        hidraw_name: e.g. "hidraw0"

    Returns:
        Tuple of (vendor_id, product_id) in lowercase hex, or None if not found.
    """
    sysfs_path = SYSFS_HIDRAW / hidraw_name

    if not sysfs_path.exists():
        return None

    # Resolve the real path and walk up the directory tree
    # looking for idVendor and idProduct files (present at the USB device level)
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
                return (vendor.lower(), product.lower())

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


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
        ids = _find_usb_ids_for_hidraw(hidraw_name)

        if ids is None:
            continue

        known = known_lookup.get(ids)
        if known is not None:
            dev_path = f"/dev/{hidraw_name}"
            device = DiscoveredDevice(
                hidraw_path=dev_path,
                vendor_id=ids[0],
                product_id=ids[1],
                name=known.name,
                device_type=known.device_type,
            )
            discovered.append(device)
            logger.info(
                "Discovered %s (%s:%s) at %s",
                known.name,
                ids[0],
                ids[1],
                dev_path,
            )

    if not discovered:
        logger.info("No known USB devices found")

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
