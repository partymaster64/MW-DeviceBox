#!/usr/bin/env python3
"""DeviceBox WiFi Manager – Captive-Portal fuer WLAN-Einrichtung.

Laeuft als systemd-Service auf dem Host (NICHT in Docker).
Wenn kein bekanntes WLAN gefunden wird, startet ein Access-Point
mit Captive-Portal, ueber das ein Handy die WLAN-Daten eingeben kann.

Ablauf:
  1. Pruefe ob WLAN verbunden ist
  2. Falls nicht → Access-Point "DeviceBox-Setup" starten
  3. Captive-Portal auf Port 80 starten
  4. Handy verbindet sich → Portal oeffnet automatisch
  5. Benutzer waehlt WLAN und gibt Passwort ein
  6. Verbindung wird hergestellt → AP stoppt
  7. Bei Misserfolg → AP wird neu gestartet, Fehler angezeigt

Abhaengigkeiten:
  - Python 3.9+ (nur stdlib)
  - NetworkManager (nmcli)
"""

import http.server
import json
import logging
import os
import signal
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("wifi-manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AP_SSID = "DeviceBox-Setup"
AP_CON_NAME = "DeviceBox-AP"
AP_IP = "10.42.0.1"
PORTAL_PORT = 80
PORTAL_DIR = Path(__file__).parent / "portal"
WIFI_INTERFACE = "wlan0"

CHECK_INTERVAL = 10          # Sekunden zwischen Konnektivitaets-Checks
FAILURE_THRESHOLD = 6        # 6 × 10s = 60s ohne WLAN → AP starten
CONNECT_SETTLE_TIME = 2      # Sekunden Wartezeit nach HTTP-Antwort vor AP-Stopp

DNSMASQ_CONF_DIR = Path("/etc/NetworkManager/dnsmasq-shared.d")
DNSMASQ_CONF_FILE = DNSMASQ_CONF_DIR / "captive-portal.conf"

# Docker-Compose Verzeichnis (Gateway-Container belegt Port 80)
DOCKER_COMPOSE_DIR = Path("/opt/iot-gateway")

# Pfade die Betriebssysteme fuer Captive-Portal-Erkennung pruefen
CAPTIVE_CHECK_PATHS = {
    "/hotspot-detect.html",          # Apple iOS / macOS
    "/library/test/success.html",    # Apple (aelter)
    "/generate_204",                 # Android / Chrome OS
    "/gen_204",                      # Android (Variante)
    "/connecttest.txt",              # Windows
    "/ncsi.txt",                     # Windows (aelter)
    "/redirect",                     # Android Fallback
    "/canonical.html",               # Firefox
    "/success.txt",                  # Diverse
    "/check_network_status.txt",     # Diverse
}


# ---------------------------------------------------------------------------
# WiFi Manager
# ---------------------------------------------------------------------------

class WifiManager:
    """Verwaltet WLAN-Konnektivitaet und Access-Point-Modus."""

    def __init__(self) -> None:
        self._ap_active = False
        self._server: socketserver.TCPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._running = True
        self._connecting = False
        self._consecutive_failures = 0
        self._last_error: str = ""

    # --- Konnektivitaet ---

    def is_wifi_connected(self) -> bool:
        """Prueft ob eine aktive WLAN-Verbindung besteht."""
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,STATE", "dev"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[0] == "wifi" and parts[1] == "connected":
                    return True
            return False
        except Exception as exc:
            logger.error("WLAN-Status-Pruefung fehlgeschlagen: %s", exc)
            return False

    def get_current_ssid(self) -> str:
        """Gibt die aktuell verbundene SSID zurueck, oder leer."""
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[0] == "yes":
                    return parts[1]
            return ""
        except Exception:
            return ""

    # --- WLAN-Scan ---

    def scan_networks(self) -> list[dict]:
        """Scannt verfuegbare WLAN-Netzwerke."""
        try:
            # Rescan ausloesen
            subprocess.run(
                ["nmcli", "dev", "wifi", "rescan", "ifname", WIFI_INTERFACE],
                capture_output=True, timeout=15,
            )
            time.sleep(2)

            result = subprocess.run(
                [
                    "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
                    "dev", "wifi", "list", "--rescan", "no",
                ],
                capture_output=True, text=True, timeout=10,
            )

            networks: list[dict] = []
            seen: set[str] = set()

            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                # SSID kann ":" enthalten → rsplit mit maxsplit=2
                parts = line.rsplit(":", 2)
                if len(parts) < 3:
                    continue

                ssid = parts[0].strip()
                signal_str = parts[1].strip()
                security = parts[2].strip()

                if not ssid or ssid in seen or ssid == AP_SSID:
                    continue
                seen.add(ssid)

                networks.append({
                    "ssid": ssid,
                    "signal": int(signal_str) if signal_str.isdigit() else 0,
                    "security": security if security != "--" else "Offen",
                })

            networks.sort(key=lambda x: x["signal"], reverse=True)
            return networks

        except Exception as exc:
            logger.error("WLAN-Scan fehlgeschlagen: %s", exc)
            return []

    # --- Verbindung herstellen ---

    def connect_async(self, ssid: str, password: str) -> None:
        """Startet Verbindungsversuch im Hintergrund-Thread."""
        threading.Thread(
            target=self._do_connect,
            args=(ssid, password),
            daemon=True,
            name="wifi-connect",
        ).start()

    def _do_connect(self, ssid: str, password: str) -> None:
        """Verbindungsversuch: AP stoppen → verbinden → bei Fehler AP neu starten."""
        self._connecting = True
        try:
            # Warten bis HTTP-Antwort beim Client angekommen ist
            time.sleep(CONNECT_SETTLE_TIME)

            # Portal und AP stoppen
            self.stop_portal()
            self.stop_ap()
            time.sleep(1)

            # Verbindung herstellen
            cmd = ["nmcli", "dev", "wifi", "connect", ssid]
            if password:
                cmd += ["password", password]
            cmd += ["ifname", WIFI_INTERFACE]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )

            if result.returncode == 0:
                logger.info("Erfolgreich verbunden mit '%s'", ssid)
                self._last_error = ""
                self._consecutive_failures = 0
                # AP bleibt aus, WLAN ist verbunden
                return

            # Fehlgeschlagen
            error = result.stderr.strip() or result.stdout.strip()
            logger.warning("Verbindung zu '%s' fehlgeschlagen: %s", ssid, error)

            if "secrets were required" in error.lower() or "password" in error.lower():
                self._last_error = "Falsches Passwort. Bitte erneut versuchen."
            else:
                self._last_error = f"Verbindung zu '{ssid}' fehlgeschlagen."

        except subprocess.TimeoutExpired:
            logger.error("Verbindungs-Timeout fuer '%s'", ssid)
            self._last_error = "Zeitueberschreitung. Bitte erneut versuchen."
        except Exception as exc:
            logger.error("Verbindungsfehler: %s", exc)
            self._last_error = "Unbekannter Fehler. Bitte erneut versuchen."
        finally:
            self._connecting = False

            # Bei Misserfolg: AP und Portal neu starten
            if not self.is_wifi_connected():
                logger.info("Verbindung fehlgeschlagen – AP wird neu gestartet")
                self.start_ap()
                time.sleep(2)
                self.start_portal()

    # --- Access Point ---

    def start_ap(self) -> None:
        """Startet den WLAN-Access-Point."""
        if self._ap_active:
            return

        try:
            self._setup_dns_redirect()

            # Alte AP-Verbindung loeschen falls vorhanden
            subprocess.run(
                ["nmcli", "connection", "delete", AP_CON_NAME],
                capture_output=True, timeout=10,
            )

            # Neue AP-Verbindung anlegen (offen, kein Passwort)
            result = subprocess.run(
                [
                    "nmcli", "connection", "add",
                    "type", "wifi",
                    "ifname", WIFI_INTERFACE,
                    "con-name", AP_CON_NAME,
                    "autoconnect", "no",
                    "ssid", AP_SSID,
                    "802-11-wireless.mode", "ap",
                    "802-11-wireless.band", "bg",
                    "ipv4.method", "shared",
                    "ipv4.addresses", f"{AP_IP}/24",
                ],
                capture_output=True, text=True, timeout=15,
            )

            if result.returncode != 0:
                logger.error("AP-Erstellung fehlgeschlagen: %s", result.stderr)
                return

            # Verbindung aktivieren
            result = subprocess.run(
                ["nmcli", "connection", "up", AP_CON_NAME],
                capture_output=True, text=True, timeout=15,
            )

            if result.returncode == 0:
                self._ap_active = True
                logger.info("Access-Point '%s' gestartet (IP: %s)", AP_SSID, AP_IP)
            else:
                logger.error("AP-Aktivierung fehlgeschlagen: %s", result.stderr)

        except Exception as exc:
            logger.error("AP-Start-Fehler: %s", exc)

    def stop_ap(self) -> None:
        """Stoppt den Access-Point."""
        if not self._ap_active:
            return

        try:
            subprocess.run(
                ["nmcli", "connection", "down", AP_CON_NAME],
                capture_output=True, timeout=10,
            )
            subprocess.run(
                ["nmcli", "connection", "delete", AP_CON_NAME],
                capture_output=True, timeout=10,
            )
            self._ap_active = False
            logger.info("Access-Point gestoppt")
        except Exception as exc:
            logger.error("AP-Stopp-Fehler: %s", exc)

    def _setup_dns_redirect(self) -> None:
        """Erstellt dnsmasq-Config damit alle DNS-Anfragen zum AP zeigen."""
        try:
            DNSMASQ_CONF_DIR.mkdir(parents=True, exist_ok=True)
            DNSMASQ_CONF_FILE.write_text(f"address=/#/{AP_IP}\n")
            logger.info("DNS-Redirect-Config erstellt: alle Domains → %s", AP_IP)
        except Exception as exc:
            logger.error("DNS-Redirect-Config fehlgeschlagen: %s", exc)

    # --- Docker Gateway Container (belegt Port 80) ---

    def _stop_gateway_container(self) -> None:
        """Stoppt den Docker Gateway Container um Port 80 freizugeben."""
        compose_file = DOCKER_COMPOSE_DIR / "docker-compose.yml"
        if not compose_file.exists():
            return

        try:
            result = subprocess.run(
                ["docker", "compose", "stop", "gateway"],
                capture_output=True, text=True, timeout=30,
                cwd=str(DOCKER_COMPOSE_DIR),
            )
            if result.returncode == 0:
                logger.info("Docker Gateway Container gestoppt (Port 80 frei)")
            else:
                logger.warning("Gateway-Stop: %s", result.stderr.strip())
        except Exception as exc:
            logger.error("Gateway-Stop fehlgeschlagen: %s", exc)

    def _start_gateway_container(self) -> None:
        """Startet den Docker Gateway Container nach Portal-Stopp."""
        compose_file = DOCKER_COMPOSE_DIR / "docker-compose.yml"
        if not compose_file.exists():
            return

        try:
            result = subprocess.run(
                ["docker", "compose", "start", "gateway"],
                capture_output=True, text=True, timeout=60,
                cwd=str(DOCKER_COMPOSE_DIR),
            )
            if result.returncode == 0:
                logger.info("Docker Gateway Container gestartet (Port 80 aktiv)")
            else:
                logger.warning("Gateway-Start: %s", result.stderr.strip())
        except Exception as exc:
            logger.error("Gateway-Start fehlgeschlagen: %s", exc)

    # --- Captive Portal HTTP Server ---

    def start_portal(self) -> None:
        """Startet den HTTP-Server fuer das Captive-Portal.

        Stoppt zuerst den Docker Gateway Container, da dieser ebenfalls
        Port 80 belegt.
        """
        if self._server is not None:
            return

        # Gateway Container stoppen um Port 80 freizugeben
        self._stop_gateway_container()
        time.sleep(1)

        try:
            handler = _make_handler(self)
            self._server = _ReusableTCPServer(("", PORTAL_PORT), handler)
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="captive-portal",
            )
            self._server_thread.start()
            logger.info("Captive-Portal gestartet auf Port %d", PORTAL_PORT)
        except OSError as exc:
            logger.error("Portal-Start fehlgeschlagen (Port %d belegt?): %s", PORTAL_PORT, exc)
            # Port immer noch belegt → Gateway Container vielleicht wieder starten
            self._start_gateway_container()

    def stop_portal(self) -> None:
        """Stoppt den HTTP-Server und startet den Gateway Container wieder."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._server_thread = None
            logger.info("Captive-Portal gestoppt")

        # Gateway Container wieder starten
        self._start_gateway_container()

    # --- Hauptschleife ---

    def run(self) -> None:
        """Hauptschleife: Konnektivitaet pruefen und AP bei Bedarf starten."""
        signal.signal(signal.SIGTERM, lambda *_: self.shutdown())
        signal.signal(signal.SIGINT, lambda *_: self.shutdown())

        logger.info("DeviceBox WiFi Manager gestartet")

        # Warten bis WLAN-Interface bereit ist
        self._wait_for_interface()

        while self._running:
            try:
                if self._connecting:
                    time.sleep(2)
                    continue

                connected = self.is_wifi_connected()

                if connected:
                    self._consecutive_failures = 0

                    if self._ap_active:
                        logger.info("WLAN verbunden – Access-Point wird gestoppt")
                        self.stop_portal()
                        self.stop_ap()
                else:
                    self._consecutive_failures += 1

                    if (
                        self._consecutive_failures >= FAILURE_THRESHOLD
                        and not self._ap_active
                    ):
                        ssid = self.get_current_ssid()
                        logger.info(
                            "Kein WLAN seit %ds – Access-Point wird gestartet",
                            self._consecutive_failures * CHECK_INTERVAL,
                        )
                        self.start_ap()
                        time.sleep(2)
                        self.start_portal()

                time.sleep(CHECK_INTERVAL)

            except Exception as exc:
                logger.error("Hauptschleifen-Fehler: %s", exc)
                time.sleep(CHECK_INTERVAL)

    def _wait_for_interface(self) -> None:
        """Wartet bis das WLAN-Interface in nmcli sichtbar ist."""
        for attempt in range(30):
            try:
                result = subprocess.run(
                    ["nmcli", "-t", "-f", "DEVICE,TYPE", "dev"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.strip().splitlines():
                    parts = line.split(":")
                    if len(parts) >= 2 and parts[0] == WIFI_INTERFACE:
                        logger.info("WLAN-Interface '%s' bereit", WIFI_INTERFACE)
                        return
            except Exception:
                pass

            if attempt == 0:
                logger.info("Warte auf WLAN-Interface '%s'...", WIFI_INTERFACE)
            time.sleep(2)

        logger.warning(
            "WLAN-Interface '%s' nicht gefunden – WiFi-Manager wird trotzdem gestartet",
            WIFI_INTERFACE,
        )

    def shutdown(self) -> None:
        """Sauberes Herunterfahren."""
        logger.info("WiFi Manager wird beendet...")
        self._running = False
        self.stop_portal()
        self.stop_ap()
        sys.exit(0)


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------

class _ReusableTCPServer(socketserver.ThreadingTCPServer):
    """TCP-Server mit Adress-Wiederverwendung und Daemon-Threads."""
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(manager: WifiManager):
    """Erzeugt einen HTTP-Request-Handler mit Zugriff auf den WifiManager."""

    class CaptivePortalHandler(http.server.BaseHTTPRequestHandler):

        def log_message(self, fmt, *args):
            logger.debug(fmt, *args)

        # --- GET ---

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path.lower()

            # Captive-Portal-Erkennung → Redirect zum Portal
            if path in CAPTIVE_CHECK_PATHS:
                self._redirect_to_portal()
                return

            # API-Endpunkte
            if path == "/api/wifi/scan":
                networks = manager.scan_networks()
                self._json_response({"networks": networks})
                return

            if path == "/api/wifi/status":
                self._json_response({
                    "connected": manager.is_wifi_connected(),
                    "ap_active": manager._ap_active,
                    "connecting": manager._connecting,
                    "last_error": manager._last_error,
                    "current_ssid": manager.get_current_ssid(),
                })
                return

            # Statische Dateien
            file_map = {
                "/": "index.html",
                "/index.html": "index.html",
                "/style.css": "style.css",
                "/app.js": "app.js",
            }

            filename = file_map.get(path)
            if filename:
                content_types = {
                    ".html": "text/html",
                    ".css": "text/css",
                    ".js": "application/javascript",
                }
                ext = Path(filename).suffix
                self._serve_file(filename, content_types.get(ext, "text/plain"))
                return

            # Alles andere → Portal (hilft bei Captive-Portal-Erkennung)
            self._redirect_to_portal()

        # --- POST ---

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path

            if path == "/api/wifi/connect":
                try:
                    content_length = int(self.headers.get("Content-Length", 0))
                except (ValueError, TypeError):
                    self._json_response(
                        {"success": False, "message": "Ungueltige Anfrage"}, 400,
                    )
                    return

                try:
                    raw = self.rfile.read(content_length)
                    body = raw.decode("utf-8")
                except (UnicodeDecodeError, OSError):
                    self._json_response(
                        {"success": False, "message": "Ungueltige Zeichenkodierung"}, 400,
                    )
                    return

                try:
                    data = json.loads(body)
                except (json.JSONDecodeError, ValueError):
                    self._json_response(
                        {"success": False, "message": "Ungueltige Anfrage"}, 400,
                    )
                    return

                ssid = data.get("ssid", "").strip()
                password = data.get("password", "").strip()

                if not ssid:
                    self._json_response(
                        {"success": False, "message": "Kein Netzwerk ausgewaehlt"},
                    )
                    return

                # Verbindung im Hintergrund starten
                manager._last_error = ""
                manager.connect_async(ssid, password)

                self._json_response({
                    "success": True,
                    "message": (
                        f"Verbindung zu '{ssid}' wird hergestellt... "
                        "Sie werden gleich vom Netzwerk getrennt."
                    ),
                })
                return

            self.send_error(404)

        # --- Hilfsmethoden ---

        def _redirect_to_portal(self):
            self.send_response(302)
            self.send_header("Location", f"http://{AP_IP}/")
            self.end_headers()

        def _serve_file(self, filename: str, content_type: str):
            filepath = PORTAL_DIR / filename
            if not filepath.exists():
                self.send_error(404)
                return
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.end_headers()
            self.wfile.write(content)

        def _json_response(self, data: dict, status: int = 200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

    return CaptivePortalHandler


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mgr = WifiManager()
    mgr.run()
