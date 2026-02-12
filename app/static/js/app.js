// =============================================================================
// DeviceBox - IoT Gateway Dashboard
// =============================================================================

const API_BASE = window.location.origin;
let pollInterval = null;

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    fetchHealth();
    fetchInfo();
    fetchDevices();
    fetchWatchtower();
    fetchPosStatus();

    // Poll every 5 seconds
    pollInterval = setInterval(() => {
        fetchHealth();
        fetchDevices();
        fetchWatchtower();
        fetchPosStatus();
    }, 5000);
});

// --- API Calls ---

async function fetchHealth() {
    try {
        const res = await fetch(`${API_BASE}/health`);
        const data = await res.json();
        const el = document.getElementById('healthStatus');

        if (data.status === 'ok') {
            el.textContent = 'Online';
            el.style.color = 'var(--green)';
            setOnline();
        } else {
            el.textContent = 'Fehler';
            el.style.color = 'var(--red)';
            setOffline();
        }
    } catch {
        document.getElementById('healthStatus').textContent = 'Offline';
        document.getElementById('healthStatus').style.color = 'var(--red)';
        setOffline();
    }
}

async function fetchInfo() {
    try {
        const res = await fetch(`${API_BASE}/info`);
        if (!res.ok) {
            addLog('error', `Info-Abfrage fehlgeschlagen (HTTP ${res.status})`);
            return;
        }
        const data = await res.json();

        document.getElementById('deviceName').textContent = data.device_name;
        document.getElementById('appVersion').textContent = `v${data.version}`;
        document.getElementById('footerVersion').textContent = `v${data.version}`;

        addLog('info', `Verbunden mit ${data.device_name} v${data.version}`);
    } catch (err) {
        addLog('error', `Verbindung fehlgeschlagen: ${err.message}`);
    }
}

async function fetchWatchtower() {
    try {
        const res = await fetch(`${API_BASE}/watchtower/status`);
        if (!res.ok) return;
        const data = await res.json();

        const statusEl = document.getElementById('watchtowerStatus');
        const detailEl = document.getElementById('watchtowerDetail');
        const iconEl = document.getElementById('watchtowerIcon');

        if (data.running) {
            statusEl.textContent = 'Aktiv';
            statusEl.style.color = 'var(--green)';
            iconEl.className = 'card-icon card-icon-purple';

            const parts = [];
            parts.push(`alle ${data.interval}s`);
            if (data.containers_scanned !== null) {
                parts.push(`${data.containers_scanned} gescannt`);
            }
            if (data.containers_updated !== null && data.containers_updated > 0) {
                parts.push(`${data.containers_updated} aktualisiert`);
            }
            detailEl.textContent = parts.join(' · ');
        } else {
            statusEl.textContent = 'Inaktiv';
            statusEl.style.color = 'var(--red)';
            iconEl.className = 'card-icon card-icon-purple';
            detailEl.textContent = 'Nicht erreichbar';
        }
    } catch {
        // Silently ignore
    }
}

async function fetchPosStatus() {
    try {
        const res = await fetch(`${API_BASE}/settings/pos/status`);
        if (!res.ok) return;
        const data = await res.json();
        renderPosStatus(data);
    } catch {
        // Silently ignore
    }
}

async function fetchDevices() {
    try {
        const res = await fetch(`${API_BASE}/devices`);
        const data = await res.json();
        renderDevices(data.devices);
    } catch {
        document.getElementById('devicesList').innerHTML =
            '<div class="device-empty">Geraete konnten nicht geladen werden</div>';
    }
}

// --- Render Functions ---

function renderPosStatus(data) {
    const statusEl = document.getElementById('posStatus');
    const detailEl = document.getElementById('posDetail');
    const iconEl = document.getElementById('posCardIcon');

    const statusMap = {
        'not_configured': {
            text: 'Nicht konfiguriert',
            color: 'var(--yellow)',
            iconClass: 'card-icon card-icon-yellow',
        },
        'polling': {
            text: 'Verbunden',
            color: 'var(--green)',
            iconClass: 'card-icon card-icon-cyan',
        },
        'session_active': {
            text: 'Scan aktiv',
            color: 'var(--green)',
            iconClass: 'card-icon card-icon-green',
        },
        'error': {
            text: 'Fehler',
            color: 'var(--red)',
            iconClass: 'card-icon card-icon-red',
        },
        'stopped': {
            text: 'Gestoppt',
            color: 'var(--text-muted)',
            iconClass: 'card-icon card-icon-cyan',
        },
    };

    const cfg = statusMap[data.status] || statusMap['stopped'];

    statusEl.textContent = cfg.text;
    statusEl.style.color = cfg.color;
    iconEl.className = cfg.iconClass;

    const details = [];
    if (data.detail) details.push(data.detail);
    if (data.scanner_connected) {
        details.push('Scanner bereit');
    }
    detailEl.textContent = details.join(' · ');
}

function renderDevices(devices) {
    const container = document.getElementById('devicesList');

    if (!devices || devices.length === 0) {
        container.innerHTML = '<div class="device-empty">Keine Geraete erkannt</div>';
        return;
    }

    container.innerHTML = devices.map(device => {
        const typeLabel = getDeviceTypeLabel(device.type);
        const typeIcon = getDeviceTypeIcon(device.type);
        const powerState = device.power_state || 'unknown';

        // Determine display status based on power state and connection
        let statusClass, statusIcon, statusLabel;
        if (device.connected) {
            statusClass = 'connected';
            statusIcon = 'lucide-circle-check';
            statusLabel = 'Verbunden';
        } else if (powerState === 'off') {
            statusClass = 'standby';
            statusIcon = 'lucide-moon';
            statusLabel = 'Standby';
        } else {
            statusClass = 'disconnected';
            statusIcon = 'lucide-circle-x';
            statusLabel = 'Getrennt';
        }

        // Power badge
        const powerBadge = getPowerBadge(powerState);

        return `
            <div class="device-card">
                <div class="device-card-icon ${statusClass}">
                    <i class="lucide ${typeIcon}"></i>
                </div>
                <div class="device-card-body">
                    <div class="device-card-name">${escapeHtml(device.name)} ${powerBadge}</div>
                    <div class="device-card-meta">${typeLabel} &middot; ${escapeHtml(device.device_path)}</div>
                </div>
                <div class="device-card-status ${statusClass}">
                    <i class="lucide ${statusIcon}"></i>
                    ${statusLabel}
                </div>
            </div>
        `;
    }).join('');
}

function getPowerBadge(powerState) {
    const config = {
        'on': { icon: 'lucide-zap', label: 'USB an', cssClass: 'power-on' },
        'off': { icon: 'lucide-zap-off', label: 'USB aus', cssClass: 'power-off' },
        'unknown': { icon: 'lucide-help-circle', label: 'USB ?', cssClass: 'power-unknown' },
    };

    const cfg = config[powerState] || config['unknown'];
    return `<span class="power-badge ${cfg.cssClass}"><i class="lucide ${cfg.icon}"></i>${cfg.label}</span>`;
}

// --- UI Helpers ---

function setOnline() {
    const status = document.getElementById('connectionStatus');
    status.className = 'header-status online';
    status.innerHTML = '<i class="lucide lucide-wifi"></i><span>Verbunden</span>';
}

function setOffline() {
    const status = document.getElementById('connectionStatus');
    status.className = 'header-status offline';
    status.innerHTML = '<i class="lucide lucide-wifi-off"></i><span>Getrennt</span>';
}

function getDeviceTypeLabel(type) {
    const labels = {
        'barcode_scanner': 'Barcode Scanner',
    };
    return labels[type] || type;
}

function getDeviceTypeIcon(type) {
    const icons = {
        'barcode_scanner': 'lucide-scan-barcode',
    };
    return icons[type] || 'lucide-box';
}

function formatTimestamp(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleString('de-DE', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        });
    } catch {
        return isoString;
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// --- Log ---

function addLog(type, message) {
    const container = document.getElementById('logContainer');
    const empty = container.querySelector('.log-empty');
    if (empty) empty.remove();

    const now = new Date();
    const time = now.toLocaleTimeString('de-DE', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });

    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `<span class="log-time">${time}</span><span class="log-msg ${type}">${escapeHtml(message)}</span>`;

    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;

    // Keep max 50 entries
    const entries = container.querySelectorAll('.log-entry');
    if (entries.length > 50) {
        entries[0].remove();
    }
}

function clearLog() {
    const container = document.getElementById('logContainer');
    container.innerHTML = '<div class="log-empty">Noch keine Aktivitaet</div>';
}
