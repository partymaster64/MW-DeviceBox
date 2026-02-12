// =============================================================================
// DeviceBox - Settings Page
// =============================================================================

const API_BASE = window.location.origin;
let statusPollInterval = null;

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    loadSettings();
    loadUsbPowerSettings();
    loadPosStatus();
    fetchFooterVersion();

    // Poll status every 3 seconds
    statusPollInterval = setInterval(() => {
        loadPosStatus();
    }, 3000);

    // USB power method change handler
    document.getElementById('usbPowerMethod').addEventListener('change', updateUsbPowerHints);
});

// --- API Calls ---

async function checkHealth() {
    try {
        const res = await fetch(`${API_BASE}/health`);
        const data = await res.json();
        if (data.status === 'ok') {
            setOnline();
        } else {
            setOffline();
        }
    } catch {
        setOffline();
    }
}

async function fetchFooterVersion() {
    try {
        const res = await fetch(`${API_BASE}/info`);
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById('footerVersion').textContent = `v${data.version}`;
    } catch {
        // Silently ignore
    }
}

async function loadSettings() {
    try {
        const res = await fetch(`${API_BASE}/settings/pos`);
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById('posUrl').value = data.url || '';
        document.getElementById('posPollInterval').value = data.poll_interval || 2;

        // Don't fill in the actual token, just indicate if it's set
        if (data.token_set) {
            document.getElementById('posToken').placeholder = 'Token gesetzt (unveraendert lassen)';
        }
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

async function loadPosStatus() {
    try {
        const res = await fetch(`${API_BASE}/settings/pos/status`);
        if (!res.ok) return;
        const data = await res.json();
        renderPosStatus(data);
    } catch {
        // Silently ignore
    }
}

async function saveSettings() {
    const btn = document.getElementById('btnSave');
    btn.disabled = true;

    const body = {};
    const url = document.getElementById('posUrl').value.trim();
    const token = document.getElementById('posToken').value.trim();
    const interval = parseInt(document.getElementById('posPollInterval').value, 10);

    if (url) body.url = url;
    if (token) body.token = token;
    if (!isNaN(interval) && interval >= 1) body.poll_interval = interval;

    try {
        const res = await fetch(`${API_BASE}/settings/pos`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (res.ok) {
            const data = await res.json();
            showTestResult(true, 'Einstellungen gespeichert');
            // Update placeholder if token was set
            if (data.token_set) {
                document.getElementById('posToken').value = '';
                document.getElementById('posToken').placeholder = 'Token gesetzt (unveraendert lassen)';
            }
        } else {
            showTestResult(false, `Fehler beim Speichern (HTTP ${res.status})`);
        }
    } catch (err) {
        showTestResult(false, `Fehler: ${err.message}`);
    } finally {
        btn.disabled = false;
    }
}

async function testConnection() {
    const btn = document.getElementById('btnTest');
    btn.disabled = true;

    const url = document.getElementById('posUrl').value.trim();
    const token = document.getElementById('posToken').value.trim();

    if (!url) {
        showTestResult(false, 'Bitte POS API URL eingeben');
        btn.disabled = false;
        return;
    }

    // If no token entered, try with existing saved token
    let testToken = token;
    if (!testToken) {
        try {
            const res = await fetch(`${API_BASE}/settings/pos`);
            if (res.ok) {
                const data = await res.json();
                if (!data.token_set) {
                    showTestResult(false, 'Bitte API Token eingeben');
                    btn.disabled = false;
                    return;
                }
                // Can't test with saved token from frontend (it's not exposed)
                showTestResult(false, 'Bitte Token eingeben um die Verbindung zu testen');
                btn.disabled = false;
                return;
            }
        } catch {
            // Fall through
        }
    }

    try {
        const res = await fetch(`${API_BASE}/settings/pos/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, token: testToken }),
        });

        if (res.ok) {
            const data = await res.json();
            showTestResult(data.success, data.message);
        } else {
            showTestResult(false, `Test fehlgeschlagen (HTTP ${res.status})`);
        }
    } catch (err) {
        showTestResult(false, `Verbindungsfehler: ${err.message}`);
    } finally {
        btn.disabled = false;
    }
}

// --- Render ---

function renderPosStatus(data) {
    const card = document.getElementById('posStatusCard');
    const iconEl = document.getElementById('posStatusIcon');
    const labelEl = document.getElementById('posStatusLabel');
    const detailEl = document.getElementById('posStatusDetail');

    const statusConfig = {
        'not_configured': {
            icon: 'lucide-circle-alert',
            label: 'Nicht konfiguriert',
            cssClass: 'status-warn',
        },
        'polling': {
            icon: 'lucide-radio',
            label: 'Polling aktiv',
            cssClass: 'status-ok',
        },
        'session_active': {
            icon: 'lucide-scan-barcode',
            label: 'Scan-Session aktiv',
            cssClass: 'status-active',
        },
        'error': {
            icon: 'lucide-circle-x',
            label: 'Fehler',
            cssClass: 'status-error',
        },
        'stopped': {
            icon: 'lucide-circle-pause',
            label: 'Gestoppt',
            cssClass: 'status-warn',
        },
    };

    const cfg = statusConfig[data.status] || statusConfig['stopped'];

    card.className = `settings-status-card ${cfg.cssClass}`;
    iconEl.innerHTML = `<i class="lucide ${cfg.icon}"></i>`;
    labelEl.textContent = cfg.label;

    const details = [];
    if (data.detail) details.push(data.detail);
    if (data.scanner_connected) {
        details.push('Scanner verbunden');
    } else {
        details.push('Scanner getrennt');
    }
    detailEl.textContent = details.join(' · ');
}

function showTestResult(success, message) {
    const container = document.getElementById('testResult');
    const icon = document.getElementById('testResultIcon');
    const msg = document.getElementById('testResultMessage');

    container.style.display = 'flex';
    container.className = `test-result ${success ? 'test-success' : 'test-error'}`;
    icon.className = `lucide ${success ? 'lucide-circle-check' : 'lucide-circle-x'}`;
    msg.textContent = message;

    // Auto-hide after 5 seconds
    setTimeout(() => {
        container.style.display = 'none';
    }, 5000);
}

function toggleTokenVisibility() {
    const input = document.getElementById('posToken');
    const icon = document.getElementById('tokenToggleIcon');

    if (input.type === 'password') {
        input.type = 'text';
        icon.className = 'lucide lucide-eye-off';
    } else {
        input.type = 'password';
        icon.className = 'lucide lucide-eye';
    }
}

// --- USB Power Settings ---

let _uhubctlAvailable = false;

async function loadUsbPowerSettings() {
    try {
        const res = await fetch(`${API_BASE}/settings/usb-power`);
        if (!res.ok) return;
        const data = await res.json();

        _uhubctlAvailable = data.uhubctl_available;
        document.getElementById('usbPowerMethod').value = data.method || 'bind_unbind';
        updateUsbPowerHints();
    } catch (err) {
        console.error('Failed to load USB power settings:', err);
    }
}

function updateUsbPowerHints() {
    const method = document.getElementById('usbPowerMethod').value;
    const hintEl = document.getElementById('usbPowerHint');
    const warningEl = document.getElementById('uhubctlWarning');
    const unavailEl = document.getElementById('uhubctlUnavailable');

    warningEl.style.display = 'none';
    unavailEl.style.display = 'none';

    if (method === 'bind_unbind') {
        hintEl.textContent = 'Bind/Unbind trennt das Geraet logisch vom System. Sicher fuer andere USB-Geraete.';
    } else if (method === 'uhubctl') {
        hintEl.textContent = 'uhubctl schaltet den USB-Strom physisch ab. Scanner startet bei Aktivierung komplett neu.';
        warningEl.style.display = 'flex';
        if (!_uhubctlAvailable) {
            unavailEl.style.display = 'flex';
        }
    } else {
        hintEl.textContent = 'USB-Stromsteuerung deaktiviert. Scanner bleibt dauerhaft eingeschaltet.';
    }
}

async function saveUsbPowerSettings() {
    const btn = document.getElementById('btnSaveUsb');
    btn.disabled = true;

    const method = document.getElementById('usbPowerMethod').value;

    try {
        const res = await fetch(`${API_BASE}/settings/usb-power`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ method }),
        });

        if (res.ok) {
            showUsbTestResult(true, 'USB-Einstellungen gespeichert');
        } else {
            showUsbTestResult(false, `Fehler beim Speichern (HTTP ${res.status})`);
        }
    } catch (err) {
        showUsbTestResult(false, `Fehler: ${err.message}`);
    } finally {
        btn.disabled = false;
    }
}

function showUsbTestResult(success, message) {
    const container = document.getElementById('usbTestResult');
    const icon = document.getElementById('usbTestResultIcon');
    const msg = document.getElementById('usbTestResultMessage');

    container.style.display = 'flex';
    container.className = `test-result ${success ? 'test-success' : 'test-error'}`;
    icon.className = `lucide ${success ? 'lucide-circle-check' : 'lucide-circle-x'}`;
    msg.textContent = message;

    setTimeout(() => {
        container.style.display = 'none';
    }, 5000);
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
