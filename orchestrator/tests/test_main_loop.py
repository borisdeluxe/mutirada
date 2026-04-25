"""Tests for orchestrator main loop."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from orchestrator.main import Orchestrator, AgentSession
from orchestrator.gate import GateStatus, GateResult


class TestOrchestratorInit:
    """Orchestrator should initialize with required dependencies."""

    def test_init_with_dependencies(self, mock_db, tmp_path):
        """Should accept db connection and create internal components."""
        orch = Orchestrator(db=mock_db, pipeline_dir=tmp_path / ".pipeline")

        assert orch.task_queue is not None
        assert orch.budget is not None
        assert orch.gate is not None

    def test_init_creates_pipeline_dir(self, mock_db, tmp_path):
        """Should create .pipeline directory if missing."""
        pipeline_dir = tmp_path / ".pipeline"
        orch = Orchestrator(db=mock_db, pipeline_dir=pipeline_dir)

        assert pipeline_dir.exists()


class TestOrchestratorDispatch:
    """Orchestrator should dispatch tasks to agents."""

    def test_dispatch_pending_task_to_first_agent(self, orchestrator):
        """Should start concept_clarifier for new feature tasks."""
        orchestrator.task_queue.fetch_pending = Mock(return_value=Mock(
            id=1,
            feature_id="FAL-47",
            source="github",
            status="pending",
        ))
        orchestrator.budget.can_spend = Mock(return_value=Mock(allowed=True))

        with patch.object(orchestrator, 'start_agent_session') as mock_start:
            orchestrator.process_one()

        mock_start.assert_called_once()
        call_args = mock_start.call_args
        assert call_args[1]['agent'] == 'concept_clarifier'
        assert call_args[1]['feature_id'] == 'FAL-47'

    def test_dispatch_review_task_to_security_reviewer(self, orchestrator):
        """Should start security_reviewer for review tasks."""
        orchestrator.task_queue.fetch_pending = Mock(return_value=Mock(
            id=2,
            feature_id="REVIEW-1",
            source="review",
            status="pending",
        ))
        orchestrator.budget.can_spend = Mock(return_value=Mock(allowed=True))

        with patch.object(orchestrator, 'start_agent_session') as mock_start:
            orchestrator.process_one()

        call_args = mock_start.call_args
        assert call_args[1]['agent'] == 'security_reviewer'

    def test_skip_if_budget_exceeded(self, orchestrator):
        """Should fail task if budget check fails."""
        orchestrator.task_queue.fetch_pending = Mock(return_value=Mock(
            id=1,
            feature_id="FAL-47",
            source="github",
            status="pending",
        ))
        orchestrator.budget.can_spend = Mock(return_value=Mock(
            allowed=False,
            reason="Daily budget exceeded"
        ))

        with patch.object(orchestrator, 'start_agent_session') as mock_start:
            orchestrator.process_one()

        mock_start.assert_not_called()
        orchestrator.task_queue.fail_task.assert_called()

    def test_no_action_when_queue_empty(self, orchestrator):
        """Should do nothing when no pending tasks."""
        orchestrator.task_queue.fetch_pending = Mock(return_value=None)

        with patch.object(orchestrator, 'start_agent_session') as mock_start:
            orchestrator.process_one()

        mock_start.assert_not_called()


class TestAgentSessionManagement:
    """Orchestrator should manage tmux agent sessions."""

    def test_start_agent_session_creates_tmux(self, orchestrator):
        """Should create tmux session with correct parameters."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)

            orchestrator.start_agent_session(
                agent="concept_clarifier",
                feature_id="FAL-47",
                task_id=1,
            )

        mock_run.assert_called()
        cmd = mock_run.call_args[0][0]
        assert 'tmux' in cmd[0]
        assert 'FAL-47' in ' '.join(cmd)

    def test_check_session_status_running(self, orchestrator):
        """Should detect running session."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)

            status = orchestrator.check_session_status("FAL-47-concept")

        assert status == "running"

    def test_check_session_status_completed(self, orchestrator):
        """Should detect completed session (tmux session gone)."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=1)

            status = orchestrator.check_session_status("FAL-47-concept")

        assert status == "completed"


class TestGateEnforcement:
    """Orchestrator should enforce gates between agents."""

    def test_advance_to_next_agent_on_pass(self, orchestrator):
        """Should start next agent when gate passes."""
        orchestrator._active_sessions = {
            "FAL-47": AgentSession(
                feature_id="FAL-47",
                task_id=1,
                current_agent="concept_clarifier",
                tmux_session="FAL-47-concept",
            )
        }

        with patch.object(orchestrator, 'check_session_status', return_value="completed"):
            with patch.object(orchestrator.gate, 'validate_artifact_file') as mock_gate:
                mock_gate.return_value = GateResult(
                    status=GateStatus.PASSED,
                    next_agent="architect_planner",
                )
                with patch.object(orchestrator, 'start_agent_session') as mock_start:
                    orchestrator.check_active_sessions()

        mock_start.assert_called_once()
        assert mock_start.call_args[1]['agent'] == 'architect_planner'

    def test_return_to_previous_on_gate_return(self, orchestrator):
        """Should restart previous agent on RETURN status."""
        orchestrator._active_sessions = {
            "FAL-47": AgentSession(
                feature_id="FAL-47",
                task_id=1,
                current_agent="security_reviewer",
                tmux_session="FAL-47-security",
            )
        }

        with patch.object(orchestrator, 'check_session_status', return_value="completed"):
            with patch.object(orchestrator.gate, 'validate_artifact_file') as mock_gate:
                mock_gate.return_value = GateResult(
                    status=GateStatus.RETURN,
                    return_to="implementer",
                )
                with patch.object(orchestrator, 'start_agent_session') as mock_start:
                    orchestrator.check_active_sessions()

        assert mock_start.call_args[1]['agent'] == 'implementer'

    def test_escalate_after_max_retries(self, orchestrator):
        """Should escalate to Slack after max retries."""
        orchestrator._active_sessions = {
            "FAL-47": AgentSession(
                feature_id="FAL-47",
                task_id=1,
                current_agent="implementer",
                tmux_session="FAL-47-impl",
            )
        }
        orchestrator.gate._retry_counts = {("FAL-47", "implementer"): 2}

        with patch.object(orchestrator, 'check_session_status', return_value="completed"):
            with patch.object(orchestrator.gate, 'validate_artifact_file') as mock_gate:
                mock_gate.return_value = GateResult(
                    status=GateStatus.RETURN,
                    return_to="implementer",
                )
                with patch.object(orchestrator, 'notify_escalation') as mock_notify:
                    orchestrator.check_active_sessions()

        mock_notify.assert_called_once()


class TestCostTracking:
    """Orchestrator should track costs per task."""

    def test_record_cost_after_agent_completes(self, orchestrator):
        """Should record API cost when agent finishes."""
        orchestrator._active_sessions = {
            "FAL-47": AgentSession(
                feature_id="FAL-47",
                task_id=1,
                current_agent="concept_clarifier",
                tmux_session="FAL-47-concept",
            )
        }

        with patch.object(orchestrator, 'check_session_status', return_value="completed"):
            with patch.object(orchestrator, 'get_session_cost', return_value=0.12):
                with patch.object(orchestrator.gate, 'validate_artifact_file') as mock_gate:
                    mock_gate.return_value = GateResult(
                        status=GateStatus.PASSED,
                        next_agent="architect_planner",
                    )
                    with patch.object(orchestrator, 'start_agent_session'):
                        orchestrator.check_active_sessions()

        orchestrator.task_queue.add_cost.assert_called_with(1, 0.12)


class TestPipelineCompletion:
    """Orchestrator should handle pipeline completion."""

    def test_complete_task_after_final_agent(self, orchestrator):
        """Should mark task complete when deploy_runner finishes."""
        orchestrator._active_sessions = {
            "FAL-47": AgentSession(
                feature_id="FAL-47",
                task_id=1,
                current_agent="deploy_runner",
                tmux_session="FAL-47-deploy",
            )
        }

        with patch.object(orchestrator, 'check_session_status', return_value="completed"):
            with patch.object(orchestrator, 'get_session_cost', return_value=0.10):
                with patch.object(orchestrator.gate, 'validate_artifact_file') as mock_gate:
                    mock_gate.return_value = GateResult(
                        status=GateStatus.PASSED,
                        next_agent=None,
                    )
                    orchestrator.check_active_sessions()

        orchestrator.task_queue.complete_task.assert_called()


# Fixtures

@pytest.fixture
def orchestrator(mock_db, tmp_path):
    """Orchestrator with mocked dependencies."""
    orch = Orchestrator(db=mock_db, pipeline_dir=tmp_path / ".pipeline")
    orch.task_queue.fail_task = Mock()
    orch.task_queue.complete_task = Mock()
    orch.task_queue.add_cost = Mock()
    orch.task_queue.start_task = Mock()
    return orch
