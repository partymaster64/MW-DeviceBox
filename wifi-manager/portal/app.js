// =============================================================================
// DeviceBox – Captive Portal WLAN-Einrichtung
// =============================================================================

let selectedSsid = '';
let selectedSecurity = '';
let networks = [];

// --- Initialisierung ---

document.addEventListener('DOMContentLoaded', () => {
    checkLastError();
    scanNetworks();
});

// --- Status pruefen (Fehlermeldung nach Reconnect) ---

async function checkLastError() {
    try {
        const res = await fetch('/api/wifi/status');
        if (!res.ok) return;
        const data = await res.json();

        if (data.last_error) {
            showBanner('error', data.last_error);
        }

        if (data.connected) {
            showBanner('success', 'WLAN verbunden! Sie koennen dieses Fenster schliessen.');
        }
    } catch {
        // Portal gerade gestartet, normal
    }
}

// --- Netzwerke scannen ---

async function scanNetworks() {
    const btn = document.getElementById('btnScan');
    const list = document.getElementById('networkList');

    btn.classList.add('scanning');
    list.innerHTML = `
        <div class="network-empty">
            <div class="spinner-small"></div>
            <span>Netzwerke werden gesucht...</span>
        </div>
    `;

    try {
        const res = await fetch('/api/wifi/scan');
        if (!res.ok) throw new Error('Scan fehlgeschlagen');
        const data = await res.json();

        networks = data.networks || [];
        renderNetworks();
    } catch (err) {
        list.innerHTML = `
            <div class="network-empty">
                Suche fehlgeschlagen. Bitte erneut versuchen.
            </div>
        `;
    } finally {
        btn.classList.remove('scanning');
    }
}

// --- Netzwerke anzeigen ---

function renderNetworks() {
    const list = document.getElementById('networkList');

    if (networks.length === 0) {
        list.innerHTML = `
            <div class="network-empty">
                Keine Netzwerke gefunden. Bitte erneut suchen.
            </div>
        `;
        return;
    }

    list.innerHTML = networks.map(net => {
        const isSelected = net.ssid === selectedSsid;
        const isSecured = net.security !== 'Offen';
        const bars = getSignalBars(net.signal);

        return `
            <div class="network-item ${isSelected ? 'selected' : ''}"
                 onclick="selectNetwork('${escapeAttr(net.ssid)}', '${escapeAttr(net.security)}')">
                <div class="signal-bars">
                    ${bars}
                </div>
                <div class="network-info">
                    <div class="network-name">${escapeHtml(net.ssid)}</div>
                    <div class="network-security">${escapeHtml(net.security)}</div>
                </div>
                ${isSecured ? `
                    <div class="network-lock">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>
                            <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                        </svg>
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');
}

function getSignalBars(signal) {
    // signal ist 0-100
    const level = signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1;
    let html = '';
    for (let i = 1; i <= 4; i++) {
        html += `<div class="signal-bar ${i <= level ? 'active' : ''}"></div>`;
    }
    return html;
}

// --- Netzwerk auswaehlen ---

function selectNetwork(ssid, security) {
    selectedSsid = ssid;
    selectedSecurity = security;

    // Netzwerke neu rendern (Markierung aktualisieren)
    renderNetworks();

    // Connect-Bereich anzeigen
    const section = document.getElementById('connectSection');
    const ssidEl = document.getElementById('selectedSsid');
    const pwGroup = document.getElementById('passwordGroup');
    const pwInput = document.getElementById('wifiPassword');

    section.style.display = 'block';
    ssidEl.textContent = ssid;

    if (security === 'Offen') {
        pwGroup.style.display = 'none';
        pwInput.value = '';
    } else {
        pwGroup.style.display = 'block';
        pwInput.value = '';
        pwInput.focus();
    }

    // Zum Connect-Bereich scrollen
    section.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// --- Verbinden ---

async function connectToNetwork() {
    if (!selectedSsid) return;

    const password = document.getElementById('wifiPassword').value;
    const btn = document.getElementById('btnConnect');

    // Gesichert aber kein Passwort?
    if (selectedSecurity !== 'Offen' && !password) {
        showBanner('error', 'Bitte Passwort eingeben');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Verbindung wird hergestellt...';

    try {
        const res = await fetch('/api/wifi/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ssid: selectedSsid,
                password: password,
            }),
        });

        const data = await res.json();

        if (data.success) {
            // Overlay anzeigen – AP wird gleich gestoppt
            showConnectingOverlay();
        } else {
            showBanner('error', data.message || 'Verbindung fehlgeschlagen');
            btn.disabled = false;
            btn.textContent = 'Verbinden';
        }
    } catch {
        // Verbindung zum Portal verloren = AP wurde gestoppt (erwartet)
        showConnectingOverlay();
    }
}

async function connectManual() {
    const ssid = document.getElementById('manualSsid').value.trim();
    const password = document.getElementById('manualPassword').value;

    if (!ssid) {
        showBanner('error', 'Bitte Netzwerkname eingeben');
        return;
    }

    selectedSsid = ssid;
    selectedSecurity = password ? 'WPA' : 'Offen';

    try {
        const res = await fetch('/api/wifi/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ssid, password }),
        });

        const data = await res.json();
        if (data.success) {
            showConnectingOverlay();
        } else {
            showBanner('error', data.message || 'Verbindung fehlgeschlagen');
        }
    } catch {
        showConnectingOverlay();
    }
}

// --- UI Helpers ---

function showConnectingOverlay() {
    document.getElementById('connectingOverlay').style.display = 'flex';
}

function showBanner(type, message) {
    const banner = document.getElementById('banner');
    const icon = document.getElementById('bannerIcon');
    const text = document.getElementById('bannerText');

    const icons = {
        error: '\u26A0',     // ⚠
        success: '\u2705',   // ✅
        info: '\u2139',      // ℹ
    };

    banner.className = `banner banner-${type}`;
    banner.style.display = 'flex';
    icon.textContent = icons[type] || '';
    text.textContent = message;

    // Auto-Hide nach 8 Sekunden (außer success)
    if (type !== 'success') {
        setTimeout(() => {
            banner.style.display = 'none';
        }, 8000);
    }
}

function togglePassword() {
    const input = document.getElementById('wifiPassword');
    input.type = input.type === 'password' ? 'text' : 'password';
}

function toggleManual() {
    const section = document.getElementById('manualSection');
    const btn = document.getElementById('btnManualToggle');
    const isOpen = section.style.display !== 'none';

    section.style.display = isOpen ? 'none' : 'block';
    btn.classList.toggle('open', !isOpen);
}

// --- Escape-Funktionen ---

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/"/g, '\\"');
}
