"""Orchestrator main loop - dispatches tasks to agents and enforces gates."""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict

from .task_queue import TaskQueue
from .budget import BudgetEnforcer
from .gate import GateValidator, GateStatus


@dataclass
class AgentSession:
    """Tracks an active agent session."""
    feature_id: str
    task_id: int
    current_agent: str
    tmux_session: str
    started_at: Optional[str] = None


class Orchestrator:
    """Main orchestrator loop - dispatches tasks and enforces gates."""

    AGENT_SEQUENCE = [
        "concept_clarifier",
        "architect_planner",
        "test_designer",
        "implementer",
        "security_reviewer",
        "refactorer",
        "qa_validator",
        "docs_updater",
        "deploy_runner",
    ]

    REVIEW_ENTRY_POINT = "security_reviewer"

    AGENT_OUTPUT_ARTIFACTS = {
        "concept_clarifier": "tk-draft.md",
        "architect_planner": "plan.md",
        "test_designer": "test-plan.md",
        "implementer": "implementation.md",
        "security_reviewer": "security-report.md",
        "refactorer": "refactor-report.md",
        "qa_validator": "qa-report.md",
        "docs_updater": "docs-report.md",
        "deploy_runner": "deploy-log.md",
    }

    def __init__(
        self,
        db,
        pipeline_dir: Optional[Path] = None,
        worktree_dir: Optional[Path] = None,
    ):
        self.db = db
        self.task_queue = TaskQueue(db)
        self.budget = BudgetEnforcer(db)
        self.gate = GateValidator(db)

        self.pipeline_dir = pipeline_dir or Path("/opt/agency/.pipeline")
        self.worktree_dir = worktree_dir or Path("/opt/agency/worktrees")

        self.pipeline_dir.mkdir(parents=True, exist_ok=True)

        self._active_sessions: Dict[str, AgentSession] = {}

    def process_one(self) -> bool:
        """Process one pending task. Returns True if a task was processed."""
        task = self.task_queue.fetch_pending()
        if task is None:
            return False

        budget_check = self.budget.can_spend(task.feature_id, amount=0.50)
        if not budget_check.allowed:
            self.task_queue.fail_task(task.id, f"Budget exceeded: {budget_check.reason}")
            return True

        self.task_queue.start_task(task.id)

        if task.source == "review":
            first_agent = self.REVIEW_ENTRY_POINT
        else:
            first_agent = self.AGENT_SEQUENCE[0]

        self.start_agent_session(
            agent=first_agent,
            feature_id=task.feature_id,
            task_id=task.id,
        )

        return True

    def start_agent_session(
        self,
        agent: str,
        feature_id: str,
        task_id: int,
    ) -> None:
        """Start a new agent session in tmux."""
        session_name = f"{feature_id}-{agent.split('_')[0]}"

        feature_pipeline = self.pipeline_dir / feature_id
        feature_pipeline.mkdir(parents=True, exist_ok=True)

        feature_worktree = self.worktree_dir / feature_id

        cmd = [
            "tmux", "new-session", "-d", "-s", session_name,
            f"cd {feature_worktree} && "
            f"claude --profile {agent} "
            f"--input {feature_pipeline}/input.md "
            f"--output {feature_pipeline}/{self.AGENT_OUTPUT_ARTIFACTS.get(agent, 'output.md')}"
        ]

        subprocess.run(cmd, check=False)

        self._active_sessions[feature_id] = AgentSession(
            feature_id=feature_id,
            task_id=task_id,
            current_agent=agent,
            tmux_session=session_name,
        )

        self.task_queue.update_current_agent(task_id, agent)

    def check_session_status(self, session_name: str) -> str:
        """Check if tmux session is still running."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        return "running" if result.returncode == 0 else "completed"

    def check_active_sessions(self) -> None:
        """Check all active sessions and handle completions."""
        completed = []

        for feature_id, session in self._active_sessions.items():
            status = self.check_session_status(session.tmux_session)

            if status == "completed":
                self._handle_session_complete(session)
                completed.append(feature_id)

        for feature_id in completed:
            del self._active_sessions[feature_id]

    def _handle_session_complete(self, session: AgentSession) -> None:
        """Handle a completed agent session."""
        cost = self.get_session_cost(session.tmux_session)
        self.task_queue.add_cost(session.task_id, cost)

        artifact_path = (
            self.pipeline_dir
            / session.feature_id
            / self.AGENT_OUTPUT_ARTIFACTS.get(session.current_agent, "output.md")
        )

        gate_result = self.gate.validate_artifact_file(artifact_path, session.current_agent)

        if gate_result.status == GateStatus.PASSED:
            if gate_result.next_agent:
                self.start_agent_session(
                    agent=gate_result.next_agent,
                    feature_id=session.feature_id,
                    task_id=session.task_id,
                )
            else:
                self.task_queue.complete_task(session.task_id, cost)

        elif gate_result.status == GateStatus.RETURN:
            retry_check = self.gate.check_retry_limit(
                session.feature_id,
                gate_result.return_to,
            )

            if retry_check.escalate:
                self.notify_escalation(session, gate_result)
            else:
                self.gate.increment_retry(session.feature_id, gate_result.return_to)
                self.start_agent_session(
                    agent=gate_result.return_to,
                    feature_id=session.feature_id,
                    task_id=session.task_id,
                )

        elif gate_result.status == GateStatus.FAILED:
            self.task_queue.fail_task(session.task_id, gate_result.reason)

        elif gate_result.status == GateStatus.BLOCKED:
            self.notify_escalation(session, gate_result)

    def get_session_cost(self, session_name: str) -> float:
        """Get API cost from completed session. Placeholder for now."""
        return 0.10

    def notify_escalation(self, session: AgentSession, gate_result) -> None:
        """Send Slack notification for escalation. Placeholder for now."""
        pass

    def run_loop(self, interval: int = 30) -> None:
        """Main loop - process tasks and check sessions."""
        import time

        print(f"Orchestrator starting, polling every {interval}s...")
        while True:
            try:
                processed = self.process_one()
                if processed:
                    print(f"Processed task")
                self.check_active_sessions()
            except Exception as e:
                print(f"Error in loop: {e}")
            time.sleep(interval)


def main():
    """Entry point for orchestrator service."""
    import os
    import psycopg
    from psycopg.rows import dict_row

    db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://agency:agency@localhost:5432/agency_db'
    )

    print(f"Connecting to database...")
    db = psycopg.connect(db_url, row_factory=dict_row)
    print(f"Connected. Starting orchestrator...")

    orch = Orchestrator(db=db)
    orch.run_loop(interval=30)


if __name__ == '__main__':
    main()
