"""Tests for AgentGenerator module."""
import pytest
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
