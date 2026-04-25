"""Gate validation - checks artifact status lines and enforces handoff rules."""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, List


class GateStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    RETURN = "return"
    BLOCKED = "blocked"


@dataclass
class GateResult:
    status: GateStatus
    next_agent: Optional[str] = None
    return_to: Optional[str] = None
    reason: str = ""


@dataclass
class RetryCheckResult:
    escalate: bool
    retry_count: int = 0


class GateValidator:
    """Validates artifact status lines and enforces gate rules."""

    # Valid agent sequence
    AGENT_SEQUENCE = [
        "concept_clarifier",
        "architect_planner",
        "test_designer",
        "implementer",
        "security_reviewer",
        "qa_validator",
        "docs_updater",
        "deploy_runner",
    ]

    # Map uppercase agent names to lowercase
    AGENT_MAP = {
        "CONCEPT_CLARIFIER": "concept_clarifier",
        "ARCHITECT_PLANNER": "architect_planner",
        "TEST_DESIGNER": "test_designer",
        "IMPLEMENTER": "implementer",
        "SECURITY_REVIEWER": "security_reviewer",
        "QA_VALIDATOR": "qa_validator",
        "DOCS_UPDATER": "docs_updater",
        "DEPLOY_RUNNER": "deploy_runner",
    }

    def __init__(self, db):
        self.db = db
        self._retry_counts: dict[tuple[str, str], int] = {}

    def _parse_status_line(self, artifact: str) -> Optional[str]:
        """Extract STATUS line from artifact."""
        for line in artifact.split("\n"):
            line = line.strip()
            if line.startswith("STATUS:"):
                return line[7:].strip()
        return None

    def validate_artifact(
        self,
        artifact: str,
        current_agent: str,
        required_sections: Optional[List[str]] = None
    ) -> GateResult:
        """Validate artifact status line and required sections."""
        # Check required sections first
        if required_sections:
            for section in required_sections:
                if f"## {section}" not in artifact:
                    return GateResult(
                        status=GateStatus.FAILED,
                        reason=f"Missing required section: {section}",
                    )

        # Parse status line
        status_value = self._parse_status_line(artifact)
        if status_value is None:
            return GateResult(
                status=GateStatus.FAILED,
                reason="Status line missing",
            )

        # Handle READY_FOR_<AGENT>
        if status_value.startswith("READY_FOR_"):
            agent_key = status_value[10:]  # Remove "READY_FOR_"
            if agent_key in self.AGENT_MAP:
                return GateResult(
                    status=GateStatus.PASSED,
                    next_agent=self.AGENT_MAP[agent_key],
                )
            return GateResult(
                status=GateStatus.FAILED,
                reason=f"Invalid agent in status: {agent_key}",
            )

        # Handle RETURN_TO_<AGENT>
        if status_value.startswith("RETURN_TO_"):
            agent_key = status_value[10:]  # Remove "RETURN_TO_"
            if agent_key in self.AGENT_MAP:
                return GateResult(
                    status=GateStatus.RETURN,
                    return_to=self.AGENT_MAP[agent_key],
                )
            return GateResult(
                status=GateStatus.FAILED,
                reason=f"Invalid agent in return: {agent_key}",
            )

        # Handle BLOCKED_<REASON>
        if status_value.startswith("BLOCKED_"):
            reason = status_value[8:].lower()  # Remove "BLOCKED_"
            return GateResult(
                status=GateStatus.BLOCKED,
                reason=reason,
            )

        # Unknown status format
        return GateResult(
            status=GateStatus.FAILED,
            reason=f"Invalid status format: {status_value}",
        )

    def validate_artifact_file(self, path: Path, current_agent: str) -> GateResult:
        """Read artifact from file and validate."""
        if not path.exists():
            return GateResult(
                status=GateStatus.FAILED,
                reason=f"Artifact file not found: {path}",
            )

        artifact = path.read_text()
        return self.validate_artifact(artifact, current_agent)

    def is_valid_transition(self, from_agent: str, to_agent: str) -> bool:
        """Check if agent transition is valid."""
        # Returns (going backwards) are always valid
        if from_agent in self.AGENT_SEQUENCE and to_agent in self.AGENT_SEQUENCE:
            from_idx = self.AGENT_SEQUENCE.index(from_agent)
            to_idx = self.AGENT_SEQUENCE.index(to_agent)

            # Backwards (return) is always valid
            if to_idx < from_idx:
                return True

            # Forward must be exactly one step
            if to_idx == from_idx + 1:
                return True

        return False

    def increment_retry(self, feature_id: str, agent: str) -> None:
        """Increment retry count for feature/agent pair."""
        key = (feature_id, agent)
        self._retry_counts[key] = self._retry_counts.get(key, 0) + 1

    def get_retry_count(self, feature_id: str, agent: str) -> int:
        """Get current retry count for feature/agent pair."""
        return self._retry_counts.get((feature_id, agent), 0)

    def check_retry_limit(
        self, feature_id: str, agent: str, max_retries: int = 2
    ) -> RetryCheckResult:
        """Check if retry limit reached and escalation needed."""
        count = self.get_retry_count(feature_id, agent)
        return RetryCheckResult(
            escalate=count >= max_retries,
            retry_count=count,
        )
