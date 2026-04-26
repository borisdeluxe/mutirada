# Agent Designer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatische Pipeline-Konfiguration für neue Repos mit Stack-Erkennung, Rückfragen und Agent-Generierung.

**Architecture:** Modul im Orchestrator mit 4 Kern-Komponenten (detector, generator, repo_manager, conversation). Templates als Jinja2-Dateien. Session-State in PostgreSQL.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, PostgreSQL, httpx

---

## File Structure

```
orchestrator/
├── orchestrator/
│   ├── agent_designer/
│   │   ├── __init__.py           # Exports
│   │   ├── detector.py           # Stack detection (150 LOC)
│   │   ├── generator.py          # Template rendering (100 LOC)
│   │   ├── repo_manager.py       # Clone/register (120 LOC)
│   │   └── conversation.py       # Session state machine (200 LOC)
│   ├── api.py                    # +4 endpoints (~50 LOC)
│   ├── slack_bot.py              # +3 commands (~60 LOC)
│   └── telegram_bot.py           # +3 commands (~60 LOC)
├── templates/
│   ├── base/_header.md
│   ├── fastapi/*.md              # 9 agents
│   ├── react-vite/*.md           # 9 agents
│   ├── shopify-app/*.md          # 9 agents
│   └── shopware-plugin/*.md      # 9 agents
├── migrations/
│   └── 003_agent_designer.sql
└── tests/
    └── test_agent_designer.py
```

---

### Task 1: Database Migration

**Files:**
- Create: `orchestrator/migrations/003_agent_designer.sql`

- [ ] **Step 1: Write migration file**

```sql
-- migrations/003_agent_designer.sql

CREATE TABLE IF NOT EXISTS agency_repos (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    path TEXT NOT NULL,
    stack VARCHAR(50) NOT NULL,
    repo_url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_designer_sessions (
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

CREATE INDEX IF NOT EXISTS idx_sessions_active 
ON agent_designer_sessions (chat_id, user_id, state)
WHERE state NOT IN ('COMPLETE', 'ERROR', 'CANCELLED');

CREATE INDEX IF NOT EXISTS idx_sessions_user 
ON agent_designer_sessions (user_id, state)
WHERE state NOT IN ('COMPLETE', 'ERROR', 'CANCELLED');

-- Seed existing repos
INSERT INTO agency_repos (name, path, stack, repo_url) VALUES
('falara', '/opt/agency/repos/falara', 'fastapi', 'https://github.com/borisdeluxe/falara'),
('falara-frontend', '/opt/agency/repos/falara-frontend', 'react-vite', 'https://github.com/borisdeluxe/falara-frontend')
ON CONFLICT (name) DO NOTHING;
```

- [ ] **Step 2: Run migration on server**

```bash
ssh root@46.225.19.209 "psql -U agency -d agency_db -f /opt/agency/orchestrator/migrations/003_agent_designer.sql"
```

Expected: Tables created, 2 rows inserted into agency_repos.

- [ ] **Step 3: Commit**

```bash
git add migrations/003_agent_designer.sql
git commit -m "feat(agent-designer): add database migration for repos and sessions"
```

---

### Task 2: Repo Manager Module

**Files:**
- Create: `orchestrator/orchestrator/agent_designer/__init__.py`
- Create: `orchestrator/orchestrator/agent_designer/repo_manager.py`
- Test: `orchestrator/tests/test_repo_manager.py`

- [ ] **Step 1: Create package init**

```python
# orchestrator/orchestrator/agent_designer/__init__.py
"""Agent Designer - automatic pipeline configuration for new repos."""

from .repo_manager import RepoManager
from .detector import StackDetector, StackDetectionResult
from .generator import AgentGenerator
from .conversation import ConversationManager, SessionState

__all__ = [
    "RepoManager",
    "StackDetector", 
    "StackDetectionResult",
    "AgentGenerator",
    "ConversationManager",
    "SessionState",
]
```

- [ ] **Step 2: Write failing test for URL validation**

```python
# orchestrator/tests/test_repo_manager.py
import pytest
from orchestrator.agent_designer.repo_manager import RepoManager

def test_validate_url_accepts_github():
    rm = RepoManager()
    assert rm.validate_url("https://github.com/user/repo") is True
    assert rm.validate_url("https://github.com/user/repo.git") is True

def test_validate_url_accepts_gitlab():
    rm = RepoManager()
    assert rm.validate_url("https://gitlab.com/user/repo") is True

def test_validate_url_rejects_unknown_hosts():
    rm = RepoManager()
    assert rm.validate_url("https://evil.com/repo") is False
    assert rm.validate_url("https://github.evil.com/repo") is False

def test_validate_url_rejects_non_https():
    rm = RepoManager()
    assert rm.validate_url("file:///etc/passwd") is False
    assert rm.validate_url("git://github.com/user/repo") is False

def test_validate_url_rejects_path_traversal():
    rm = RepoManager()
    assert rm.validate_url("https://github.com/user/../etc") is False
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_repo_manager.py -v
```

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 4: Write RepoManager implementation**

```python
# orchestrator/orchestrator/agent_designer/repo_manager.py
"""Repository cloning and registration."""

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

ALLOWED_HOSTS = ["github.com", "gitlab.com", "bitbucket.org"]
REPO_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')


@dataclass
class CloneResult:
    success: bool
    path: Optional[Path] = None
    error: Optional[str] = None


class RepoManager:
    """Manages repository cloning and registration."""
    
    def __init__(self, repos_dir: Path = None):
        self.repos_dir = repos_dir or Path("/opt/agency/repos")
    
    def validate_url(self, repo_url: str) -> bool:
        """Validate URL against whitelist. Prevents command injection."""
        try:
            parsed = urlparse(repo_url)
        except Exception:
            return False
        
        if parsed.scheme not in ("https", "http"):
            return False
        
        if parsed.hostname not in ALLOWED_HOSTS:
            return False
        
        if not parsed.path or ".." in parsed.path:
            return False
        
        return True
    
    def extract_name(self, repo_url: str) -> str:
        """Extract safe repo name. Prevents path traversal."""
        parsed = urlparse(repo_url)
        
        # Last path segment, remove .git
        path = parsed.path.rstrip("/")
        name = path.split("/")[-1]
        name = name.removesuffix(".git")
        
        # Only allowed characters
        if not name or not REPO_NAME_PATTERN.match(name):
            raise ValueError(f"Invalid repo name: {name}")
        
        return name
    
    def clone(self, repo_url: str) -> CloneResult:
        """Clone repo to repos_dir. Returns CloneResult."""
        if not self.validate_url(repo_url):
            return CloneResult(
                success=False,
                error="Invalid URL. Allowed: github.com, gitlab.com, bitbucket.org"
            )
        
        try:
            name = self.extract_name(repo_url)
        except ValueError as e:
            return CloneResult(success=False, error=str(e))
        
        target = self.repos_dir / name
        
        try:
            if target.exists():
                result = subprocess.run(
                    ["git", "-C", str(target), "pull"],
                    capture_output=True, text=True, timeout=300
                )
            else:
                self.repos_dir.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    ["git", "clone", repo_url, str(target)],
                    capture_output=True, text=True, timeout=300
                )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip()[:200] if result.stderr else "Unknown git error"
                return CloneResult(success=False, error=f"Git error: {error_msg}")
            
            return CloneResult(success=True, path=target)
            
        except subprocess.TimeoutExpired:
            return CloneResult(success=False, error="Clone timeout (5 min). Repo too large?")
        except Exception as e:
            return CloneResult(success=False, error=f"Clone error: {str(e)[:200]}")
    
    def check_existing_agents(self, repo_path: Path) -> bool:
        """Check if .claude/agents/ already exists with content."""
        agents_dir = repo_path / ".claude" / "agents"
        return agents_dir.exists() and any(agents_dir.iterdir())
    
    def write_agents(self, repo_path: Path, agents: list) -> None:
        """Write generated agents to .claude/agents/"""
        agents_dir = repo_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        
        for agent in agents:
            filepath = agents_dir / agent["filename"]
            filepath.write_text(agent["content"])
    
    def cleanup_partial(self, repo_path: Path) -> None:
        """Cleanup partial clone on error."""
        if repo_path and repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_repo_manager.py -v
```

Expected: All tests PASS

- [ ] **Step 6: Add tests for extract_name**

```python
# Add to tests/test_repo_manager.py

def test_extract_name_simple():
    rm = RepoManager()
    assert rm.extract_name("https://github.com/user/my-repo") == "my-repo"
    assert rm.extract_name("https://github.com/user/repo.git") == "repo"

def test_extract_name_with_trailing_slash():
    rm = RepoManager()
    assert rm.extract_name("https://github.com/user/repo/") == "repo"

def test_extract_name_rejects_traversal():
    rm = RepoManager()
    with pytest.raises(ValueError):
        rm.extract_name("https://github.com/user/..%2fetc")

def test_extract_name_rejects_empty():
    rm = RepoManager()
    with pytest.raises(ValueError):
        rm.extract_name("https://github.com/")
```

- [ ] **Step 7: Run all repo_manager tests**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_repo_manager.py -v
```

Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add orchestrator/agent_designer/ tests/test_repo_manager.py
git commit -m "feat(agent-designer): add RepoManager with URL validation and path safety"
```

---

### Task 3: Stack Detector Module

**Files:**
- Create: `orchestrator/orchestrator/agent_designer/detector.py`
- Test: `orchestrator/tests/test_detector.py`

- [ ] **Step 1: Write failing test for stack detection**

```python
# orchestrator/tests/test_detector.py
import pytest
from pathlib import Path
from orchestrator.agent_designer.detector import StackDetector, StackDetectionResult

def test_detect_fastapi(tmp_path):
    # Setup: Create pyproject.toml with fastapi
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["fastapi"]\n')
    
    detector = StackDetector()
    result = detector.detect(tmp_path)
    
    assert result.stack == "fastapi"
    assert result.confidence > 0.5

def test_detect_shopify_app(tmp_path):
    # Setup: Create shopify.app.toml
    (tmp_path / "shopify.app.toml").write_text("[app]\nname = 'test'\n")
    (tmp_path / "package.json").write_text('{"dependencies": {"@shopify/polaris": "1.0"}}')
    
    detector = StackDetector()
    result = detector.detect(tmp_path)
    
    assert result.stack == "shopify-app"

def test_detect_priority_shopify_over_react(tmp_path):
    """Shopify app contains package.json with react - must detect as shopify."""
    (tmp_path / "shopify.app.toml").write_text("[app]\nname = 'test'\n")
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "18", "vite": "5"}}')
    (tmp_path / "vite.config.ts").write_text("export default {}")
    
    detector = StackDetector()
    result = detector.detect(tmp_path)
    
    assert result.stack == "shopify-app"  # NOT react-vite

def test_detect_unknown_stack(tmp_path):
    # Empty directory
    detector = StackDetector()
    result = detector.detect(tmp_path)
    
    assert result.stack is None
    assert result.confidence == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_detector.py -v
```

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write StackDetector implementation**

```python
# orchestrator/orchestrator/agent_designer/detector.py
"""Stack detection for repositories."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Explicit priority order - specific before generic
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
        "description": "Shopify App (React Router + Prisma + Polaris)",
    },
    "shopware-plugin": {
        "required": ["composer.json"],
        "composer_markers": ["shopware/core"],
        "optional_dirs": ["src/Resources/app/administration"],
        "description": "Shopware Plugin (PHP + Guzzle + Vue)",
    },
    "react-vite": {
        "required": ["package.json"],
        "optional": ["vite.config.ts", "vite.config.js"],
        "package_markers": ["react", "vite"],
        "description": "React + Vite + TypeScript",
    },
    "fastapi": {
        "required": ["pyproject.toml"],
        "pyproject_markers": ["fastapi"],
        "description": "FastAPI + Python",
    },
}

DEFAULT_COMMANDS = {
    "shopify-app": {
        "test": "npm test",
        "build": "npm run build",
        "lint": "npm run lint",
    },
    "shopware-plugin": {
        "test": "./vendor/bin/phpunit",
        "build": "npm --prefix src/Resources/app/administration run build",
        "lint": "./vendor/bin/phpstan analyse",
    },
    "react-vite": {
        "test": "npm test",
        "build": "npm run build",
        "lint": "npm run lint",
    },
    "fastapi": {
        "test": "pytest",
        "build": "echo 'No build step'",
        "lint": "ruff check .",
    },
}


@dataclass
class StackDetectionResult:
    stack: Optional[str] = None
    confidence: float = 0.0
    detected_files: list = field(default_factory=list)
    suggested_commands: dict = field(default_factory=dict)
    description: str = ""
    questions: list = field(default_factory=list)


class StackDetector:
    """Detects project stack from repository files."""
    
    def detect(self, repo_path: Path) -> StackDetectionResult:
        """Detect stack type from repository."""
        for stack_name in DETECTION_PRIORITY:
            signature = STACK_SIGNATURES[stack_name]
            result = self._check_stack(repo_path, stack_name, signature)
            if result.stack:
                return result
        
        return StackDetectionResult(
            stack=None,
            confidence=0.0,
            questions=["Stack nicht erkannt. Unterstützt: FastAPI, React, Shopify, Shopware"]
        )
    
    def _check_stack(self, repo_path: Path, stack_name: str, signature: dict) -> StackDetectionResult:
        """Check if repo matches a specific stack signature."""
        detected_files = []
        confidence = 0.0
        
        # Check required files
        for required in signature.get("required", []):
            if (repo_path / required).exists():
                detected_files.append(required)
                confidence += 0.3
            else:
                return StackDetectionResult()  # Missing required file
        
        # Check optional files
        for optional in signature.get("optional", []):
            if (repo_path / optional).exists():
                detected_files.append(optional)
                confidence += 0.1
        
        # Check optional directories
        for optional_dir in signature.get("optional_dirs", []):
            if (repo_path / optional_dir).is_dir():
                detected_files.append(optional_dir)
                confidence += 0.1
        
        # Check package.json markers
        if "package_markers" in signature:
            package_json = repo_path / "package.json"
            if package_json.exists():
                try:
                    data = json.loads(package_json.read_text())
                    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                    for marker in signature["package_markers"]:
                        if marker in deps:
                            confidence += 0.2
                except (json.JSONDecodeError, IOError):
                    pass
        
        # Check composer.json markers
        if "composer_markers" in signature:
            composer_json = repo_path / "composer.json"
            if composer_json.exists():
                try:
                    data = json.loads(composer_json.read_text())
                    deps = {**data.get("require", {}), **data.get("require-dev", {})}
                    for marker in signature["composer_markers"]:
                        if marker in deps:
                            confidence += 0.3
                except (json.JSONDecodeError, IOError):
                    pass
        
        # Check pyproject.toml markers
        if "pyproject_markers" in signature:
            pyproject = repo_path / "pyproject.toml"
            if pyproject.exists():
                content = pyproject.read_text().lower()
                for marker in signature["pyproject_markers"]:
                    if marker.lower() in content:
                        confidence += 0.3
        
        if confidence > 0:
            suggested = self._detect_commands(repo_path, stack_name)
            return StackDetectionResult(
                stack=stack_name,
                confidence=min(confidence, 1.0),
                detected_files=detected_files,
                suggested_commands=suggested,
                description=signature.get("description", stack_name),
            )
        
        return StackDetectionResult()
    
    def _detect_commands(self, repo_path: Path, stack_name: str) -> dict:
        """Try to detect actual commands from project files."""
        defaults = DEFAULT_COMMANDS.get(stack_name, {}).copy()
        
        # Try to read package.json scripts
        package_json = repo_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                scripts = data.get("scripts", {})
                if "test" in scripts:
                    defaults["test"] = "npm test"
                if "build" in scripts:
                    defaults["build"] = "npm run build"
                if "lint" in scripts:
                    defaults["lint"] = "npm run lint"
            except (json.JSONDecodeError, IOError):
                pass
        
        return defaults
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_detector.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/agent_designer/detector.py tests/test_detector.py
git commit -m "feat(agent-designer): add StackDetector with priority-based detection"
```

---

### Task 4: Agent Generator Module

**Files:**
- Create: `orchestrator/orchestrator/agent_designer/generator.py`
- Create: `orchestrator/templates/base/_header.md`
- Create: `orchestrator/templates/fastapi/` (9 agents)
- Test: `orchestrator/tests/test_generator.py`

- [ ] **Step 1: Write failing test**

```python
# orchestrator/tests/test_generator.py
import pytest
from pathlib import Path
from orchestrator.agent_designer.generator import AgentGenerator

def test_generate_returns_nine_agents():
    gen = AgentGenerator()
    agents = gen.generate("fastapi", {
        "test_command": "pytest",
        "build_command": "echo done",
        "lint_command": "ruff check .",
    })
    
    assert len(agents) == 9
    filenames = [a["filename"] for a in agents]
    assert "concept_clarifier.md" in filenames
    assert "implementer.md" in filenames
    assert "deploy_runner.md" in filenames

def test_generate_includes_commands():
    gen = AgentGenerator()
    agents = gen.generate("fastapi", {
        "test_command": "pytest -v",
        "build_command": "make build",
        "lint_command": "ruff check .",
    })
    
    implementer = next(a for a in agents if a["filename"] == "implementer.md")
    assert "pytest -v" in implementer["content"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_generator.py -v
```

Expected: FAIL

- [ ] **Step 3: Create base template header**

```markdown
# orchestrator/templates/base/_header.md

Die LETZTE Zeile deiner Ausgabe MUSS exakt so aussehen:

```
STATUS: READY_FOR_<NEXT_AGENT>
```

NICHT: `STATUS: ...` (mit Backticks)
NICHT: ### STATUS: ... (mit Markdown)
NICHT: Status: ... (kleingeschrieben)

NUR: STATUS: gefolgt vom Statuswert, auf einer eigenen Zeile.
```

- [ ] **Step 4: Create FastAPI templates (9 files)**

```markdown
# orchestrator/templates/fastapi/concept_clarifier.md
---
name: concept_clarifier
description: Erster Pipeline-Agent - klärt Anforderungen und prüft bestehenden Code
tools: Read, Bash
---

## KRITISCH: STATUS-Zeile (PFLICHT)

{{ header }}

---

Du bist der erste Agent in der Pipeline. Deine Aufgabe ist es, Anforderungen zu klären und bestehenden Code zu prüfen.

## Stack

- FastAPI + Python
- pytest für Tests

## Commands

```bash
{{ test_command }}      # Tests ausführen
{{ lint_command }}      # Linting
```

## Aufgabe

1. **Suche nach bestehendem Code** für das Feature
2. **Bei Overlap**: EXTEND, REFACTOR, REWRITE, oder CANCEL empfehlen
3. **Output**: tk-draft.md schreiben

## Output Format

- `STATUS: READY_FOR_ARCHITECT_PLANNER` - wenn fertig
- `STATUS: BLOCKED_<GRUND>` - bei Problemen
```

(Repeat for all 9 agents: architect_planner, test_designer, implementer, security_reviewer, refactorer, qa_validator, docs_updater, deploy_runner)

- [ ] **Step 5: Write AgentGenerator**

```python
# orchestrator/orchestrator/agent_designer/generator.py
"""Agent template generation."""

from pathlib import Path
from typing import Optional

AGENT_SEQUENCE = [
    ("concept_clarifier", "ARCHITECT_PLANNER"),
    ("architect_planner", "TEST_DESIGNER"),
    ("test_designer", "IMPLEMENTER"),
    ("implementer", "SECURITY_REVIEWER"),
    ("security_reviewer", "REFACTORER"),
    ("refactorer", "QA_VALIDATOR"),
    ("qa_validator", "DOCS_UPDATER"),
    ("docs_updater", "DEPLOY_RUNNER"),
    ("deploy_runner", None),
]

AGENT_TOOLS = {
    "concept_clarifier": "Read, Bash",
    "architect_planner": "Read, Bash",
    "test_designer": "Read, Write, Bash",
    "implementer": "Read, Write, Edit, Bash",
    "security_reviewer": "Read, Bash",
    "refactorer": "Read, Write, Edit, Bash",
    "qa_validator": "Read, Bash",
    "docs_updater": "Read, Write, Edit, Bash",
    "deploy_runner": "Read, Bash",
}

AGENT_DESCRIPTIONS = {
    "concept_clarifier": "Erster Pipeline-Agent - klärt Anforderungen",
    "architect_planner": "Plant Architektur und Komponenten",
    "test_designer": "Schreibt Test-Spezifikationen",
    "implementer": "Implementiert bis Tests grün sind",
    "security_reviewer": "Prüft Sicherheit und OWASP",
    "refactorer": "Refactoring und Code-Qualität",
    "qa_validator": "End-to-End Validierung",
    "docs_updater": "Dokumentation aktualisieren",
    "deploy_runner": "Deployment vorbereiten",
}


class AgentGenerator:
    """Generates agent profiles from templates."""
    
    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates_dir = templates_dir or Path(__file__).parent.parent.parent / "templates"
    
    def generate(self, stack: str, commands: dict) -> list:
        """Generate all 9 agent profiles for a stack."""
        agents = []
        header = self._load_header()
        
        for agent_name, next_agent in AGENT_SEQUENCE:
            content = self._generate_agent(
                stack=stack,
                agent_name=agent_name,
                next_agent=next_agent,
                commands=commands,
                header=header,
            )
            agents.append({
                "filename": f"{agent_name}.md",
                "content": content,
            })
        
        return agents
    
    def _load_header(self) -> str:
        """Load the shared header template."""
        header_path = self.templates_dir / "base" / "_header.md"
        if header_path.exists():
            return header_path.read_text()
        return "STATUS: READY_FOR_<NEXT_AGENT>"
    
    def _generate_agent(self, stack: str, agent_name: str, next_agent: Optional[str], 
                        commands: dict, header: str) -> str:
        """Generate a single agent profile."""
        tools = AGENT_TOOLS.get(agent_name, "Read, Bash")
        description = AGENT_DESCRIPTIONS.get(agent_name, agent_name)
        
        if next_agent:
            status_line = f"STATUS: READY_FOR_{next_agent}"
        else:
            status_line = "STATUS: READY_DEPLOY_COMPLETE"
        
        # Try to load stack-specific template
        template_path = self.templates_dir / stack / f"{agent_name}.md"
        if template_path.exists():
            content = template_path.read_text()
            # Simple placeholder replacement
            content = content.replace("{{ header }}", header)
            content = content.replace("{{ test_command }}", commands.get("test_command", ""))
            content = content.replace("{{ build_command }}", commands.get("build_command", ""))
            content = content.replace("{{ lint_command }}", commands.get("lint_command", ""))
            return content
        
        # Fallback: generate basic template
        return f"""---
name: {agent_name}
description: {description}
tools: {tools}
---

## KRITISCH: STATUS-Zeile (PFLICHT)

{header}

---

## Commands

```bash
{commands.get('test_command', '# No test command')}
{commands.get('build_command', '# No build command')}
{commands.get('lint_command', '# No lint command')}
```

## Output Format

- `{status_line}` - wenn fertig
- `STATUS: BLOCKED_<GRUND>` - bei Problemen
"""
```

- [ ] **Step 6: Run tests**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_generator.py -v
```

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add orchestrator/agent_designer/generator.py orchestrator/templates/ tests/test_generator.py
git commit -m "feat(agent-designer): add AgentGenerator with template system"
```

---

### Task 5: Conversation State Machine

**Files:**
- Create: `orchestrator/orchestrator/agent_designer/conversation.py`
- Test: `orchestrator/tests/test_conversation.py`

- [ ] **Step 1: Write failing test**

```python
# orchestrator/tests/test_conversation.py
import pytest
from orchestrator.agent_designer.conversation import ConversationManager, SessionState

def test_start_session_returns_session():
    cm = ConversationManager(db=None)  # Mock DB later
    session = cm.start("https://github.com/test/repo", "channel123", "user456", "slack")
    
    assert session is not None
    assert session.user_id == "user456"
    assert session.chat_id == "channel123"
    assert session.state in [SessionState.DETECTING, SessionState.ERROR]

def test_session_requires_user_id():
    cm = ConversationManager(db=None)
    
    # Different user cannot access session
    cm.start("https://github.com/test/repo", "channel123", "user456", "slack")
    session = cm.get_active_session("channel123", "user789")
    
    assert session is None  # No session for user789

def test_cancel_session():
    cm = ConversationManager(db=None)
    session = cm.start("https://github.com/test/repo", "channel123", "user456", "slack")
    
    result = cm.cancel("channel123", "user456")
    assert result is True
    
    session = cm.get_active_session("channel123", "user456")
    assert session is None or session.state == SessionState.CANCELLED
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_conversation.py -v
```

Expected: FAIL

- [ ] **Step 3: Write ConversationManager**

```python
# orchestrator/orchestrator/agent_designer/conversation.py
"""Conversation state machine for agent designer."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any

from .detector import StackDetector
from .generator import AgentGenerator
from .repo_manager import RepoManager


class SessionState(str, Enum):
    INIT = "INIT"
    DETECTING = "DETECTING"
    ASKING_COMMANDS = "ASKING_COMMANDS"
    ASKING_CONFIRM = "ASKING_CONFIRM"
    ASKING_OVERWRITE = "ASKING_OVERWRITE"
    CLONING = "CLONING"
    GENERATING = "GENERATING"
    REGISTERING = "REGISTERING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


@dataclass
class Session:
    session_id: str
    chat_id: str
    user_id: str
    source: str
    repo_url: str
    state: SessionState
    stack: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    @property
    def is_active(self) -> bool:
        return self.state not in (
            SessionState.COMPLETE, 
            SessionState.ERROR, 
            SessionState.CANCELLED
        )


class ConversationManager:
    """Manages conversation sessions for agent designer."""
    
    MAX_SESSIONS_PER_USER = 3
    SESSION_TIMEOUT_MINUTES = 30
    
    def __init__(self, db=None, repos_dir=None):
        self.db = db
        self.detector = StackDetector()
        self.generator = AgentGenerator()
        self.repo_manager = RepoManager(repos_dir)
        
        # In-memory sessions for testing (use DB in production)
        self._sessions: Dict[str, Session] = {}
    
    def start(self, repo_url: str, chat_id: str, user_id: str, source: str) -> Session:
        """Start a new configuration session."""
        # Check rate limit
        active_count = self._count_active_sessions(user_id)
        if active_count >= self.MAX_SESSIONS_PER_USER:
            return Session(
                session_id="",
                chat_id=chat_id,
                user_id=user_id,
                source=source,
                repo_url=repo_url,
                state=SessionState.ERROR,
                data={"error": f"Max {self.MAX_SESSIONS_PER_USER} active sessions. Use /cancel."}
            )
        
        # Validate URL
        if not self.repo_manager.validate_url(repo_url):
            return Session(
                session_id="",
                chat_id=chat_id,
                user_id=user_id,
                source=source,
                repo_url=repo_url,
                state=SessionState.ERROR,
                data={"error": "Invalid URL. Allowed: github.com, gitlab.com, bitbucket.org"}
            )
        
        session_id = str(uuid.uuid4())[:8]
        session = Session(
            session_id=session_id,
            chat_id=chat_id,
            user_id=user_id,
            source=source,
            repo_url=repo_url,
            state=SessionState.DETECTING,
        )
        
        self._sessions[session_id] = session
        self._save_session(session)
        
        return session
    
    def get_active_session(self, chat_id: str, user_id: str) -> Optional[Session]:
        """Get active session for user in channel."""
        for session in self._sessions.values():
            if (session.chat_id == chat_id and 
                session.user_id == user_id and 
                session.is_active):
                # Check timeout
                if datetime.now() - session.updated_at > timedelta(minutes=self.SESSION_TIMEOUT_MINUTES):
                    session.state = SessionState.ERROR
                    session.data["error"] = "Session expired. Start over with /configure."
                    self._save_session(session)
                    return None
                return session
        return None
    
    def cancel(self, chat_id: str, user_id: str) -> bool:
        """Cancel active session for user."""
        session = self.get_active_session(chat_id, user_id)
        if session:
            session.state = SessionState.CANCELLED
            session.updated_at = datetime.now()
            self._save_session(session)
            return True
        return False
    
    def handle_answer(self, chat_id: str, user_id: str, answer: str) -> Optional[Session]:
        """Handle user answer in conversation."""
        session = self.get_active_session(chat_id, user_id)
        if not session:
            return None
        
        session.updated_at = datetime.now()
        
        if session.state == SessionState.ASKING_COMMANDS:
            return self._handle_command_answer(session, answer)
        elif session.state == SessionState.ASKING_CONFIRM:
            return self._handle_confirm_answer(session, answer)
        elif session.state == SessionState.ASKING_OVERWRITE:
            return self._handle_overwrite_answer(session, answer)
        
        return session
    
    def _handle_command_answer(self, session: Session, answer: str) -> Session:
        """Handle answer for command questions."""
        current_question = session.data.get("current_question", "test")
        
        if answer.lower() != "skip":
            session.data[f"{current_question}_command"] = answer
        
        # Move to next question or confirm
        questions = ["test", "build", "lint"]
        current_idx = questions.index(current_question) if current_question in questions else 0
        
        if current_idx < len(questions) - 1:
            session.data["current_question"] = questions[current_idx + 1]
        else:
            session.state = SessionState.ASKING_CONFIRM
        
        self._save_session(session)
        return session
    
    def _handle_confirm_answer(self, session: Session, answer: str) -> Session:
        """Handle confirmation answer."""
        if answer.lower() in ("ja", "yes", "y", "ok"):
            return self._execute_configuration(session)
        else:
            session.state = SessionState.CANCELLED
            self._save_session(session)
        return session
    
    def _handle_overwrite_answer(self, session: Session, answer: str) -> Session:
        """Handle overwrite confirmation."""
        if answer.lower() in ("ja", "yes", "y"):
            session.data["overwrite"] = True
            return self._execute_configuration(session)
        else:
            session.state = SessionState.CANCELLED
            self._save_session(session)
        return session
    
    def _execute_configuration(self, session: Session) -> Session:
        """Execute the full configuration: clone, generate, register."""
        session.state = SessionState.CLONING
        self._save_session(session)
        
        # Clone
        result = self.repo_manager.clone(session.repo_url)
        if not result.success:
            session.state = SessionState.ERROR
            session.data["error"] = result.error
            self._save_session(session)
            return session
        
        repo_path = result.path
        
        # Check existing agents
        if self.repo_manager.check_existing_agents(repo_path) and not session.data.get("overwrite"):
            session.state = SessionState.ASKING_OVERWRITE
            self._save_session(session)
            return session
        
        # Generate
        session.state = SessionState.GENERATING
        self._save_session(session)
        
        commands = {
            "test_command": session.data.get("test_command", ""),
            "build_command": session.data.get("build_command", ""),
            "lint_command": session.data.get("lint_command", ""),
        }
        
        agents = self.generator.generate(session.stack, commands)
        self.repo_manager.write_agents(repo_path, agents)
        
        # Register
        session.state = SessionState.REGISTERING
        self._save_session(session)
        
        repo_name = self.repo_manager.extract_name(session.repo_url)
        # DB registration would happen here with self.db
        
        session.state = SessionState.COMPLETE
        session.data["repo_name"] = repo_name
        session.data["repo_path"] = str(repo_path)
        session.data["agents_count"] = len(agents)
        self._save_session(session)
        
        return session
    
    def _count_active_sessions(self, user_id: str) -> int:
        """Count active sessions for user."""
        return sum(1 for s in self._sessions.values() 
                   if s.user_id == user_id and s.is_active)
    
    def _save_session(self, session: Session) -> None:
        """Save session to DB."""
        self._sessions[session.session_id] = session
        
        if self.db:
            self.db.execute(
                """
                INSERT INTO agent_designer_sessions 
                    (session_id, chat_id, user_id, source, repo_url, stack, state, data, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    state = EXCLUDED.state,
                    data = EXCLUDED.data,
                    updated_at = NOW()
                """,
                (session.session_id, session.chat_id, session.user_id, 
                 session.source, session.repo_url, session.stack, 
                 session.state.value, json.dumps(session.data))
            )
```

- [ ] **Step 4: Run tests**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_conversation.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/agent_designer/conversation.py tests/test_conversation.py
git commit -m "feat(agent-designer): add ConversationManager with session state machine"
```

---

### Task 6: API Endpoints

**Files:**
- Modify: `orchestrator/orchestrator/api.py`
- Test: `orchestrator/tests/test_api_configure.py`

- [ ] **Step 1: Write failing test**

```python
# orchestrator/tests/test_api_configure.py
import pytest
from fastapi.testclient import TestClient
from orchestrator.api import app

client = TestClient(app)
API_SECRET = "dev-secret-change-me"

def test_configure_requires_auth():
    response = client.post("/api/configure", json={"repo_url": "https://github.com/test/repo"})
    assert response.status_code == 401

def test_configure_starts_session():
    response = client.post(
        "/api/configure",
        json={"repo_url": "https://github.com/test/repo"},
        headers={"X-Agency-Secret": API_SECRET}
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["state"] in ["DETECTING", "ERROR"]

def test_configure_rejects_invalid_url():
    response = client.post(
        "/api/configure",
        json={"repo_url": "https://evil.com/repo"},
        headers={"X-Agency-Secret": API_SECRET}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ERROR"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_api_configure.py -v
```

Expected: FAIL (endpoint doesn't exist)

- [ ] **Step 3: Add API endpoints to api.py**

```python
# Add to orchestrator/orchestrator/api.py

from .agent_designer import ConversationManager

# Initialize conversation manager
configure_manager = ConversationManager()


class ConfigureRequest(BaseModel):
    repo_url: str


class AnswerRequest(BaseModel):
    answer: str


@app.post("/api/configure")
def start_configure(request: ConfigureRequest, _: bool = Depends(verify_secret)):
    """Start repo configuration session."""
    session = configure_manager.start(
        repo_url=request.repo_url,
        chat_id="api",
        user_id="api",
        source="api"
    )
    
    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "stack": session.stack,
        "message": session.data.get("error") or "Configuration started",
    }


@app.post("/api/configure/{session_id}/answer")
def answer_configure(session_id: str, request: AnswerRequest, _: bool = Depends(verify_secret)):
    """Answer a configuration question."""
    session = configure_manager.handle_answer("api", "api", request.answer)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "data": session.data,
    }


@app.post("/api/configure/{session_id}/cancel")
def cancel_configure(session_id: str, _: bool = Depends(verify_secret)):
    """Cancel configuration session."""
    success = configure_manager.cancel("api", "api")
    
    if not success:
        raise HTTPException(status_code=404, detail="No active session")
    
    return {"state": "CANCELLED"}


@app.get("/api/repos")
def list_repos(_: bool = Depends(verify_secret)):
    """List registered repos."""
    with get_db() as conn:
        repos = conn.execute(
            "SELECT name, path, stack, repo_url, created_at FROM agency_repos ORDER BY created_at DESC"
        ).fetchall()
    
    return {
        "repos": [
            {
                "name": r["name"],
                "path": r["path"],
                "stack": r["stack"],
                "repo_url": r["repo_url"],
            }
            for r in repos
        ]
    }
```

- [ ] **Step 4: Run tests**

```bash
cd /home/boris/projects/mutirada/orchestrator && python -m pytest tests/test_api_configure.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/api.py tests/test_api_configure.py
git commit -m "feat(agent-designer): add /api/configure endpoints"
```

---

### Task 7: Slack Integration

**Files:**
- Modify: `orchestrator/orchestrator/slack_bot.py`

- [ ] **Step 1: Add /configure command handler**

```python
# Add to orchestrator/orchestrator/slack_bot.py

from .agent_designer import ConversationManager, SessionState

configure_manager = ConversationManager()


def handle_configure_command(repo_url: str, channel: str, user_id: str):
    """Handle /configure command."""
    session = configure_manager.start(repo_url, channel, user_id, "slack")
    
    if session.state == SessionState.ERROR:
        send_slack_message(channel, f"❌ {session.data.get('error')}")
        return
    
    if session.stack:
        suggested = session.data.get("suggested_commands", {})
        send_slack_message(
            channel,
            f"*{session.data.get('description', session.stack)}* erkannt!\n\n"
            f"Test-Command? Vorschlag: `{suggested.get('test', 'npm test')}`\n"
            f"Antworte mit dem Command oder 'skip'."
        )
    else:
        send_slack_message(channel, "Stack wird analysiert...")


def handle_cancel_command(channel: str, user_id: str):
    """Handle /cancel command."""
    success = configure_manager.cancel(channel, user_id)
    if success:
        send_slack_message(channel, "✅ Konfiguration abgebrochen.")
    else:
        send_slack_message(channel, "Keine aktive Konfiguration gefunden.")


def handle_help_configure(channel: str):
    """Handle /help configure."""
    send_slack_message(channel, """*Agent Designer Hilfe*

`/configure <repo-url>` — Pipeline für neues Repo einrichten
`/cancel` — Aktive Konfiguration abbrechen

*Unterstützte Stacks:*
• FastAPI (Python)
• React + Vite
• Shopify App
• Shopware Plugin
""")


# Update handle_message to check for configure session answers
def handle_message(event: dict):
    """Handle an incoming Slack message."""
    text = event.get("text", "")
    channel = event.get("channel", "")
    user_id = event.get("user", "")
    thread_ts = event.get("thread_ts") or event.get("ts")
    
    # Check for active configure session
    session = configure_manager.get_active_session(channel, user_id)
    if session and session.state in (SessionState.ASKING_COMMANDS, 
                                      SessionState.ASKING_CONFIRM,
                                      SessionState.ASKING_OVERWRITE):
        session = configure_manager.handle_answer(channel, user_id, text)
        _send_session_response(channel, session)
        return
    
    # ... rest of existing handle_message code ...


def _send_session_response(channel: str, session):
    """Send appropriate response based on session state."""
    if session.state == SessionState.ASKING_COMMANDS:
        q = session.data.get("current_question", "build")
        send_slack_message(channel, f"{q.title()}-Command?")
    
    elif session.state == SessionState.ASKING_CONFIRM:
        send_slack_message(
            channel,
            f"*Preview:*\n"
            f"• 9 Agent-Profile für {session.stack}\n"
            f"• Repo: {session.repo_url}\n\n"
            f"Generieren? (ja/nein)"
        )
    
    elif session.state == SessionState.ASKING_OVERWRITE:
        send_slack_message(
            channel,
            "⚠️ `.claude/agents/` existiert bereits. Überschreiben? (ja/nein)"
        )
    
    elif session.state == SessionState.COMPLETE:
        send_slack_message(
            channel,
            f"✅ *Konfiguration abgeschlossen!*\n\n"
            f"• Repo: `{session.data.get('repo_name')}`\n"
            f"• Agents: {session.data.get('agents_count')}\n"
            f"• Pfad: `{session.data.get('repo_path')}`\n\n"
            f"Du kannst jetzt Tasks schicken!"
        )
    
    elif session.state == SessionState.ERROR:
        send_slack_message(channel, f"❌ Fehler: {session.data.get('error')}")
```

- [ ] **Step 2: Update slack_events to handle commands**

```python
# Update slack_events in slack_bot.py

@router.post("/events")
async def slack_events(request: Request):
    # ... existing code ...
    
    # Handle slash commands (via separate endpoint or event)
    if event_type == "app_mention":
        text = event.get("text", "")
        
        # Check for /configure command
        if "/configure " in text or text.strip().startswith("configure "):
            match = re.search(r'configure\s+(https?://\S+)', text)
            if match:
                repo_url = match.group(1)
                handle_configure_command(repo_url, event["channel"], event["user"])
                return {"ok": True}
        
        # Check for /cancel
        if "/cancel" in text or "cancel" in text.lower():
            handle_cancel_command(event["channel"], event["user"])
            return {"ok": True}
        
        # Check for /help configure
        if "help configure" in text.lower():
            handle_help_configure(event["channel"])
            return {"ok": True}
        
        # ... rest of handle_message ...
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/slack_bot.py
git commit -m "feat(agent-designer): add /configure, /cancel, /help commands to Slack"
```

---

### Task 8: Telegram Integration

**Files:**
- Modify: `orchestrator/orchestrator/telegram_bot.py`

- [ ] **Step 1: Add configure commands to Telegram**

```python
# Add to orchestrator/orchestrator/telegram_bot.py

from .agent_designer import ConversationManager, SessionState

configure_manager = ConversationManager()


def handle_telegram_message(message: dict):
    """Handle incoming Telegram message."""
    text = message.get("text", "")
    chat_id = str(message.get("chat", {}).get("id", ""))
    user_id = str(message.get("from", {}).get("id", ""))
    
    if not text:
        return
    
    # Handle /commands
    if text.startswith("/"):
        cmd_parts = text.split(maxsplit=1)
        cmd = cmd_parts[0].lower().split("@")[0]
        arg = cmd_parts[1] if len(cmd_parts) > 1 else ""
        
        if cmd == "/configure":
            if arg:
                handle_configure_command_tg(arg.strip(), chat_id, user_id)
            else:
                send_telegram_message("Usage: /configure <repo-url>", chat_id)
            return
        
        if cmd == "/cancel":
            handle_cancel_command_tg(chat_id, user_id)
            return
        
        if cmd == "/status":
            status = get_pipeline_status_telegram()
            send_telegram_message(status, chat_id)
            return
        
        if cmd in ("/help", "/start"):
            send_telegram_message(get_help_text_telegram(), chat_id)
            return
    
    # Check for active configure session
    session = configure_manager.get_active_session(chat_id, user_id)
    if session and session.state in (SessionState.ASKING_COMMANDS,
                                      SessionState.ASKING_CONFIRM,
                                      SessionState.ASKING_OVERWRITE):
        session = configure_manager.handle_answer(chat_id, user_id, text)
        send_session_response_tg(chat_id, session)
        return
    
    # ... rest of existing code ...


def handle_configure_command_tg(repo_url: str, chat_id: str, user_id: str):
    """Handle /configure command in Telegram."""
    session = configure_manager.start(repo_url, chat_id, user_id, "telegram")
    
    if session.state == SessionState.ERROR:
        send_telegram_message(f"❌ {session.data.get('error')}", chat_id)
        return
    
    if session.stack:
        suggested = session.data.get("suggested_commands", {})
        send_telegram_message(
            f"*{session.data.get('description', session.stack)}* erkannt!\n\n"
            f"Test-Command? Vorschlag: `{suggested.get('test', 'npm test')}`\n"
            f"Antworte mit dem Command oder 'skip'.",
            chat_id
        )
    else:
        send_telegram_message("Stack wird analysiert...", chat_id)


def handle_cancel_command_tg(chat_id: str, user_id: str):
    """Handle /cancel command."""
    success = configure_manager.cancel(chat_id, user_id)
    if success:
        send_telegram_message("✅ Konfiguration abgebrochen.", chat_id)
    else:
        send_telegram_message("Keine aktive Konfiguration gefunden.", chat_id)


def send_session_response_tg(chat_id: str, session):
    """Send response based on session state."""
    if session.state == SessionState.ASKING_COMMANDS:
        q = session.data.get("current_question", "build")
        send_telegram_message(f"{q.title()}-Command?", chat_id)
    
    elif session.state == SessionState.ASKING_CONFIRM:
        send_telegram_message(
            f"*Preview:*\n"
            f"• 9 Agent-Profile für {session.stack}\n"
            f"• Repo: {session.repo_url}\n\n"
            f"Generieren? (ja/nein)",
            chat_id
        )
    
    elif session.state == SessionState.ASKING_OVERWRITE:
        send_telegram_message(
            "⚠️ `.claude/agents/` existiert bereits. Überschreiben? (ja/nein)",
            chat_id
        )
    
    elif session.state == SessionState.COMPLETE:
        send_telegram_message(
            f"✅ *Konfiguration abgeschlossen!*\n\n"
            f"• Repo: `{session.data.get('repo_name')}`\n"
            f"• Agents: {session.data.get('agents_count')}\n\n"
            f"Du kannst jetzt Tasks schicken!",
            chat_id
        )
    
    elif session.state == SessionState.ERROR:
        send_telegram_message(f"❌ Fehler: {session.data.get('error')}", chat_id)


def get_help_text_telegram() -> str:
    """Help text for Telegram."""
    return """*Mutirada Pipeline Bot* 🤖

*Task erstellen:*
Schreib einfach was du brauchst:
`Mobile Layout im Dashboard fixen`

*Repo konfigurieren:*
`/configure <repo-url>`
`/cancel` - Konfiguration abbrechen

*Status:*
`/status` oder `wie weit?`

*Unterstützte Stacks:*
FastAPI, React, Shopify, Shopware
"""
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/telegram_bot.py
git commit -m "feat(agent-designer): add /configure, /cancel commands to Telegram"
```

---

### Task 9: Stack Templates (Shopify + Shopware)

**Files:**
- Create: `orchestrator/templates/shopify-app/*.md` (9 files)
- Create: `orchestrator/templates/shopware-plugin/*.md` (9 files)

- [ ] **Step 1: Create Shopify App templates**

Create 9 agent templates in `orchestrator/templates/shopify-app/` with Shopify-specific patterns:
- Polaris components
- Remix loader/action
- App Bridge
- Prisma commands

- [ ] **Step 2: Create Shopware Plugin templates**

Create 9 agent templates in `orchestrator/templates/shopware-plugin/` with Shopware-specific patterns:
- PHP Services + DI
- Entity Definitions
- Vue Admin-UI
- PHPUnit + PHPStan

- [ ] **Step 3: Commit**

```bash
git add orchestrator/templates/
git commit -m "feat(agent-designer): add Shopify App and Shopware Plugin templates"
```

---

### Task 10: Update Orchestrator for Dynamic Repos

**Files:**
- Modify: `orchestrator/orchestrator/main.py`

- [ ] **Step 1: Update _get_repo_dir to use DB**

```python
# Update in orchestrator/orchestrator/main.py

def _get_repo_dir(self, task_id: int) -> Path:
    """Get the repo directory based on task data."""
    try:
        task = self.task_queue.get_task(task_id)
        if task and hasattr(task, 'id'):
            result = self.db.execute(
                "SELECT data FROM agency_tasks WHERE id = %s",
                (task_id,)
            ).fetchone()
            if result and result.get("data"):
                import json
                data = result["data"] if isinstance(result["data"], dict) else json.loads(result["data"])
                repo_name = data.get("repo", "backend")
                
                # Lookup in agency_repos
                repo = self.db.execute(
                    "SELECT path FROM agency_repos WHERE name = %s",
                    (repo_name,)
                ).fetchone()
                
                if repo:
                    return Path(repo["path"])
                
                # Fallback for legacy names
                if repo_name == "frontend":
                    return Path("/opt/agency/repos/falara-frontend")
    except Exception:
        pass
    return Path("/opt/agency/repos/falara")
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/main.py
git commit -m "feat(agent-designer): update orchestrator to use dynamic repo lookup"
```

---

### Task 11: Deploy and Test

- [ ] **Step 1: Sync to server**

```bash
rsync -avz /home/boris/projects/mutirada/orchestrator/ root@46.225.19.209:/opt/agency/orchestrator/
```

- [ ] **Step 2: Run migration**

```bash
ssh root@46.225.19.209 "psql -U agency -d agency_db -f /opt/agency/orchestrator/migrations/003_agent_designer.sql"
```

- [ ] **Step 3: Restart services**

```bash
ssh root@46.225.19.209 "systemctl restart mutirada-api mutirada-orchestrator"
```

- [ ] **Step 4: Test via Telegram**

```
/configure https://github.com/borisdeluxe/falara-shopify
```

Expected: Stack detected, questions asked, configuration completed.

- [ ] **Step 5: Verify repo registered**

```bash
ssh root@46.225.19.209 "psql -U agency -d agency_db -c 'SELECT * FROM agency_repos'"
```

---

## Summary

11 Tasks, ~50 steps. Estimated time: 3-4 hours with subagents.

Key deliverables:
1. Database migration with agency_repos and sessions tables
2. RepoManager with URL validation and path safety
3. StackDetector with priority-based detection
4. AgentGenerator with template system
5. ConversationManager with session state machine
6. API endpoints for /api/configure
7. Slack /configure, /cancel commands
8. Telegram /configure, /cancel commands
9. Shopify + Shopware templates (36 files)
10. Orchestrator dynamic repo lookup
11. Deployment and testing
