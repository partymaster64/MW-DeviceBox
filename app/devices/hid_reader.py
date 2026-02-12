"""Low-level HID barcode reader.

Reads raw HID keyboard reports from /dev/hidraw* devices and decodes
USB scancodes into barcode strings. No external dependencies needed.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# HID report size (8 bytes: modifier, reserved, key1-key6)
HID_REPORT_SIZE = 8

# USB HID keyboard scancode to character mapping
# Reference: USB HID Usage Tables, Section 10 (Keyboard/Keypad Page)
_SCANCODE_MAP: dict[int, str] = {
    0x04: "a", 0x05: "b", 0x06: "c", 0x07: "d", 0x08: "e",
    0x09: "f", 0x0A: "g", 0x0B: "h", 0x0C: "i", 0x0D: "j",
    0x0E: "k", 0x0F: "l", 0x10: "m", 0x11: "n", 0x12: "o",
    0x13: "p", 0x14: "q", 0x15: "r", 0x16: "s", 0x17: "t",
    0x18: "u", 0x19: "v", 0x1A: "w", 0x1B: "x", 0x1C: "y",
    0x1D: "z",
    0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4", 0x22: "5",
    0x23: "6", 0x24: "7", 0x25: "8", 0x26: "9", 0x27: "0",
    0x2C: " ", 0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]",
    0x31: "\\", 0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",",
    0x37: ".", 0x38: "/",
}

_SCANCODE_MAP_SHIFTED: dict[int, str] = {
    0x04: "A", 0x05: "B", 0x06: "C", 0x07: "D", 0x08: "E",
    0x09: "F", 0x0A: "G", 0x0B: "H", 0x0C: "I", 0x0D: "J",
    0x0E: "K", 0x0F: "L", 0x10: "M", 0x11: "N", 0x12: "O",
    0x13: "P", 0x14: "Q", 0x15: "R", 0x16: "S", 0x17: "T",
    0x18: "U", 0x19: "V", 0x1A: "W", 0x1B: "X", 0x1C: "Y",
    0x1D: "Z",
    0x1E: "!", 0x1F: "@", 0x20: "#", 0x21: "$", 0x22: "%",
    0x23: "^", 0x24: "&", 0x25: "*", 0x26: "(", 0x27: ")",
    0x2C: " ", 0x2D: "_", 0x2E: "+", 0x2F: "{", 0x30: "}",
    0x31: "|", 0x33: ":", 0x34: '"', 0x35: "~", 0x36: "<",
    0x37: ">", 0x38: "?",
}

# Enter key scancode (signals end of barcode)
SCANCODE_ENTER = 0x28

# Shift modifier bitmask (left shift = bit 1, right shift = bit 5)
SHIFT_MASK = 0x22


def read_barcode(device_path: str) -> str | None:
    """Read a single barcode from an HID device.

    Blocks until a complete barcode is received (terminated by Enter key)
    or the device is disconnected.

    Args:
        device_path: Path to the HID device (e.g. /dev/hidraw0).

    Returns:
        The barcode string, or None if the device was disconnected.

    Raises:
        PermissionError: If the device cannot be opened.
        OSError: If the device is lost during reading.
    """
    barcode_chars: list[str] = []

    with open(device_path, "rb") as device:
        while True:
            data = device.read(HID_REPORT_SIZE)

            if not data or len(data) < HID_REPORT_SIZE:
                # Device disconnected
                return None

            modifier = data[0]
            scancode = data[2]

            # Skip empty reports (key release)
            if scancode == 0:
                continue

            # Enter key = end of barcode
            if scancode == SCANCODE_ENTER:
                result = "".join(barcode_chars)
                return result if result else None

            # Decode the scancode
            shifted = bool(modifier & SHIFT_MASK)
            char_map = _SCANCODE_MAP_SHIFTED if shifted else _SCANCODE_MAP
            char = char_map.get(scancode)

            if char:
                barcode_chars.append(char)
