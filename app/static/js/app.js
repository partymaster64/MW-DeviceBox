// =============================================================================
// DeviceBox - IoT Gateway Dashboard
// =============================================================================

const API_BASE = window.location.origin;
let lastKnownBarcode = null;
let pollInterval = null;
let scanPollInterval = null;

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    fetchHealth();
    fetchInfo();
    fetchDevices();
    fetchLastScan();
    fetchHistory();

    // Poll health every 10 seconds
    pollInterval = setInterval(() => {
        fetchHealth();
        fetchDevices();
    }, 10000);

    // Poll scanner every 2 seconds for near-realtime barcode updates
    scanPollInterval = setInterval(() => {
        fetchLastScan();
        fetchHistory();
    }, 2000);
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
        const data = await res.json();

        document.getElementById('deviceName').textContent = data.device_name;
        document.getElementById('appVersion').textContent = `v${data.version}`;
        document.getElementById('footerVersion').textContent = `v${data.version}`;

        addLog('info', `Verbunden mit ${data.device_name} v${data.version}`);
    } catch (err) {
        addLog('error', `Verbindung fehlgeschlagen: ${err.message}`);
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

async function fetchLastScan() {
    try {
        const res = await fetch(`${API_BASE}/devices/scanner/last-scan`);
        const data = await res.json();
        renderLastScan(data.scan);
    } catch {
        // Silently ignore polling errors
    }
}

async function fetchHistory() {
    try {
        const res = await fetch(`${API_BASE}/devices/scanner/history`);
        const data = await res.json();
        renderHistory(data.scans, data.total);
    } catch {
        // Silently ignore polling errors
    }
}

// --- Render Functions ---

function renderDevices(devices) {
    const container = document.getElementById('devicesList');

    if (!devices || devices.length === 0) {
        container.innerHTML = '<div class="device-empty">Keine Geraete erkannt</div>';
        return;
    }

    container.innerHTML = devices.map(device => {
        const isConnected = device.connected;
        const typeLabel = getDeviceTypeLabel(device.type);
        const typeIcon = getDeviceTypeIcon(device.type);

        return `
            <div class="device-card">
                <div class="device-card-icon ${isConnected ? 'connected' : ''}">
                    <i class="lucide ${typeIcon}"></i>
                </div>
                <div class="device-card-body">
                    <div class="device-card-name">${escapeHtml(device.name)}</div>
                    <div class="device-card-meta">${typeLabel} &middot; ${escapeHtml(device.device_path)}</div>
                </div>
                <div class="device-card-status ${isConnected ? 'connected' : 'disconnected'}">
                    <i class="lucide ${isConnected ? 'lucide-circle-check' : 'lucide-circle-x'}"></i>
                    ${isConnected ? 'Verbunden' : 'Getrennt'}
                </div>
            </div>
        `;
    }).join('');
}

function renderLastScan(scan) {
    const container = document.getElementById('barcodeDisplay');

    if (!scan) {
        container.innerHTML = `
            <div class="barcode-empty">
                <i class="lucide lucide-scan-line"></i>
                <p>Warte auf Scan...</p>
            </div>
        `;
        return;
    }

    // Detect new barcode and log it
    if (scan.barcode !== lastKnownBarcode) {
        if (lastKnownBarcode !== null) {
            addLog('success', `Neuer Barcode gescannt: ${scan.barcode}`);
        }
        lastKnownBarcode = scan.barcode;
    }

    const time = formatTimestamp(scan.timestamp);

    container.innerHTML = `
        <div class="barcode-value">${escapeHtml(scan.barcode)}</div>
        <div class="barcode-meta">
            <i class="lucide lucide-clock"></i>
            <span>${time}</span>
            <span>&middot;</span>
            <i class="lucide lucide-scan-barcode"></i>
            <span>${escapeHtml(scan.device)}</span>
        </div>
    `;
}

function renderHistory(scans, total) {
    const container = document.getElementById('historyList');
    const countEl = document.getElementById('historyCount');

    countEl.textContent = total;

    if (!scans || scans.length === 0) {
        container.innerHTML = '<div class="history-empty">Noch keine Scans</div>';
        return;
    }

    container.innerHTML = scans.map(scan => {
        const time = formatTimestamp(scan.timestamp);
        return `
            <div class="history-entry">
                <i class="lucide lucide-scan-barcode history-entry-icon"></i>
                <span class="history-entry-barcode">${escapeHtml(scan.barcode)}</span>
                <span class="history-entry-time">${time}</span>
            </div>
        `;
    }).join('');
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
