"""Tests for StackDetector module."""
import pytest
from pathlib import Path
from orchestrator.agent_designer.detector import StackDetector, StackDetectionResult


def test_detect_fastapi(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["fastapi"]\n')

    detector = StackDetector()
    result = detector.detect(tmp_path)

    assert result.stack == "fastapi"
    assert result.confidence > 0.5


def test_detect_shopify_app(tmp_path):
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

    assert result.stack == "shopify-app"


def test_detect_unknown_stack(tmp_path):
    detector = StackDetector()
    result = detector.detect(tmp_path)

    assert result.stack is None
    assert result.confidence == 0.0
