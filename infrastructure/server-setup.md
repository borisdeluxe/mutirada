# Agency Server Setup

**Server:** Hetzner cx43 (8 vCPU, 16GB RAM, 160GB SSD)
**IP:** 46.225.19.209
**OS:** Ubuntu 24.04.3 LTS
**Hostname:** pluribus-16gb-nbg1-1

## Installed Packages

| Package | Version |
|---------|---------|
| Node.js | 22.22.2 |
| npm | 10.9.7 |
| PostgreSQL | 16.13 |
| Caddy | 2.11.2 |
| Git | 2.43.0 |
| tmux | installed |
| htop | installed |
| ufw | installed |
| jq | installed |

## Users

| User | Purpose |
|------|---------|
| `agency` | Main service user, owns /opt/agency |
| `agent-orchestrator` | Orchestrator service |
| `agent-impl` | Implementer agent |
| `agent-deploy` | Deploy runner (restricted SSH) |

## Directory Structure

```
/opt/agency/
├── .env                    # Credentials (600, agency:agency)
├── .claude/
│   ├── agents/             # Role system prompts
│   └── skills/             # Skill definitions
├── .pipeline/              # Per-feature artifacts
├── repos/                  # Bare git clones
├── worktrees/              # Feature worktrees
├── logs/                   # Service logs
├── monitor/
│   └── static/             # Dashboard HTML/CSS/JS
└── reports/
    ├── daily/
    └── weekly/
```

## Database

**Database:** agency_db
**User:** agency
**Connection:** `postgresql://agency:<password>@localhost:5432/agency_db`

### Tables

| Table | Purpose |
|-------|---------|
| `agency_live_snapshot` | Current system state (singleton) |
| `agency_events` | Event log (7-day retention) |
| `agency_metrics_hourly` | Aggregated hourly metrics |
| `agency_tasks` | Persistent task queue |
| `pipeline_metrics` | Per-agent-run metrics |

## Credentials

Stored in `/opt/agency/.env`:
- `DATABASE_URL` — Postgres connection string
- `AGENCY_MONITOR_SECRET` — Dashboard auth token

## Completed

- [x] Caddy configuration (Caddyfile)
- [x] Claude CLI (v2.1.119)
- [x] Firewall (ufw: 22, 80, 443)
- [x] SSH key for GitHub (agency@pluribus)

## Pending

- [ ] DNS: agency.falara.io → 46.225.19.209
- [ ] Add SSH key to GitHub as deploy key
- [ ] systemd services (orchestrator, monitor-api)
- [ ] Clone falara repo

## SSH Key for GitHub

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGvicg5kp3j+luvD70IDP/f0j5e9tSNodIR3GMDxtGgk agency@pluribus
```

Add this as **deploy key** to `borisdeluxe/falara` (read-only) or as SSH key to your GitHub account.
