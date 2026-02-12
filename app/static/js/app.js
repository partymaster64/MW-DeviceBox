// =============================================================================
// DeviceBox - Dashboard
// =============================================================================

const API_BASE = window.location.origin;
let pollInterval = null;
let isOnline = false;
let logVisible = false;

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    fetchAll();
    pollInterval = setInterval(fetchAll, 4000);
});

function fetchAll() {
    fetchHealth();
    fetchInfo();
    fetchDevices();
    fetchWatchtower();
    fetchPosStatus();
}

// --- API Calls ---

async function fetchHealth() {
    try {
        const res = await fetch(`${API_BASE}/health`);
        const data = await res.json();
        isOnline = data.status === 'ok';
    } catch {
        isOnline = false;
    }
    updateBanner();
}

async function fetchInfo() {
    try {
        const res = await fetch(`${API_BASE}/info`);
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById('deviceName').textContent = data.device_name;
        document.getElementById('appVersion').textContent = `v${data.version}`;
        document.getElementById('footerVersion').textContent = `v${data.version}`;
    } catch {
        // ignore
    }
}

async function fetchWatchtower() {
    try {
        const res = await fetch(`${API_BASE}/watchtower/status`);
        if (!res.ok) return;
        const data = await res.json();
        const el = document.getElementById('watchtowerStatus');

        if (data.running) {
            el.textContent = 'Aktiv';
            el.style.color = 'var(--green)';
        } else {
            el.textContent = 'Inaktiv';
            el.style.color = 'var(--text-muted)';
        }
    } catch {
        // ignore
    }
}

// --- Scanner Status ---

let scannerConnected = false;
let scannerSessionActive = false;
let scannerName = '';

async function fetchDevices() {
    try {
        const res = await fetch(`${API_BASE}/devices`);
        if (!res.ok) return;
        const data = await res.json();

        if (data.devices && data.devices.length > 0) {
            const dev = data.devices[0];
            scannerConnected = dev.connected;
            scannerSessionActive = dev.session_active;
            scannerName = dev.name;
        } else {
            scannerConnected = false;
            scannerSessionActive = false;
            scannerName = '';
        }
    } catch {
        scannerConnected = false;
    }
    renderScanner();
    updateBanner();
}

function renderScanner() {
    const dot = document.getElementById('scannerDot');
    const label = document.getElementById('scannerLabel');
    const detail = document.getElementById('scannerDetail');

    if (scannerConnected) {
        if (scannerSessionActive) {
            dot.className = 'status-dot dot-pulse-green';
            label.textContent = 'Aktiv - scannt Barcodes';
            label.style.color = 'var(--green)';
        } else {
            dot.className = 'status-dot dot-green';
            label.textContent = 'Verbunden und bereit';
            label.style.color = 'var(--green)';
        }
        detail.textContent = scannerName || 'Barcode Scanner';
    } else {
        dot.className = 'status-dot dot-red';
        label.textContent = 'Nicht verbunden';
        label.style.color = 'var(--red)';
        detail.textContent = 'Bitte Scanner anschliessen';
    }
}

// --- POS Status ---

let posStatus = 'stopped';
let posDetail = '';

async function fetchPosStatus() {
    try {
        const res = await fetch(`${API_BASE}/settings/pos/status`);
        if (!res.ok) return;
        const data = await res.json();
        posStatus = data.status;
        posDetail = data.detail || '';
    } catch {
        posStatus = 'stopped';
    }
    renderPos();
    updateBanner();
}

function renderPos() {
    const dot = document.getElementById('posDot');
    const label = document.getElementById('posLabel');
    const detail = document.getElementById('posDetailText');

    const states = {
        'not_configured': {
            dotClass: 'dot-yellow',
            text: 'Nicht eingerichtet',
            detail: 'Einstellungen oeffnen zum Verbinden',
            color: 'var(--yellow)',
        },
        'polling': {
            dotClass: 'dot-green',
            text: 'Verbunden',
            detail: 'Wartet auf Scan-Auftrag vom Kassensystem',
            color: 'var(--green)',
        },
        'session_active': {
            dotClass: 'dot-pulse-green',
            text: 'Scan-Auftrag aktiv',
            detail: 'Barcodes werden an Kasse gesendet',
            color: 'var(--green)',
        },
        'error': {
            dotClass: 'dot-red',
            text: 'Verbindungsfehler',
            detail: posDetail || 'Einstellungen pruefen',
            color: 'var(--red)',
        },
        'stopped': {
            dotClass: 'dot-gray',
            text: 'Inaktiv',
            detail: '',
            color: 'var(--text-muted)',
        },
    };

    const cfg = states[posStatus] || states['stopped'];

    dot.className = `status-dot ${cfg.dotClass}`;
    label.textContent = cfg.text;
    label.style.color = cfg.color;
    detail.textContent = cfg.detail;
}

// --- Global Banner ---

function updateBanner() {
    const banner = document.getElementById('statusBanner');
    const icon = document.getElementById('statusBannerIcon');
    const title = document.getElementById('statusBannerTitle');
    const subtitle = document.getElementById('statusBannerSubtitle');

    if (!isOnline) {
        banner.className = 'status-banner banner-red';
        icon.innerHTML = '<i class="lucide lucide-wifi-off"></i>';
        title.textContent = 'DeviceBox ist nicht erreichbar';
        subtitle.textContent = 'Bitte Netzwerkverbindung pruefen';
        return;
    }

    if (posStatus === 'session_active' && scannerConnected) {
        banner.className = 'status-banner banner-green banner-pulse';
        icon.innerHTML = '<i class="lucide lucide-scan-barcode"></i>';
        title.textContent = 'Scan-Modus aktiv';
        subtitle.textContent = 'Barcodes werden an das Kassensystem gesendet';
        return;
    }

    if (posStatus === 'error') {
        banner.className = 'status-banner banner-red';
        icon.innerHTML = '<i class="lucide lucide-circle-alert"></i>';
        title.textContent = 'Kassensystem-Verbindung fehlgeschlagen';
        subtitle.textContent = posDetail || 'Einstellungen pruefen';
        return;
    }

    if (posStatus === 'not_configured') {
        banner.className = 'status-banner banner-yellow';
        icon.innerHTML = '<i class="lucide lucide-settings"></i>';
        title.textContent = 'Kassensystem nicht eingerichtet';
        subtitle.textContent = 'Oeffne die Einstellungen um die Verbindung herzustellen';
        return;
    }

    if (!scannerConnected) {
        banner.className = 'status-banner banner-yellow';
        icon.innerHTML = '<i class="lucide lucide-unplug"></i>';
        title.textContent = 'Scanner nicht verbunden';
        subtitle.textContent = 'Bitte Barcode-Scanner per USB anschliessen';
        return;
    }

    // All good
    banner.className = 'status-banner banner-green';
    icon.innerHTML = '<i class="lucide lucide-circle-check"></i>';
    title.textContent = 'Alles bereit';
    subtitle.textContent = 'Scanner verbunden, Kassensystem erreichbar';
}

// --- Log ---

function toggleLog() {
    const container = document.getElementById('logContainer');
    const chevron = document.getElementById('logChevron');
    logVisible = !logVisible;
    container.style.display = logVisible ? 'block' : 'none';
    chevron.className = logVisible
        ? 'lucide lucide-chevron-up'
        : 'lucide lucide-chevron-down';
}

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

    const entries = container.querySelectorAll('.log-entry');
    if (entries.length > 50) entries[0].remove();
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
