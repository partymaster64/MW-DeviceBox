"""Persistent JSON-based settings store.

Stores runtime-configurable settings (like POS connection details) in a
JSON file that survives container restarts via a Docker volume mount.

Thread-safe: all reads and writes are protected by a lock.
"""

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default path inside the container (mapped to a Docker volume)
DEFAULT_SETTINGS_PATH = Path("/data/settings.json")


@dataclass
class PosSettings:
    """POS system connection settings."""

    url: str = ""
    token: str = ""
    poll_interval: int = 2  # seconds


@dataclass
class UsbPowerSettings:
    """USB power control settings."""

    method: str = "bind_unbind"  # "bind_unbind", "uhubctl", "none"


@dataclass
class AppSettings:
    """All runtime-configurable settings."""

    pos: PosSettings = field(default_factory=PosSettings)
    usb_power: UsbPowerSettings = field(default_factory=UsbPowerSettings)


class SettingsStore:
    """Thread-safe persistent settings store backed by a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_SETTINGS_PATH
        self._lock = threading.Lock()
        self._settings = AppSettings()
        self._load()

    def _load(self) -> None:
        """Load settings from disk, or use defaults if file missing/corrupt."""
        if not self._path.exists():
            logger.info("No settings file at %s, using defaults", self._path)
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            pos_raw = raw.get("pos", {})
            usb_raw = raw.get("usb_power", {})
            self._settings = AppSettings(
                pos=PosSettings(
                    url=pos_raw.get("url", ""),
                    token=pos_raw.get("token", ""),
                    poll_interval=int(pos_raw.get("poll_interval", 2)),
                ),
                usb_power=UsbPowerSettings(
                    method=usb_raw.get("method", "bind_unbind"),
                ),
            )
            logger.info("Settings loaded from %s", self._path)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Failed to load settings from %s: %s", self._path, exc)

    def _save(self) -> None:
        """Persist current settings to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(asdict(self._settings), indent=2, ensure_ascii=False)
            self._path.write_text(data, encoding="utf-8")
            logger.info("Settings saved to %s", self._path)
        except OSError as exc:
            logger.error("Failed to save settings to %s: %s", self._path, exc)

    @property
    def pos(self) -> PosSettings:
        """Get a snapshot of the current POS settings."""
        with self._lock:
            return PosSettings(
                url=self._settings.pos.url,
                token=self._settings.pos.token,
                poll_interval=self._settings.pos.poll_interval,
            )

    def update_pos(
        self,
        url: str | None = None,
        token: str | None = None,
        poll_interval: int | None = None,
    ) -> PosSettings:
        """Update POS settings and persist to disk.

        Only provided (non-None) values are updated.

        Returns:
            The updated PosSettings.
        """
        with self._lock:
            if url is not None:
                url = url.strip().rstrip("/")
                # Auto-prepend https:// if no protocol given
                if url and not url.startswith(("http://", "https://")):
                    url = f"https://{url}"
                self._settings.pos.url = url
            if token is not None:
                self._settings.pos.token = token
            if poll_interval is not None:
                self._settings.pos.poll_interval = max(1, poll_interval)
            self._save()
            return PosSettings(
                url=self._settings.pos.url,
                token=self._settings.pos.token,
                poll_interval=self._settings.pos.poll_interval,
            )

    @property
    def pos_configured(self) -> bool:
        """Check if POS URL and token are both set."""
        with self._lock:
            return bool(self._settings.pos.url and self._settings.pos.token)

    @property
    def usb_power(self) -> UsbPowerSettings:
        """Get a snapshot of the current USB power settings."""
        with self._lock:
            return UsbPowerSettings(
                method=self._settings.usb_power.method,
            )

    def update_usb_power(
        self,
        method: str | None = None,
    ) -> UsbPowerSettings:
        """Update USB power settings and persist to disk.

        Returns:
            The updated UsbPowerSettings.
        """
        with self._lock:
            if method is not None:
                if method not in ("bind_unbind", "uhubctl", "none"):
                    logger.warning("Invalid USB power method: %s", method)
                    method = "bind_unbind"
                self._settings.usb_power.method = method
            self._save()
            return UsbPowerSettings(
                method=self._settings.usb_power.method,
            )
