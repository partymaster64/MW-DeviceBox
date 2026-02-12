"""POS system polling service.

Runs a background thread that periodically checks the POS system API
for active scan sessions.  When a session is active, it tells the
BarcodeScanner to start forwarding scanned barcodes back to the POS.
"""

import json
import logging
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.devices.barcode_scanner import BarcodeScanner, ScanEntry
from app.services.settings_store import SettingsStore

logger = logging.getLogger(__name__)

# SSL context that works with both verified and self-signed certificates.
# On an IoT local network, the Bearer token provides authentication;
# we still use HTTPS for transport encryption but tolerate self-signed certs.
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _urlopen(req: Request, timeout: int = 5):
    """Open a URL with SSL support and timeout."""
    return urlopen(req, timeout=timeout, context=_ssl_ctx)


class PosPollingStatus:
    """Observable status of the POS polling service."""

    NOT_CONFIGURED = "not_configured"
    POLLING = "polling"
    SESSION_ACTIVE = "session_active"
    ERROR = "error"
    STOPPED = "stopped"


class PosPollingService:
    """Background service that polls a POS system for scan sessions."""

    def __init__(
        self,
        scanner: BarcodeScanner,
        settings_store: SettingsStore,
    ) -> None:
        self._scanner = scanner
        self._settings = settings_store
        self._running = False
        self._thread: threading.Thread | None = None
        self._status = PosPollingStatus.STOPPED
        self._status_detail: str = ""
        self._lock = threading.Lock()
        self._current_session_id: str | None = None

    def start(self) -> None:
        """Start the polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="pos-polling",
        )
        self._thread.start()
        logger.info("POS polling service started")

    def stop(self) -> None:
        """Stop the polling thread."""
        self._running = False
        self._scanner.deactivate_session()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        with self._lock:
            self._status = PosPollingStatus.STOPPED
            self._status_detail = ""
            self._current_session_id = None
        logger.info("POS polling service stopped")

    @property
    def status(self) -> str:
        """Current status string."""
        with self._lock:
            return self._status

    @property
    def status_detail(self) -> str:
        """Human-readable status detail."""
        with self._lock:
            return self._status_detail

    @property
    def current_session_id(self) -> str | None:
        """Currently active session ID, if any."""
        with self._lock:
            return self._current_session_id

    def _set_status(self, status: str, detail: str = "") -> None:
        with self._lock:
            self._status = status
            self._status_detail = detail

    # --- Polling loop ---

    def _poll_loop(self) -> None:
        """Main loop: check POS for sessions, manage scanner activation."""
        while self._running:
            try:
                pos = self._settings.pos

                # Check if configured
                if not pos.url or not pos.token:
                    self._set_status(
                        PosPollingStatus.NOT_CONFIGURED,
                        "POS URL oder Token nicht konfiguriert",
                    )
                    if self._current_session_id:
                        self._scanner.deactivate_session()
                        with self._lock:
                            self._current_session_id = None
                    time.sleep(3)
                    continue

                # Poll the POS API
                session = self._fetch_session(pos.url, pos.token)

                if session is None:
                    # Error already logged and status set in _fetch_session
                    if self._current_session_id:
                        self._scanner.deactivate_session()
                        with self._lock:
                            self._current_session_id = None
                    time.sleep(pos.poll_interval)
                    continue

                active = session.get("active", False)
                session_id = session.get("session_id")

                if active and session_id:
                    # Session is active
                    if self._current_session_id != session_id:
                        # New session or session changed
                        logger.info("POS scan session active: %s", session_id)
                        self._scanner.activate_session(
                            session_id=session_id,
                            on_barcode=lambda entry: self._send_barcode(
                                pos.url, pos.token, session_id, entry
                            ),
                        )
                        with self._lock:
                            self._current_session_id = session_id
                    self._set_status(
                        PosPollingStatus.SESSION_ACTIVE,
                        f"Session: {session_id[:8]}...",
                    )
                else:
                    # No active session
                    if self._current_session_id:
                        logger.info("POS scan session ended")
                        self._scanner.deactivate_session()
                        with self._lock:
                            self._current_session_id = None
                    self._set_status(
                        PosPollingStatus.POLLING,
                        "Warte auf Scan-Anfrage",
                    )

                time.sleep(pos.poll_interval)

            except Exception as exc:
                logger.error("POS polling error: %s", exc)
                self._set_status(PosPollingStatus.ERROR, str(exc))
                if self._current_session_id:
                    self._scanner.deactivate_session()
                    with self._lock:
                        self._current_session_id = None
                time.sleep(5)

    # --- HTTP helpers ---

    def _fetch_session(self, url: str, token: str) -> dict | None:
        """Query the POS API for the current scan session.

        Returns:
            Parsed JSON response dict, or None on error.
        """
        endpoint = f"{url}/api/devicebox/session"
        try:
            req = Request(endpoint)
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Accept", "application/json")

            with _urlopen(req) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)

        except HTTPError as exc:
            if exc.code == 401:
                self._set_status(PosPollingStatus.ERROR, "Token ungueltig (401)")
                logger.warning("POS API returned 401 Unauthorized")
            elif exc.code == 404:
                self._set_status(PosPollingStatus.ERROR, "Endpoint nicht gefunden (404)")
                logger.warning("POS API endpoint not found: %s", endpoint)
            else:
                self._set_status(PosPollingStatus.ERROR, f"HTTP {exc.code}")
                logger.warning("POS API error: HTTP %d", exc.code)
            return None
        except (URLError, OSError, TimeoutError) as exc:
            self._set_status(PosPollingStatus.ERROR, "POS nicht erreichbar")
            logger.debug("POS API not reachable: %s", exc)
            return None
        except (json.JSONDecodeError, ValueError) as exc:
            self._set_status(
                PosPollingStatus.ERROR,
                "Antwort ist kein JSON",
            )
            logger.warning(
                "POS API returned invalid JSON from %s: %s (body: %.200s)",
                endpoint,
                exc,
                body if "body" in dir() else "<unreadable>",
            )
            return None

    def _send_barcode(
        self,
        url: str,
        token: str,
        session_id: str,
        entry: ScanEntry,
    ) -> None:
        """Send a scanned barcode to the POS system."""
        endpoint = f"{url}/api/devicebox/barcode"
        payload = json.dumps(
            {
                "session_id": session_id,
                "barcode": entry.barcode,
                "timestamp": entry.timestamp,
                "device_name": entry.device,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        try:
            req = Request(endpoint, data=payload, method="POST")
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json")

            with _urlopen(req) as resp:
                resp.read()
                logger.info(
                    "Barcode sent to POS: %s (session %s)",
                    entry.barcode,
                    session_id[:8],
                )
        except HTTPError as exc:
            logger.error(
                "Failed to send barcode to POS: HTTP %d", exc.code
            )
        except (URLError, OSError, TimeoutError) as exc:
            logger.error("Failed to send barcode to POS: %s", exc)

    # --- Test connection (used by settings API) ---

    @staticmethod
    def test_connection(url: str, token: str) -> tuple[bool, str]:
        """Test the POS API connection.

        Returns:
            Tuple of (success, message).
        """
        endpoint = f"{url.rstrip('/')}/api/devicebox/session"
        body = ""
        try:
            req = Request(endpoint)
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Accept", "application/json")

            with _urlopen(req) as resp:
                body = resp.read().decode("utf-8")
                content_type = resp.headers.get("Content-Type", "")
                logger.info(
                    "POS test response: status=%d, type=%s, body=%.200s",
                    resp.status,
                    content_type,
                    body,
                )
                data = json.loads(body)
                if "active" in data:
                    return True, "Verbindung erfolgreich"
                return False, f"Unerwartetes Antwortformat: {list(data.keys())}"

        except HTTPError as exc:
            if exc.code == 401:
                return False, "Token ungueltig (401 Unauthorized)"
            # Try to read the error body for more info
            try:
                err_body = exc.read().decode("utf-8")[:200]
                return False, f"HTTP {exc.code}: {err_body}"
            except Exception:
                return False, f"HTTP-Fehler: {exc.code}"
        except (URLError, OSError, TimeoutError) as exc:
            return False, f"Nicht erreichbar: {exc}"
        except (json.JSONDecodeError, ValueError):
            preview = body[:200] if body else "<leer>"
            return False, f"Antwort ist kein JSON: {preview}"
