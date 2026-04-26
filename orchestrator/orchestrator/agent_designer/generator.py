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
