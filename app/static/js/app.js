// =============================================================================
// DeviceBox - IoT Gateway Dashboard
// =============================================================================

const API_BASE = window.location.origin;
let writeValue = 0;
let pollInterval = null;

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    fetchHealth();
    fetchInfo();
    // Poll health every 10 seconds
    pollInterval = setInterval(fetchHealth, 10000);
});

// --- API Calls ---

async function fetchHealth() {
    try {
        const res = await fetch(`${API_BASE}/health`);
        const data = await res.json();
        const el = document.getElementById('healthStatus');
        const card = document.getElementById('healthCard');
        const status = document.getElementById('connectionStatus');

        if (data.status === 'ok') {
            el.textContent = 'Online';
            el.style.color = 'var(--green)';
            status.className = 'header-status online';
            status.innerHTML = '<i class="lucide lucide-wifi"></i><span>Verbunden</span>';
        } else {
            el.textContent = 'Fehler';
            el.style.color = 'var(--red)';
            setOffline();
        }
    } catch (err) {
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

async function readGPIO() {
    const pin = parseInt(document.getElementById('readPin').value);
    if (isNaN(pin) || pin < 0) {
        addLog('warn', 'Ungueltiger Pin');
        return;
    }

    const btn = document.getElementById('readBtn');
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/device/gpio/read`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin }),
        });

        const data = await res.json();

        if (res.ok) {
            const resultEl = document.getElementById('readResult');
            const valueEl = document.getElementById('readValue');
            resultEl.style.display = 'flex';
            valueEl.textContent = data.value === 1 ? 'HIGH (1)' : 'LOW (0)';
            valueEl.className = `result-value ${data.value === 1 ? 'high' : 'low'}`;
            addLog('success', `Pin ${pin} gelesen: ${data.value === 1 ? 'HIGH' : 'LOW'}`);
        } else {
            addLog('error', `Fehler beim Lesen von Pin ${pin}: ${data.detail}`);
        }
    } catch (err) {
        addLog('error', `Netzwerkfehler: ${err.message}`);
    } finally {
        btn.disabled = false;
    }
}

async function writeGPIO() {
    const pin = parseInt(document.getElementById('writePin').value);
    if (isNaN(pin) || pin < 0) {
        addLog('warn', 'Ungueltiger Pin');
        return;
    }

    const btn = document.getElementById('writeBtn');
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/device/gpio/write`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin, value: writeValue }),
        });

        const data = await res.json();

        if (res.ok) {
            const resultEl = document.getElementById('writeResult');
            const statusEl = document.getElementById('writeStatus');
            resultEl.style.display = 'flex';
            statusEl.textContent = 'Erfolgreich';
            statusEl.className = 'result-value success';
            addLog('success', `Pin ${pin} auf ${writeValue === 1 ? 'HIGH' : 'LOW'} gesetzt`);

            // Auto-hide result after 3s
            setTimeout(() => {
                resultEl.style.display = 'none';
            }, 3000);
        } else {
            const resultEl = document.getElementById('writeResult');
            const statusEl = document.getElementById('writeStatus');
            resultEl.style.display = 'flex';
            statusEl.textContent = 'Fehler';
            statusEl.className = 'result-value error';
            addLog('error', `Fehler beim Schreiben auf Pin ${pin}: ${data.detail}`);
        }
    } catch (err) {
        addLog('error', `Netzwerkfehler: ${err.message}`);
    } finally {
        btn.disabled = false;
    }
}

// --- UI Helpers ---

function setWriteValue(val) {
    writeValue = val;
    document.getElementById('valLow').className = `toggle-btn ${val === 0 ? 'active' : ''}`;
    document.getElementById('valHigh').className = `toggle-btn ${val === 1 ? 'active' : ''}`;
}

function setOffline() {
    const status = document.getElementById('connectionStatus');
    status.className = 'header-status offline';
    status.innerHTML = '<i class="lucide lucide-wifi-off"></i><span>Getrennt</span>';
}

// --- Log ---

function addLog(type, message) {
    const container = document.getElementById('logContainer');
    const empty = container.querySelector('.log-empty');
    if (empty) empty.remove();

    const now = new Date();
    const time = now.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `<span class="log-time">${time}</span><span class="log-msg ${type}">${message}</span>`;

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
