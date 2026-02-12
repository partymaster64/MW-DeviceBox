#!/usr/bin/env bash
# =============================================================================
# IoT Gateway - Raspberry Pi Installation Script
# =============================================================================
# Dieses Skript installiert alle Abhaengigkeiten und richtet den IoT Gateway
# Service auf einem Raspberry Pi (ARM64) ein.
#
# Verwendung:
#   chmod +x install.sh
#   sudo ./install.sh
#
# =============================================================================

set -euo pipefail

# --- Farben fuer Ausgabe ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/iot-gateway"
SERVICE_USER="iot-gateway"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"

# --- Hilfsfunktionen ---

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Dieses Skript muss als root ausgefuehrt werden (sudo ./install.sh)"
        exit 1
    fi
}

check_architecture() {
    local arch
    arch=$(uname -m)
    if [[ "$arch" != "aarch64" && "$arch" != "armv7l" ]]; then
        log_warn "Erkannte Architektur: $arch (erwartet: aarch64/armv7l)"
        log_warn "Dieses Skript ist fuer Raspberry Pi optimiert. Fortfahren auf eigene Gefahr."
    else
        log_success "Architektur: $arch"
    fi
}

# --- System aktualisieren ---

update_system() {
    log_info "System wird aktualisiert..."
    apt-get update -y
    apt-get upgrade -y
    log_success "System aktualisiert"
}

# --- Docker installieren ---

install_docker() {
    if command -v docker &> /dev/null; then
        log_success "Docker ist bereits installiert: $(docker --version)"
    else
        log_info "Docker wird installiert..."

        # Alte Versionen entfernen falls vorhanden
        apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

        # Abhaengigkeiten installieren
        apt-get install -y \
            ca-certificates \
            curl \
            gnupg \
            lsb-release

        # Docker GPG Key hinzufuegen
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg

        # Docker Repository hinzufuegen
        echo \
            "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
            $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
            tee /etc/apt/sources.list.d/docker.list > /dev/null

        # Docker installieren
        apt-get update -y
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        log_success "Docker installiert: $(docker --version)"
    fi
}

# --- Docker Dienst aktivieren ---

enable_docker_service() {
    log_info "Docker-Dienst wird aktiviert..."
    systemctl enable docker
    systemctl start docker
    log_success "Docker-Dienst laeuft und ist aktiviert"
}

# --- Benutzer fuer den Service anlegen ---

create_service_user() {
    if id "$SERVICE_USER" &>/dev/null; then
        log_success "Benutzer '$SERVICE_USER' existiert bereits"
    else
        log_info "Benutzer '$SERVICE_USER' wird erstellt..."
        useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
        log_success "Benutzer '$SERVICE_USER' erstellt"
    fi

    # Benutzer zur Docker-Gruppe hinzufuegen
    usermod -aG docker "$SERVICE_USER" 2>/dev/null || true
    log_success "Benutzer '$SERVICE_USER' ist in der Docker-Gruppe"
}

# --- Installationsverzeichnis einrichten ---

setup_install_dir() {
    log_info "Installationsverzeichnis wird eingerichtet: $INSTALL_DIR"

    mkdir -p "$INSTALL_DIR"

    # docker-compose.yml kopieren
    if [[ -f "$COMPOSE_FILE" ]]; then
        cp "$COMPOSE_FILE" "$INSTALL_DIR/docker-compose.yml"
        log_success "docker-compose.yml kopiert"
    else
        log_error "docker-compose.yml nicht gefunden im aktuellen Verzeichnis"
        exit 1
    fi

    # .env Datei erstellen falls nicht vorhanden
    if [[ ! -f "$INSTALL_DIR/.env" ]]; then
        if [[ -f ".env.example" ]]; then
            cp ".env.example" "$INSTALL_DIR/.env"
            log_info ".env aus .env.example erstellt - bitte Werte anpassen!"
        else
            cat > "$INSTALL_DIR/.env" <<'ENVEOF'
DEVICE_NAME=iot-gateway
APP_VERSION=1.0.0
GPIO_ENABLED=true
LOG_LEVEL=INFO
ENVEOF
            log_info "Standard .env erstellt"
        fi
    else
        log_success ".env existiert bereits - wird nicht ueberschrieben"
    fi

    # Berechtigungen setzen
    chown -R root:docker "$INSTALL_DIR"
    chmod 750 "$INSTALL_DIR"
    chmod 640 "$INSTALL_DIR/.env"

    log_success "Installationsverzeichnis eingerichtet"
}

# --- ghcr.io Authentifizierung einrichten ---

setup_ghcr_auth() {
    log_info "GitHub Container Registry Authentifizierung..."

    local ghcr_configured=false

    # Pruefen ob bereits authentifiziert
    if docker pull ghcr.io/$(grep -oP 'ghcr\.io/\K[^:]+' "$INSTALL_DIR/docker-compose.yml" | head -1):latest &>/dev/null 2>&1; then
        ghcr_configured=true
    fi

    if [[ "$ghcr_configured" == "false" ]]; then
        echo ""
        log_warn "============================================="
        log_warn " ghcr.io Authentifizierung erforderlich"
        log_warn "============================================="
        echo ""
        echo "Falls das Repository PRIVAT ist, muss Docker sich bei ghcr.io anmelden."
        echo "Erstelle einen GitHub Personal Access Token (PAT) mit 'read:packages' Berechtigung:"
        echo "  https://github.com/settings/tokens/new"
        echo ""
        read -rp "GitHub Benutzername (leer lassen fuer oeffentliches Repo): " GHCR_USER

        if [[ -n "$GHCR_USER" ]]; then
            read -rsp "GitHub Personal Access Token (PAT): " GHCR_TOKEN
            echo ""

            echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin

            # Credentials auch fuer den Service-User verfuegbar machen
            mkdir -p /root/.docker
            if [[ -f /root/.docker/config.json ]]; then
                log_success "ghcr.io Authentifizierung erfolgreich"
            fi
        else
            log_info "Ueberspringe Authentifizierung (oeffentliches Repository)"
        fi
    else
        log_success "ghcr.io ist bereits konfiguriert"
    fi
}

# --- Systemd Service erstellen ---

create_systemd_service() {
    log_info "Systemd-Service wird erstellt..."

    cat > /etc/systemd/system/iot-gateway.service <<SERVICEEOF
[Unit]
Description=IoT Gateway Service
Documentation=https://github.com/USERNAME/iot-gateway
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$INSTALL_DIR
ExecStartPre=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose pull && /usr/bin/docker compose up -d
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
SERVICEEOF

    systemctl daemon-reload
    systemctl enable iot-gateway.service
    log_success "Systemd-Service 'iot-gateway' erstellt und aktiviert"
}

# --- GPIO Zugriff einrichten ---

setup_gpio() {
    log_info "GPIO-Zugriff wird konfiguriert..."

    # gpio Gruppe erstellen falls noetig
    if ! getent group gpio &>/dev/null; then
        groupadd gpio
    fi

    # udev-Regel fuer GPIO Zugriff
    if [[ ! -f /etc/udev/rules.d/99-gpio.rules ]]; then
        cat > /etc/udev/rules.d/99-gpio.rules <<'GPIOEOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", ACTION=="add", PROGRAM="/bin/sh -c 'chown root:gpio /sys/class/gpio/export /sys/class/gpio/unexport ; chmod 220 /sys/class/gpio/export /sys/class/gpio/unexport'"
SUBSYSTEM=="gpio", KERNEL=="gpio*", ACTION=="add", PROGRAM="/bin/sh -c 'chown root:gpio /sys%p/active_low /sys%p/direction /sys%p/edge /sys%p/value ; chmod 660 /sys%p/active_low /sys%p/direction /sys%p/edge /sys%p/value'"
GPIOEOF
        udevadm control --reload-rules
        udevadm trigger
        log_success "GPIO udev-Regeln erstellt"
    else
        log_success "GPIO udev-Regeln existieren bereits"
    fi

    log_success "GPIO-Zugriff konfiguriert"
}

# --- Service starten ---

start_services() {
    log_info "IoT Gateway wird gestartet..."

    cd "$INSTALL_DIR"

    # Images pullen
    docker compose pull

    # Services starten
    docker compose up -d

    log_success "IoT Gateway laeuft"
}

# --- Status anzeigen ---

show_status() {
    echo ""
    echo -e "${GREEN}=============================================${NC}"
    echo -e "${GREEN}  IoT Gateway Installation abgeschlossen     ${NC}"
    echo -e "${GREEN}=============================================${NC}"
    echo ""
    echo -e "  Installationsverzeichnis: ${BLUE}$INSTALL_DIR${NC}"
    echo -e "  Konfiguration:           ${BLUE}$INSTALL_DIR/.env${NC}"
    echo -e "  API Adresse:             ${BLUE}http://$(hostname -I | awk '{print $1}'):8000${NC}"
    echo ""
    echo -e "  ${YELLOW}Nuetzliche Befehle:${NC}"
    echo "    sudo systemctl status iot-gateway    # Service-Status"
    echo "    sudo systemctl restart iot-gateway   # Service neustarten"
    echo "    sudo systemctl stop iot-gateway      # Service stoppen"
    echo "    cd $INSTALL_DIR && docker compose logs -f  # Logs anzeigen"
    echo ""
    echo -e "  ${YELLOW}API testen:${NC}"
    echo "    curl http://localhost:8000/health"
    echo "    curl http://localhost:8000/info"
    echo ""
    echo -e "  ${YELLOW}Watchtower:${NC}"
    echo "    Automatische Updates sind aktiv (Intervall: 60 Sekunden)"
    echo "    Bei jedem Push auf 'main' wird das neue Image automatisch deployed."
    echo ""

    # Container Status anzeigen
    log_info "Container-Status:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" --filter "name=iot-gateway" --filter "name=watchtower"
    echo ""
}

# =============================================================================
# Hauptprogramm
# =============================================================================

main() {
    echo ""
    echo -e "${BLUE}=============================================${NC}"
    echo -e "${BLUE}  IoT Gateway - Raspberry Pi Installer       ${NC}"
    echo -e "${BLUE}=============================================${NC}"
    echo ""

    check_root
    check_architecture

    update_system
    install_docker
    enable_docker_service
    create_service_user
    setup_gpio
    setup_install_dir
    setup_ghcr_auth
    create_systemd_service
    start_services
    show_status
}

main "$@"
