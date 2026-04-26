# Agent Designer — Design Spec

## Übersicht

Der Agent Designer automatisiert die Pipeline-Konfiguration für neue Repositories. User gibt Repo-URL ein, Agent Designer erkennt Stack, stellt Rückfragen, generiert 9 Agent-Profile, klont Repo und registriert es beim Orchestrator.

## Entscheidungen

| Aspekt | Entscheidung |
|--------|--------------|
| Interface | API + Slack + Telegram + CLI |
| Stacks Phase 1 | FastAPI, React-Vite, Shopify-App, Shopware-Plugin |
| Output | Hybrid (Preview → PR oder ZIP) |
| Analyse | Hybrid mit Rückfragen |
| Templates | Dateien in `/opt/agency/templates/` |
| Registrierung | Klonen + Registrieren |
| Architektur | Modul im Orchestrator |

## Modulstruktur

```
orchestrator/
├── orchestrator/
│   ├── api.py                    # + neue Endpoints
│   ├── agent_designer/           # NEU
│   │   ├── __init__.py
│   │   ├── detector.py           # Stack-Erkennung
│   │   ├── generator.py          # Agent-Profile generieren
│   │   ├── repo_manager.py       # Klonen, Registrieren
│   │   └── conversation.py       # Rückfrage-Logik
│   ├── slack_bot.py              # + /configure Command
│   ├── telegram_bot.py           # + /configure Command
│   └── ...
└── templates/                    # NEU
    ├── base/
    │   └── _header.md            # Shared STATUS-Zeilen Doku
    ├── fastapi/
    │   ├── concept_clarifier.md
    │   ├── architect_planner.md
    │   ├── test_designer.md
    │   ├── implementer.md
    │   ├── security_reviewer.md
    │   ├── refactorer.md
    │   ├── qa_validator.md
    │   ├── docs_updater.md
    │   └── deploy_runner.md
    ├── react-vite/
    │   └── ... (9 Agents)
    ├── shopify-app/
    │   └── ... (9 Agents)
    └── shopware-plugin/
        └── ... (9 Agents)
```

## Stack Detection (`detector.py`)

Analysiert Repo-Root und erkennt Stack anhand von Marker-Dateien.

**Explizite Priorität** (spezifisch vor generisch):

```python
DETECTION_PRIORITY = [
    "shopify-app",
    "shopware-plugin",
    "react-vite",
    "fastapi",
]

STACK_SIGNATURES = {
    "shopify-app": {
        "required": ["shopify.app.toml"],
        "optional": ["package.json"],
        "package_markers": ["@shopify/shopify-app-remix", "@shopify/polaris"],
    },
    "shopware-plugin": {
        "required": ["composer.json"],
        "composer_markers": ["shopware/core"],
        "optional": ["src/Resources/app/administration/"],
    },
    "react-vite": {
        "required": ["package.json", "vite.config.ts"],
        "package_markers": ["react", "vite"],
    },
    "fastapi": {
        "required": ["pyproject.toml"],
        "pyproject_markers": ["fastapi"],
    },
}
```

**Output:**
```python
@dataclass
class StackDetectionResult:
    stack: str                    # "shopify-app"
    confidence: float             # 0.0-1.0
    detected_files: list[str]     # ["shopify.app.toml", "package.json"]
    suggested_commands: dict      # {"test": "npm test", "build": "npm run build"}
    questions: list[str]          # Rückfragen falls nötig
```

## Template System (`generator.py`)

Templates sind Jinja2-Dateien mit Platzhaltern:

```markdown
---
name: {{ agent_name }}
description: {{ agent_description }}
tools: {{ tools }}
---

## KRITISCH: STATUS-Zeile (PFLICHT)
{% include 'base/_header.md' %}

## Stack

- {{ stack_description }}

## Commands

```bash
{{ test_command }}      # Tests ausführen
{{ build_command }}     # Build prüfen
{{ lint_command }}      # Linting
```

## Patterns

{{ stack_patterns }}
```

**Template-Variablen:**

| Variable | Quelle |
|----------|--------|
| `agent_name` | Fest pro Agent |
| `test_command` | Rückfrage oder Auto-Detect aus package.json/pyproject.toml |
| `build_command` | Rückfrage oder Auto-Detect |
| `lint_command` | Rückfrage oder Auto-Detect |
| `stack_patterns` | Stack-spezifisch (React-Patterns, PHP-Patterns, etc.) |

## Conversation Flow (`conversation.py`)

State-Machine für Rückfragen:

```
States:
  INIT           → User sendet /configure <url>
  DETECTING      → Stack wird analysiert
  ASKING_COMMANDS → Rückfragen zu test/build/lint
  ASKING_CONFIRM  → Preview anzeigen, User bestätigt
  CLONING        → Repo wird geklont
  GENERATING     → Agents werden generiert
  REGISTERING    → Repo wird in DB registriert
  COMPLETE       → Fertig
  ERROR          → Fehler aufgetreten
  CANCELLED      → User hat abgebrochen
```

**Session-Storage:** DB-Tabelle `agent_designer_sessions`:

```sql
CREATE TABLE agent_designer_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) UNIQUE NOT NULL,
    chat_id VARCHAR(50),
    user_id VARCHAR(50),              -- NEU: User-spezifische Sessions
    source VARCHAR(20),               -- "slack", "telegram", "api", "cli"
    repo_url TEXT NOT NULL,
    stack VARCHAR(50),
    state VARCHAR(20) NOT NULL,
    data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sessions_active ON agent_designer_sessions (chat_id, user_id, state)
    WHERE state NOT IN ('COMPLETE', 'ERROR', 'CANCELLED');
```

**Session-Matching:** Antworten werden gegen `(chat_id, user_id)` gematcht, nicht nur `chat_id`. Verhindert Session-Hijacking in Team-Channels.

**Rate-Limiting:** Max 3 aktive Sessions pro `user_id`. Bei Überschreitung: "Du hast bereits 3 aktive Konfigurationen. Schließe eine ab oder nutze /cancel."

## Repo Manager (`repo_manager.py`)

```python
import re
from pathlib import Path
import subprocess

ALLOWED_HOSTS = ["github.com", "gitlab.com", "bitbucket.org"]
REPO_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

class RepoManager:
    REPOS_DIR = Path("/opt/agency/repos")
    
    def validate_url(self, repo_url: str) -> bool:
        """Validiert URL gegen Whitelist. Verhindert Command Injection."""
        from urllib.parse import urlparse
        parsed = urlparse(repo_url)
        
        if parsed.scheme not in ("https", "http"):
            return False
        if parsed.hostname not in ALLOWED_HOSTS:
            return False
        if not parsed.path or ".." in parsed.path:
            return False
        return True
    
    def extract_name(self, repo_url: str) -> str:
        """Extrahiert sicheren Repo-Namen. Verhindert Path Traversal."""
        from urllib.parse import urlparse
        parsed = urlparse(repo_url)
        
        # Letztes Pfad-Segment, .git entfernen
        name = parsed.path.rstrip("/").split("/")[-1]
        name = name.removesuffix(".git")
        
        # Nur erlaubte Zeichen
        if not REPO_NAME_PATTERN.match(name):
            raise ValueError(f"Ungültiger Repo-Name: {name}")
        
        return name
    
    def clone(self, repo_url: str) -> tuple[Path, str]:
        """Klont Repo nach /opt/agency/repos/<name>/. Returns (path, error)."""
        if not self.validate_url(repo_url):
            return None, "Ungültige URL. Erlaubt: github.com, gitlab.com, bitbucket.org"
        
        try:
            name = self.extract_name(repo_url)
        except ValueError as e:
            return None, str(e)
        
        target = self.REPOS_DIR / name
        
        # Check ob bereits registriert
        # (wird vom Caller geprüft via DB-Lookup)
        
        try:
            if target.exists():
                result = subprocess.run(
                    ["git", "-C", str(target), "pull"],
                    capture_output=True, text=True, timeout=300
                )
            else:
                result = subprocess.run(
                    ["git", "clone", repo_url, str(target)],
                    capture_output=True, text=True, timeout=300
                )
            
            if result.returncode != 0:
                return None, f"Git-Fehler: {result.stderr[:200]}"
            
            return target, None
            
        except subprocess.TimeoutExpired:
            return None, "Clone-Timeout (5 min). Repo zu groß?"
        except Exception as e:
            return None, f"Clone-Fehler: {str(e)[:200]}"
    
    def check_existing_agents(self, repo_path: Path) -> bool:
        """Prüft ob .claude/agents/ bereits existiert."""
        agents_dir = repo_path / ".claude" / "agents"
        return agents_dir.exists() and any(agents_dir.iterdir())
    
    def register(self, name: str, path: Path, stack: str, repo_url: str, db):
        """Registriert Repo in DB."""
        db.execute(
            """
            INSERT INTO agency_repos (name, path, stack, repo_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                path = EXCLUDED.path,
                stack = EXCLUDED.stack,
                repo_url = EXCLUDED.repo_url
            """,
            (name, str(path), stack, repo_url)
        )
    
    def write_agents(self, repo_path: Path, agents: list[dict]):
        """Schreibt generierte Agents nach .claude/agents/"""
        agents_dir = repo_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        
        for agent in agents:
            (agents_dir / agent["filename"]).write_text(agent["content"])
    
    def cleanup_partial(self, repo_path: Path):
        """Cleanup bei Fehler nach Clone."""
        import shutil
        if repo_path and repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)
```

**DB-Tabelle `agency_repos`:**

```sql
CREATE TABLE agency_repos (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    path TEXT NOT NULL,
    stack VARCHAR(50) NOT NULL,
    repo_url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## API Endpoints

```python
# orchestrator/api.py

class ConfigureRequest(BaseModel):
    repo_url: str

class AnswerRequest(BaseModel):
    answer: str

@app.post("/api/configure")
def start_configure(request: ConfigureRequest, _: bool = Depends(verify_secret)):
    """Startet Konfiguration, gibt session_id zurück."""
    # Returns: {"session_id": "...", "state": "DETECTING", "message": "..."}

@app.post("/api/configure/{session_id}/answer")
def answer_question(session_id: str, answer: AnswerRequest, _: bool = Depends(verify_secret)):
    """Beantwortet Rückfrage."""
    # Returns: {"state": "...", "next_question": "..." oder "preview": "..."}

@app.post("/api/configure/{session_id}/confirm")
def confirm_configure(session_id: str, overwrite: bool = False, _: bool = Depends(verify_secret)):
    """Bestätigt und führt Konfiguration aus."""
    # overwrite=True wenn existierende Agents überschrieben werden sollen
    # Returns: {"state": "COMPLETE", "repo_name": "...", "agents_count": 9}

@app.post("/api/configure/{session_id}/cancel")
def cancel_configure(session_id: str, _: bool = Depends(verify_secret)):
    """Bricht Konfiguration ab."""
    # Returns: {"state": "CANCELLED"}

@app.get("/api/repos")
def list_repos(_: bool = Depends(verify_secret)):
    """Listet registrierte Repos."""
```

## Slack/Telegram Integration

**Neue Commands:**
- `/configure <repo-url>` — Startet Konfiguration
- `/cancel` — Bricht aktive Konfiguration ab
- `/help configure` — Hilfe zum Agent Designer

```python
# slack_bot.py / telegram_bot.py

def handle_configure_command(repo_url: str, channel: str, user_id: str):
    # Rate-Limit Check
    active_count = get_active_session_count(user_id)
    if active_count >= 3:
        send_message(channel, "Du hast bereits 3 aktive Konfigurationen. /cancel zum Abbrechen.")
        return
    
    session = agent_designer.start(repo_url, channel, user_id)
    
    if session.state == "ERROR":
        send_message(channel, f"❌ {session.error}")
        return
    
    if session.state == "ASKING_COMMANDS":
        send_message(
            channel,
            f"*{session.stack}* erkannt!\n\n"
            f"Welcher Test-Command? Ich sehe:\n"
            f"• `{session.detected_commands.get('test', 'nicht erkannt')}`\n\n"
            f"Antworte mit dem gewünschten Command oder 'skip'."
        )

def handle_cancel_command(channel: str, user_id: str):
    cancelled = agent_designer.cancel_active_session(user_id, channel)
    if cancelled:
        send_message(channel, "✅ Konfiguration abgebrochen.")
    else:
        send_message(channel, "Keine aktive Konfiguration gefunden.")

def handle_help_configure(channel: str):
    send_message(channel, """*Agent Designer Hilfe*

`/configure <repo-url>` — Pipeline für neues Repo einrichten
`/cancel` — Aktive Konfiguration abbrechen

*Unterstützte Stacks:*
• FastAPI (Python)
• React + Vite
• Shopify App
• Shopware Plugin

*Ablauf:*
1. Repo-URL eingeben
2. Stack wird erkannt
3. Commands bestätigen (test/build/lint)
4. Agents werden generiert
5. Repo ist bereit für Tasks!
""")
```

**Antwort-Handling:** Messages werden gegen `(chat_id, user_id)` gematcht — verhindert Session-Hijacking in Team-Channels.

## CLI

```bash
mutirada configure https://github.com/user/repo

# Output:
# Shopify App erkannt (React Router 7 + Prisma + Polaris)
# 
# Test-Command? [npm test]: 
# Build-Command? [npm run build]: 
# 
# Preview:
# ├── concept_clarifier.md (Test: npm test, Build: npm run build)
# ├── implementer.md
# └── ... (9 files)
# 
# ⚠️  .claude/agents/ existiert bereits. Überschreiben? [y/N]: 
# 
# ✅ Repo geklont nach /opt/agency/repos/falara-shopify
# ✅ 9 Agent-Profile generiert
# ✅ Repo registriert - du kannst jetzt Tasks schicken!
```

## Output-Optionen

Nach Bestätigung:

1. **Lokal schreiben** (Default für geklonte Repos):
   - Schreibt direkt nach `.claude/agents/`
   - User committed selbst

2. **PR erstellen** (wenn GitHub-Token vorhanden):
   - Branch `mutirada/setup-agents`
   - Commit mit 9 Agent-Dateien
   - PR erstellen mit Beschreibung

3. **ZIP-Download** (Fallback):
   - Generiert ZIP mit allen Agent-Dateien
   - Link zum Download

## Existing Agents Check

Vor dem Schreiben:

```python
if repo_manager.check_existing_agents(repo_path):
    # In Chat: Frage User
    session.state = "ASKING_OVERWRITE"
    send_message(channel, 
        "⚠️ `.claude/agents/` existiert bereits. Überschreiben?\n"
        "Antworte 'ja' oder 'nein'."
    )
    return
```

Nur bei explizitem "ja" überschreiben. Bei "nein" → CANCELLED.

## Error Recovery

Bei Fehler nach CLONING:

```python
def handle_error(session, error: str, repo_path: Path = None):
    session.state = "ERROR"
    session.data["error"] = error
    session.data["retry_available"] = True
    save_session(session)
    
    # Cleanup partieller Clone
    if repo_path:
        repo_manager.cleanup_partial(repo_path)
    
    send_message(session.chat_id,
        f"❌ Fehler: {error}\n\n"
        f"Antworte 'retry' zum erneuten Versuch oder /cancel zum Abbrechen."
    )
```

## Orchestrator-Anpassungen

`main.py` muss Repos aus DB lesen statt hardcoded:

```python
def _get_repo_dir(self, task_id: int) -> Path:
    task = self.task_queue.get_task(task_id)
    repo_name = task.data.get("repo")
    
    # Lookup in agency_repos
    repo = self.db.execute(
        "SELECT path FROM agency_repos WHERE name = %s",
        (repo_name,)
    ).fetchone()
    
    if repo:
        return Path(repo["path"])
    
    # Fallback für alte Tasks
    if repo_name == "frontend":
        return Path("/opt/agency/repos/falara-frontend")
    return Path("/opt/agency/repos/falara")
```

## Stack-Templates Phase 1

### Shopify App (React Router 7 + Prisma + Polaris)

**Erkennungs-Signale:**
- `shopify.app.toml`
- `@shopify/shopify-app-remix` in package.json

**Commands:**
- Test: `npm test` oder `npm run test`
- Build: `npm run build`
- Dev: `npm run dev`
- Prisma: `npx prisma migrate dev`

**Patterns im Implementer:**
- Polaris-Komponenten (`<Page>`, `<Card>`, `<DataTable>`)
- App Bridge für Shopify-Admin-Kontext
- Remix loader/action Pattern

### Shopware Plugin (PHP + Guzzle + Vue)

**Erkennungs-Signale:**
- `composer.json` mit `shopware/core`
- `src/Resources/app/administration/` (Vue Admin-UI)

**Commands:**
- Test: `./vendor/bin/phpunit`
- Lint: `./vendor/bin/phpstan analyse`
- Build Admin: `npm --prefix src/Resources/app/administration run build`

**Patterns im Implementer:**
- Shopware Services + DI
- Entity Definitions
- Admin-UI mit Vue + Meteor Components

## Error Handling

| Fehler | Handling |
|--------|----------|
| URL ungültig | "Ungültige URL. Erlaubt: github.com, gitlab.com, bitbucket.org" |
| Repo nicht erreichbar | "Git-Fehler: {stderr}" mit Details |
| Stack nicht erkannt | "Stack nicht erkannt. Unterstützt: FastAPI, React, Shopify, Shopware" |
| Clone-Timeout | "Clone-Timeout (5 min). Repo zu groß?" |
| Session abgelaufen | Sessions nach 30min löschen, "Session abgelaufen. Starte neu mit /configure" |
| Rate-Limit | "Du hast bereits 3 aktive Konfigurationen. /cancel zum Abbrechen." |

## Testing

```python
# tests/test_agent_designer.py

def test_detect_shopify_app():
    result = detector.detect("/path/to/shopify-repo")
    assert result.stack == "shopify-app"
    assert "shopify.app.toml" in result.detected_files

def test_detect_priority_shopify_over_react():
    """Shopify-App enthält auch package.json — muss als Shopify erkannt werden."""
    result = detector.detect("/path/to/shopify-with-react")
    assert result.stack == "shopify-app"  # Nicht "react-vite"

def test_validate_url_rejects_malicious():
    rm = RepoManager()
    assert rm.validate_url("https://github.com/user/repo") == True
    assert rm.validate_url("https://evil.com/repo") == False
    assert rm.validate_url("file:///etc/passwd") == False
    assert rm.validate_url("https://github.com/--upload-pack=x") == False

def test_extract_name_prevents_traversal():
    rm = RepoManager()
    assert rm.extract_name("https://github.com/user/my-repo") == "my-repo"
    assert rm.extract_name("https://github.com/user/repo.git") == "repo"
    with pytest.raises(ValueError):
        rm.extract_name("https://github.com/user/../etc")

def test_session_requires_user_id():
    """Sessions müssen user_id haben für Multi-User Channels."""
    session = conversation.start("https://github.com/test/repo", "channel123", "user456")
    assert session.user_id == "user456"
    
    # Antwort von anderem User wird ignoriert
    result = conversation.handle_answer("channel123", "user789", "npm test")
    assert result is None  # Keine Session für diesen User

def test_cancel_command():
    session = conversation.start("https://github.com/test/repo", "channel123", "user456")
    assert session.state == "DETECTING"
    
    conversation.cancel("channel123", "user456")
    session = conversation.get_session("channel123", "user456")
    assert session.state == "CANCELLED"

def test_existing_agents_warning():
    # Setup: Repo mit existierenden Agents
    result = conversation.confirm(session_id, overwrite=False)
    assert result.state == "ASKING_OVERWRITE"
    
    result = conversation.confirm(session_id, overwrite=True)
    assert result.state == "COMPLETE"

def test_generate_agents():
    agents = generator.generate("shopify-app", {
        "test_command": "npm test",
        "build_command": "npm run build",
    })
    assert len(agents) == 9
    assert "implementer.md" in [a["filename"] for a in agents]

def test_full_flow():
    session = conversation.start("https://github.com/test/repo", "ch", "user")
    session = conversation.answer(session.id, "npm test")
    session = conversation.confirm(session.id)
    assert session.state == "COMPLETE"
```

## Migrations

```sql
-- migrations/003_agent_designer.sql

CREATE TABLE agency_repos (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    path TEXT NOT NULL,
    stack VARCHAR(50) NOT NULL,
    repo_url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE agent_designer_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) UNIQUE NOT NULL,
    chat_id VARCHAR(50),
    user_id VARCHAR(50),
    source VARCHAR(20),
    repo_url TEXT NOT NULL,
    stack VARCHAR(50),
    state VARCHAR(20) NOT NULL,
    data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sessions_active ON agent_designer_sessions (chat_id, user_id, state)
    WHERE state NOT IN ('COMPLETE', 'ERROR', 'CANCELLED');

CREATE INDEX idx_sessions_user ON agent_designer_sessions (user_id, state)
    WHERE state NOT IN ('COMPLETE', 'ERROR', 'CANCELLED');

-- Seed existing repos
INSERT INTO agency_repos (name, path, stack, repo_url) VALUES
('falara', '/opt/agency/repos/falara', 'fastapi', 'https://github.com/borisdeluxe/falara'),
('falara-frontend', '/opt/agency/repos/falara-frontend', 'react-vite', 'https://github.com/borisdeluxe/falara-frontend');
```

## Deliverables

1. `orchestrator/agent_designer/` — Kern-Module (detector, generator, repo_manager, conversation)
2. `templates/` — 4 Stack-Templates × 9 Agents = 36 Dateien
3. API-Endpoints in `api.py`
4. Slack/Telegram Commands (`/configure`, `/cancel`, `/help configure`)
5. CLI-Wrapper
6. DB-Migration
7. Tests
