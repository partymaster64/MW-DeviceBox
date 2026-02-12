// =============================================================================
// DeviceBox - Einstellungen
// =============================================================================

const API_BASE = window.location.origin;
let statusPollInterval = null;

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadPosStatus();
    fetchFooterVersion();

    // Poll status every 3 seconds
    statusPollInterval = setInterval(loadPosStatus, 3000);
});

// --- API Calls ---

async function fetchFooterVersion() {
    try {
        const res = await fetch(`${API_BASE}/info`);
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById('footerVersion').textContent = `v${data.version}`;
    } catch {
        // ignore
    }
}

async function loadSettings() {
    try {
        const res = await fetch(`${API_BASE}/settings/pos`);
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById('posUrl').value = data.url || '';
        document.getElementById('posPollInterval').value = data.poll_interval || 2;

        if (data.token_set) {
            document.getElementById('posToken').placeholder = 'Schluessel gesetzt (nur aendern wenn noetig)';
        }
    } catch (err) {
        console.error('Einstellungen laden fehlgeschlagen:', err);
    }
}

async function loadPosStatus() {
    try {
        const res = await fetch(`${API_BASE}/settings/pos/status`);
        if (!res.ok) return;
        const data = await res.json();
        renderPosStatus(data);
    } catch {
        // ignore
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
            showTestResult(true, 'Einstellungen gespeichert!');
            if (data.token_set) {
                document.getElementById('posToken').value = '';
                document.getElementById('posToken').placeholder = 'Schluessel gesetzt (nur aendern wenn noetig)';
            }
        } else {
            showTestResult(false, `Speichern fehlgeschlagen (Fehler ${res.status})`);
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
        showTestResult(false, 'Bitte zuerst die Server-Adresse eingeben');
        btn.disabled = false;
        return;
    }

    let testToken = token;
    if (!testToken) {
        try {
            const res = await fetch(`${API_BASE}/settings/pos`);
            if (res.ok) {
                const data = await res.json();
                if (!data.token_set) {
                    showTestResult(false, 'Bitte Zugangsschluessel eingeben');
                    btn.disabled = false;
                    return;
                }
                showTestResult(false, 'Bitte Zugangsschluessel eingeben um die Verbindung zu testen');
                btn.disabled = false;
                return;
            }
        } catch {
            // fall through
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
            showTestResult(false, `Test fehlgeschlagen (Fehler ${res.status})`);
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
            label: 'Noch nicht eingerichtet',
            cssClass: 'status-warn',
        },
        'polling': {
            icon: 'lucide-radio',
            label: 'Verbunden und aktiv',
            cssClass: 'status-ok',
        },
        'session_active': {
            icon: 'lucide-scan-barcode',
            label: 'Scanner arbeitet',
            cssClass: 'status-active',
        },
        'error': {
            icon: 'lucide-circle-x',
            label: 'Verbindungsfehler',
            cssClass: 'status-error',
        },
        'stopped': {
            icon: 'lucide-circle-pause',
            label: 'Nicht aktiv',
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
        details.push('Scanner nicht verbunden');
    }
    detailEl.textContent = details.join(' \u2013 ');
}

function showTestResult(success, message) {
    const container = document.getElementById('testResult');
    const icon = document.getElementById('testResultIcon');
    const msg = document.getElementById('testResultMessage');

    container.style.display = 'flex';
    container.className = `test-result ${success ? 'test-success' : 'test-error'}`;
    icon.className = `lucide ${success ? 'lucide-circle-check' : 'lucide-circle-x'}`;
    msg.textContent = message;

    setTimeout(() => {
        container.style.display = 'none';
    }, 6000);
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
