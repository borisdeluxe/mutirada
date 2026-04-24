# Agency Monitor — Design Spec

**Date:** 2026-04-24
**Status:** Draft
**Scope:** Live Agent-Monitoring Dashboard für Pluribus Agency

---

## 1. Overview

Lightweight Monitoring-Dashboard für die Pluribus Agency. Zeigt live, was die Agenten tun, welche Features in der Pipeline sind, und den aktuellen System-Status.

### Goals

- Live-Überblick über alle laufenden Agenten und Features
- Browser-Zugang, 1 Nutzer (Boris)
- Zero zusätzliche Infrastruktur (kein Grafana, kein Prometheus)
- Minimaler Footprint auf dem Agency-Server

### Non-Goals

- Multi-User Auth
- Alerting (das macht Slack)
- Log-Aggregation (tmux-Sessions direkt einsehbar via SSH)
- Metriken-History >7 Tage

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Orchestrator (Python)                                          │
│                                                                 │
│  _collect_agency_snapshot()                                     │
│  ├─ every 10s: collect agent states → Postgres (live_snapshot)  │
│  ├─ on state change: write event → Postgres (events)            │
│  └─ daily: DELETE snapshots older than 7 days                  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Postgres               │
                    │                        │
                    │ agency_live_snapshot   │  ← Single row, updated every 10s
                    │ agency_events          │  ← Append-only event log
                    │ agency_metrics_hourly  │  ← Aggregated metrics
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────────────────────┐
                    │ Monitor API (FastAPI)                  │
                    │ Port 8080 (intern) oder via Caddy      │
                    │                                        │
                    │ GET /api/live       ← Live snapshot    │
                    │ GET /api/events     ← Recent events    │
                    │ GET /api/features   ← Feature status   │
                    │ POST /api/command   ← pause/resume     │
                    │                                        │
                    │ Auth: X-Agency-Secret header           │
                    └───────────┬────────────────────────────┘
                                │
                                ▼
                    ┌────────────────────────────────────────┐
                    │ Dashboard (Static SPA)                 │
                    │ https://agency.falara.io oder          │
                    │ http://46.224.92.156:8080              │
                    │                                        │
                    │ - HTML/CSS/JS (kein Framework nötig)   │
                    │ - Auto-Refresh 10s                     │
                    │ - Admin-Key in localStorage            │
                    └────────────────────────────────────────┘
```

---

## 3. Data Model

### 3.1 Live Snapshot (Single Row)

```sql
CREATE TABLE agency_live_snapshot (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- Singleton
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data JSONB NOT NULL
);
```

**Snapshot Structure:**

```json
{
  "recorded_at": "2026-04-24T14:30:15Z",
  "system": {
    "cpu_percent": 42.3,
    "ram_percent": 67.1,
    "disk_percent": 54.8
  },
  "budget": {
    "today_eur": 4.20,
    "today_limit_eur": 20.00,
    "week_eur": 34.50,
    "week_limit_eur": 100.00
  },
  "agents": [
    {
      "id": "implementer",
      "status": "running",
      "feature": "FAL-123-new-endpoint",
      "started_at": "2026-04-24T14:25:00Z",
      "pid": 12345,
      "tmux_session": "agent-impl-FAL-123"
    },
    {
      "id": "security_reviewer",
      "status": "idle",
      "feature": null,
      "last_run": "2026-04-24T14:20:00Z"
    }
  ],
  "features": [
    {
      "id": "FAL-123-new-endpoint",
      "status": "in_progress",
      "current_agent": "implementer",
      "started_at": "2026-04-24T14:00:00Z",
      "cost_eur": 1.23,
      "progress": ["concept_clarifier", "architect_planner", "test_designer"]
    }
  ],
  "queue": {
    "pending": 2,
    "next": "FAL-124-bugfix"
  }
}
```

### 3.2 Events (Append-Only Log)

```sql
CREATE TABLE agency_events (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL,  -- agent_started, agent_finished, gate_passed, gate_failed, error, budget_warning
    feature_id TEXT,
    agent_id TEXT,
    data JSONB,
    
    -- Retention
    CONSTRAINT events_max_age CHECK (created_at > NOW() - INTERVAL '7 days')
);

CREATE INDEX idx_events_created ON agency_events (created_at DESC);
CREATE INDEX idx_events_feature ON agency_events (feature_id) WHERE feature_id IS NOT NULL;
```

**Event Types:**

| Type | Beschreibung | Data |
|------|--------------|------|
| `agent_started` | Agent hat Arbeit begonnen | `{agent, feature, worktree}` |
| `agent_finished` | Agent fertig | `{agent, feature, status, duration_s, cost_eur}` |
| `gate_passed` | Gate erfolgreich | `{agent, feature, next_agent}` |
| `gate_failed` | Gate fehlgeschlagen | `{agent, feature, reason, retry_count}` |
| `feature_started` | Neues Feature in Pipeline | `{feature, source}` |
| `feature_completed` | Feature durch alle Stages | `{feature, total_cost_eur, duration_min}` |
| `budget_warning` | 80% Budget erreicht | `{scope, current, limit}` |
| `error` | Fehler | `{agent, feature, error}` |

### 3.3 Hourly Metrics (Aggregated)

```sql
CREATE TABLE agency_metrics_hourly (
    hour TIMESTAMPTZ PRIMARY KEY,
    features_started INT DEFAULT 0,
    features_completed INT DEFAULT 0,
    features_failed INT DEFAULT 0,
    total_cost_eur NUMERIC(10,4) DEFAULT 0,
    total_tokens_in BIGINT DEFAULT 0,
    total_tokens_out BIGINT DEFAULT 0,
    avg_feature_duration_min NUMERIC(10,2)
);
```

---

## 4. API Endpoints

### `GET /api/live`

Aktueller Snapshot.

**Response:**

```json
{
  "snapshot": { ... },  // agency_live_snapshot.data
  "age_seconds": 5
}
```

### `GET /api/events?limit=50&feature=FAL-123`

Letzte Events.

**Response:**

```json
{
  "events": [
    {
      "id": 1234,
      "created_at": "2026-04-24T14:30:15Z",
      "event_type": "agent_finished",
      "feature_id": "FAL-123",
      "agent_id": "implementer",
      "data": { "status": "success", "duration_s": 180 }
    }
  ]
}
```

### `GET /api/features?status=in_progress`

Features mit Status.

### `POST /api/command`

Steuerung (optional, kann auch rein Slack sein).

```json
{
  "action": "pause_feature",
  "feature_id": "FAL-123"
}
```

---

## 5. Frontend

### 5.1 Tech Stack

- **Vanilla HTML/CSS/JS** — kein Build-Step, kein Framework
- **~500 LOC** — Single `index.html` mit inline CSS/JS
- **Auto-Refresh** — `setInterval` 10s
- **Auth** — Secret in localStorage, gesendet als `X-Agency-Secret` Header

### 5.2 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Agency Monitor                            [Refresh] [Settings] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │
│ │ CPU: 42%    │ │ RAM: 67%    │ │ Today: €4.20│ │ Queue: 2    │ │
│ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ │
│                                                                 │
│ AGENTS                                                          │
│ ┌───────────────────────────────────────────────────────────┐  │
│ │ ● implementer      FAL-123  running   5min                │  │
│ │ ○ security_rev     —        idle      last: 10min ago     │  │
│ │ ○ qa_validator     —        idle      last: 15min ago     │  │
│ │ ○ deploy_runner    —        idle      last: 2h ago        │  │
│ └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│ FEATURES IN PIPELINE                                            │
│ ┌───────────────────────────────────────────────────────────┐  │
│ │ FAL-123  new-endpoint   ████████░░  implementer   €1.23   │  │
│ │ FAL-124  bugfix         ░░░░░░░░░░  queued        —       │  │
│ └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│ RECENT EVENTS                                                   │
│ ┌───────────────────────────────────────────────────────────┐  │
│ │ 14:30  gate_passed     FAL-123  test_designer → impl      │  │
│ │ 14:25  agent_finished  FAL-123  test_designer  42s €0.08  │  │
│ │ 14:20  agent_started   FAL-123  test_designer             │  │
│ └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Visual States

| Agent Status | Indicator |
|--------------|-----------|
| `running` | 🟢 Grüner Punkt, pulsierend |
| `idle` | ⚪ Grauer Punkt |
| `error` | 🔴 Roter Punkt |
| `paused` | 🟡 Gelber Punkt |

| Feature Progress | Bar |
|------------------|-----|
| 1/7 agents done | `█░░░░░░` |
| 4/7 agents done | `████░░░` |
| completed | `███████` grün |
| failed | `████░░░` rot |

---

## 6. Hosting

### Option A: Auf Agency-Server (CAX31)

```
Caddy oder nginx auf Port 443
├── /api/* → localhost:8080 (Monitor API)
└── /* → /opt/agency/monitor/static/
```

**Domain:** `agency.falara.io` (A-Record auf CAX31 IP)

### Option B: Auf Falara-Prod-Server

Falls CAX31 keinen Public-Zugang haben soll:
- Monitor-API läuft auf CAX31
- Caddy auf Prod-Server proxied `/agency/*` zu CAX31 via WireGuard

### Empfehlung

**Option A** — einfacher, Agency-Server hat eh Public IP für GitHub Webhooks.

---

## 7. Auth

**Single-User, Simple:**

1. `AGENCY_MONITOR_SECRET` in `.env` auf Server
2. Dashboard fragt beim ersten Load nach Secret
3. Secret wird in `localStorage` gespeichert
4. Jeder API-Request sendet `X-Agency-Secret` Header
5. API vergleicht mit Env-Var

Kein Login-Flow, keine Sessions, keine DB-User.

---

## 8. Implementation

### Phase 1a (MVP)

| Task | Aufwand |
|------|---------|
| Postgres Migrations | 1h |
| Snapshot Collection im Orchestrator | 2h |
| Monitor API (FastAPI, 4 Endpoints) | 3h |
| Dashboard HTML/CSS/JS | 4h |
| Caddy Config | 0.5h |
| **Total** | **~10h** |

### Phase 1b (Nice-to-have)

- tmux Session-Attach via Browser (ttyd)
- Cost-Graph (7-Tage Sparkline)
- Feature-Detail-View

---

## 9. Nicht in Scope

- **Logs:** tmux-Sessions direkt via SSH einsehen
- **Alerts:** Slack übernimmt das
- **Multi-User:** Nur Boris
- **Mobile PWA:** Desktop-First, Mobile funktioniert aber

---

## 10. Referenzen

- Falara Monitoring: `~/projects/falara/docs/superpowers/specs/done/2026-03-21-monitoring-dashboard-design.md`
- TK14 Observability Layer: `TK14_Autonome_Entwicklungsagentur_v0.yaml`
