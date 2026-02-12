# DeviceBox POS-Integration -- Prompt fuer POS-System-Entwicklung

Du bist ein Senior Full-Stack-Entwickler. Implementiere die DeviceBox-Integration in einem bestehenden Next.js POS-System. Die DeviceBox ist ein IoT-Gateway (Raspberry Pi), das USB-Barcode-Scanner verwaltet und gescannte Barcodes an das POS-System sendet.

---

## Kontext

Die **DeviceBox** ist ein Raspberry Pi mit einem Docker-Container, der:
- USB-Barcode-Scanner automatisch erkennt (Datalogic Touch 65 und andere HID-Geraete)
- Die POS-API regelmaessig abfragt (Polling), um zu pruefen, ob ein Scan-Vorgang angefordert wird
- Gescannte Barcodes in Echtzeit an die POS-API zuruecksendet
- Ueber `devicebox.local` im lokalen Netzwerk erreichbar ist

Die Kommunikation ist **unidirektional vom DeviceBox-Client zum POS-Server**: Die DeviceBox pollt die POS-API, nicht umgekehrt.

---

## Architektur-Ueberblick

```
POS System (Next.js)                    DeviceBox (Raspberry Pi)
┌─────────────────────┐                 ┌─────────────────────┐
│                     │   HTTP/REST     │                     │
│  GET /api/device-   │ ◄────────────── │  POS Polling        │
│  box/session        │   alle 2s       │  Service            │
│                     │                 │                     │
│  POST /api/device-  │ ◄────────────── │  Barcode            │
│  box/barcode        │   bei Scan      │  Scanner            │
│                     │                 │                     │
└─────────────────────┘                 └─────────────────────┘
```

**Ablauf:**
1. POS-Benutzer startet einen Scan-Vorgang in der POS-Oberflaeche
2. POS-System erstellt eine Scan-Session (UUID) und speichert sie
3. DeviceBox pollt `GET /api/devicebox/session` und erkennt die aktive Session
4. DeviceBox aktiviert den Barcode-Scanner
5. Benutzer scannt Barcode → DeviceBox sendet `POST /api/devicebox/barcode`
6. POS-System empfaengt den Barcode und verarbeitet ihn (z.B. Produktsuche)
7. POS-Benutzer beendet den Scan-Vorgang → Session wird deaktiviert
8. DeviceBox erkennt beim naechsten Poll, dass keine Session aktiv ist, und stoppt den Scanner

---

## API-Kontrakt

Das POS-System muss folgende zwei Endpoints implementieren:

### 1. `GET /api/devicebox/session`

**Zweck:** Die DeviceBox fragt ab, ob ein Scan-Vorgang angefordert wird.

**Authentifizierung:** `Authorization: Bearer {token}` Header (siehe unten)

**Response wenn eine Session aktiv ist:**

```json
{
  "active": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response wenn keine Session aktiv ist:**

```json
{
  "active": false,
  "session_id": null
}
```

**Response-Schema:**

| Feld         | Typ              | Beschreibung                        |
| ------------ | ---------------- | ----------------------------------- |
| `active`     | `boolean`        | Ob eine Scan-Session aktiv ist      |
| `session_id` | `string \| null` | UUID der Session, oder null         |

**Fehlerbehandlung:**
- `401 Unauthorized` → Token ungueltig oder fehlend
- `500 Internal Server Error` → DeviceBox versucht es erneut

**Wichtig:** Die DeviceBox pollt diesen Endpoint alle 1-2 Sekunden. Der Endpoint muss schnell antworten (< 200ms). Keine aufwendigen Datenbankabfragen oder Berechnungen.

---

### 2. `POST /api/devicebox/barcode`

**Zweck:** Die DeviceBox sendet einen gescannten Barcode an das POS-System.

**Authentifizierung:** `Authorization: Bearer {token}` Header

**Request Body:**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "barcode": "4006381333931",
  "timestamp": "2026-02-12T12:30:45",
  "device_name": "Datalogic Touch 65"
}
```

**Request-Schema:**

| Feld          | Typ      | Beschreibung                              |
| ------------- | -------- | ----------------------------------------- |
| `session_id`  | `string` | UUID der Session (muss aktiv sein)        |
| `barcode`     | `string` | Der gescannte Barcode-Inhalt              |
| `timestamp`   | `string` | ISO 8601 Zeitstempel des Scans            |
| `device_name` | `string` | Name des Scanners (z.B. "Datalogic Touch 65") |

**Success Response:**

```json
{
  "ok": true
}
```

**Error Responses:**
- `401 Unauthorized` → Token ungueltig
- `400 Bad Request` → Session nicht aktiv oder ungueltige Daten
- `404 Not Found` → Session-ID nicht gefunden

---

## Authentifizierung

Die Kommunikation wird durch einen **Bearer Token** geschuetzt:

1. Das POS-System generiert einen zufaelligen Token (z.B. `crypto.randomUUID()` oder ein JWT)
2. Der Token wird in der POS-Datenbank gespeichert
3. Der Benutzer kopiert den Token und traegt ihn in der DeviceBox-Web-GUI ein (`devicebox.local/settings`)
4. Alle Requests der DeviceBox enthalten den Header: `Authorization: Bearer {token}`

### Token-Generierung (Beispiel)

```typescript
// In der POS-Verwaltungsoberflaeche
import { randomUUID } from 'crypto';

async function generateDeviceBoxToken(): Promise<string> {
  const token = randomUUID();
  // Token in der Datenbank speichern
  await db.settings.upsert({
    where: { key: 'devicebox_token' },
    update: { value: token },
    create: { key: 'devicebox_token', value: token },
  });
  return token;
}
```

### Token-Validierung (Middleware)

```typescript
// middleware oder API-Route
function validateDeviceBoxToken(request: Request): boolean {
  const authHeader = request.headers.get('Authorization');
  if (!authHeader?.startsWith('Bearer ')) return false;

  const token = authHeader.slice(7);
  const storedToken = await db.settings.findUnique({
    where: { key: 'devicebox_token' },
  });

  return storedToken?.value === token;
}
```

---

## Implementierungs-Anforderungen

### 1. Session-Management

```typescript
// Beispiel: In-Memory oder Redis-basiert
interface ScanSession {
  id: string;           // UUID
  active: boolean;
  createdAt: Date;
  barcodes: string[];   // Empfangene Barcodes
}
```

- Sessions muessen schnell abrufbar sein (In-Memory, Redis, oder schneller DB-Query)
- Nur EINE Session kann gleichzeitig aktiv sein
- Sessions haben ein Timeout (z.B. 5 Minuten ohne Aktivitaet)
- Wenn eine neue Session gestartet wird, wird die alte automatisch beendet

### 2. API-Routen (Next.js App Router)

Erstelle folgende Dateien:

**`app/api/devicebox/session/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  // 1. Token validieren
  // 2. Aktive Session abfragen
  // 3. Response zurueckgeben
}
```

**`app/api/devicebox/barcode/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  // 1. Token validieren
  // 2. Session pruefen (aktiv + session_id stimmt)
  // 3. Barcode verarbeiten (z.B. Produktsuche, Event emittieren)
  // 4. Response zurueckgeben
}
```

### 3. Frontend-Integration

Das POS-Frontend braucht:

- **"Scan starten" Button** → Erstellt eine Session und zeigt einen Warte-Indikator
- **Echtzeit-Updates** → Empfangene Barcodes werden sofort angezeigt (z.B. via SSE, WebSocket, oder Polling)
- **"Scan beenden" Button** → Deaktiviert die Session
- **Token-Verwaltung** → Seite zum Generieren/Anzeigen des DeviceBox-Tokens

### 4. Barcode-Verarbeitung

Wenn ein Barcode empfangen wird:

```typescript
async function handleBarcode(sessionId: string, barcode: string) {
  // Option A: Event an Frontend senden (SSE/WebSocket)
  eventEmitter.emit('barcode', { sessionId, barcode });

  // Option B: In Session speichern, Frontend pollt
  await addBarcodeToSession(sessionId, barcode);

  // Option C: Direkt verarbeiten (z.B. Produkt suchen)
  const product = await findProductByBarcode(barcode);
  if (product) {
    await addToCart(sessionId, product);
  }
}
```

---

## CORS-Konfiguration

Die DeviceBox sendet Requests von einer anderen Origin (`devicebox.local`). Das POS-System muss CORS korrekt konfigurieren.

**`next.config.js`:**

```javascript
module.exports = {
  async headers() {
    return [
      {
        source: '/api/devicebox/:path*',
        headers: [
          { key: 'Access-Control-Allow-Origin', value: '*' },
          { key: 'Access-Control-Allow-Methods', value: 'GET, POST, OPTIONS' },
          { key: 'Access-Control-Allow-Headers', value: 'Authorization, Content-Type' },
        ],
      },
    ];
  },
};
```

**Hinweis:** In Produktion sollte `Access-Control-Allow-Origin` auf die spezifische DeviceBox-Adresse beschraenkt werden.

---

## Fehlerbehandlung

Die DeviceBox behandelt Fehler wie folgt:
- **POS nicht erreichbar:** Wartet und versucht es erneut (alle `poll_interval` Sekunden)
- **401 Unauthorized:** Zeigt Fehler in der DeviceBox-GUI an
- **Barcode-Send fehlgeschlagen:** Loggt den Fehler, versucht es NICHT erneut (Barcode geht verloren)

Das POS-System sollte:
- Immer innerhalb von 5 Sekunden antworten
- Bei internen Fehlern `500` mit einer Fehlermeldung zurueckgeben
- Keine Seiteneffekte bei `GET /api/devicebox/session` haben (idempotent)

---

## Zusammenfassung der zu implementierenden Dateien

| Datei                                  | Zweck                                    |
| -------------------------------------- | ---------------------------------------- |
| `app/api/devicebox/session/route.ts`   | Session-Abfrage-Endpoint                 |
| `app/api/devicebox/barcode/route.ts`   | Barcode-Empfangs-Endpoint               |
| `lib/devicebox/auth.ts`               | Token-Validierung                        |
| `lib/devicebox/session.ts`            | Session-Management (erstellen/beenden)   |
| `components/BarcodeScanner.tsx`        | UI-Komponente fuer Scan-Steuerung        |
| `app/settings/devicebox/page.tsx`     | Token-Verwaltungsseite                   |

---

## Test-Szenario

1. POS-System starten, Token generieren
2. Token in DeviceBox-GUI eingeben (`devicebox.local/settings`)
3. Im POS-System "Scan starten" klicken
4. In der DeviceBox-GUI pruefen: POS-Status sollte "Session aktiv" anzeigen
5. Barcode scannen
6. Im POS-System pruefen: Barcode sollte erscheinen
7. "Scan beenden" klicken
8. In der DeviceBox-GUI pruefen: POS-Status sollte "Polling" anzeigen
