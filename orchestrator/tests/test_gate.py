"""Tests for gate validation."""
import pytest
from pathlib import Path

from orchestrator.gate import GateValidator, GateResult, GateStatus


class TestGateValidator:
    """Gate validator should check artifact status lines and enforce handoff rules."""

    def test_validate_status_line_passes_ready(self, gate: GateValidator):
        """Should pass when status line indicates ready for next agent."""
        artifact = "# Report\n\nSome content.\n\nSTATUS: READY_FOR_IMPLEMENTER"

        result = gate.validate_artifact(artifact, current_agent="test_designer")

        assert result.status == GateStatus.PASSED
        assert result.next_agent == "implementer"

    def test_validate_status_line_fails_missing(self, gate: GateValidator):
        """Should fail when status line is missing."""
        artifact = "# Report\n\nSome content without status line."

        result = gate.validate_artifact(artifact, current_agent="test_designer")

        assert result.status == GateStatus.FAILED
        assert "missing" in result.reason.lower()

    def test_validate_status_line_fails_invalid_format(self, gate: GateValidator):
        """Should fail when status line has invalid format."""
        artifact = "# Report\n\nSTATUS: SOMETHING_WRONG"

        result = gate.validate_artifact(artifact, current_agent="test_designer")

        assert result.status == GateStatus.FAILED
        assert "invalid" in result.reason.lower()

    def test_validate_return_to_author(self, gate: GateValidator):
        """Should recognize RETURN_TO status as gate failure with retry."""
        artifact = "# Report\n\nSTATUS: RETURN_TO_ARCHITECT_PLANNER"

        result = gate.validate_artifact(artifact, current_agent="security_reviewer")

        assert result.status == GateStatus.RETURN
        assert result.return_to == "architect_planner"

    def test_validate_blocked_status(self, gate: GateValidator):
        """Should recognize BLOCKED status as requiring intervention."""
        artifact = "# Report\n\nSTATUS: BLOCKED_REVIEW_FAILED"

        result = gate.validate_artifact(artifact, current_agent="qa_validator")

        assert result.status == GateStatus.BLOCKED
        assert "review_failed" in result.reason.lower()

    def test_validate_checks_required_sections(self, gate: GateValidator):
        """Should verify required sections are present based on agent role."""
        # QA report missing "Gate Decision" section
        artifact = """# QA Report

## Summary
All good.

STATUS: READY_FOR_DEPLOY_RUNNER
"""
        result = gate.validate_artifact(
            artifact,
            current_agent="qa_validator",
            required_sections=["Summary", "Gate Decision"]
        )

        assert result.status == GateStatus.FAILED
        assert "gate decision" in result.reason.lower()

    def test_validate_file_reads_from_path(self, gate: GateValidator, tmp_path: Path):
        """Should read artifact from file path."""
        artifact_path = tmp_path / "test-report.md"
        artifact_path.write_text("# Report\n\nSTATUS: READY_FOR_IMPLEMENTER")

        result = gate.validate_artifact_file(artifact_path, current_agent="test_designer")

        assert result.status == GateStatus.PASSED

    def test_validate_file_fails_on_missing_file(self, gate: GateValidator, tmp_path: Path):
        """Should fail gracefully when artifact file doesn't exist."""
        missing_path = tmp_path / "nonexistent.md"

        result = gate.validate_artifact_file(missing_path, current_agent="test_designer")

        assert result.status == GateStatus.FAILED
        assert "not found" in result.reason.lower()


class TestGateAgentSequence:
    """Gate should enforce correct agent sequence."""

    def test_valid_sequence_test_designer_to_implementer(self, gate: GateValidator):
        """test_designer -> implementer is valid."""
        assert gate.is_valid_transition("test_designer", "implementer") is True

    def test_valid_sequence_implementer_to_security(self, gate: GateValidator):
        """implementer -> security_reviewer is valid."""
        assert gate.is_valid_transition("implementer", "security_reviewer") is True

    def test_invalid_sequence_skipping_agent(self, gate: GateValidator):
        """test_designer -> qa_validator is invalid (skips implementer)."""
        assert gate.is_valid_transition("test_designer", "qa_validator") is False

    def test_return_sequence_is_valid(self, gate: GateValidator):
        """Returning to earlier agent is always valid."""
        assert gate.is_valid_transition("security_reviewer", "architect_planner") is True


class TestRetryTracking:
    """Gate should track retries per agent."""

    def test_increment_retry_count(self, gate: GateValidator):
        """Should track retry count per feature/agent pair."""
        gate.increment_retry("FAL-001", "implementer")
        gate.increment_retry("FAL-001", "implementer")

        assert gate.get_retry_count("FAL-001", "implementer") == 2

    def test_max_retries_triggers_escalation(self, gate: GateValidator):
        """Should indicate escalation needed after max retries."""
        gate.increment_retry("FAL-001", "implementer")
        gate.increment_retry("FAL-001", "implementer")

        result = gate.check_retry_limit("FAL-001", "implementer", max_retries=2)

        assert result.escalate is True


@pytest.fixture
def gate(mock_db):
    """Gate validator instance."""
    return GateValidator(mock_db)
