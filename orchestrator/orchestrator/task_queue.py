"""Task queue operations - manages persistent tasks in Postgres."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: int
    feature_id: str
    source: str
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cost_eur: float = 0.0
    current_agent: Optional[str] = None
    error: Optional[str] = None


class TaskQueue:
    """Manages task queue in Postgres."""

    def __init__(self, db):
        self.db = db

    def _row_to_task(self, row: dict) -> Task:
        """Convert database row to Task object."""
        return Task(
            id=row["id"],
            feature_id=row["feature_id"],
            source=row["source"],
            status=TaskStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            cost_eur=float(row.get("cost_eur") or 0),
            current_agent=row.get("current_agent"),
            error=row.get("error"),
        )

    def fetch_pending(self) -> Optional[Task]:
        """Fetch oldest pending task."""
        result = self.db.execute(
            """
            SELECT * FROM agency_tasks
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()

        if result is None:
            return None
        return self._row_to_task(result)

    def get_task(self, task_id: int) -> Task:
        """Get task by ID."""
        result = self.db.execute(
            "SELECT * FROM agency_tasks WHERE id = %s",
            (task_id,)
        ).fetchone()

        if result is None:
            raise ValueError(f"Task {task_id} not found")
        return self._row_to_task(result)

    def start_task(self, task_id: int) -> None:
        """Mark task as in progress."""
        self.db.execute(
            """
            UPDATE agency_tasks
            SET status = 'in_progress', started_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (task_id,)
        )

    def complete_task(self, task_id: int, cost_eur: float) -> None:
        """Mark task as completed with final cost."""
        self.db.execute(
            """
            UPDATE agency_tasks
            SET status = 'completed', cost_eur = %s, completed_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (cost_eur, task_id)
        )

    def fail_task(self, task_id: int, error: str) -> None:
        """Mark task as failed with error message."""
        self.db.execute(
            """
            UPDATE agency_tasks
            SET status = 'failed', error = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (error, task_id)
        )

    def cancel_task(self, task_id: int) -> None:
        """Mark task as cancelled."""
        self.db.execute(
            """
            UPDATE agency_tasks
            SET status = 'cancelled', updated_at = NOW()
            WHERE id = %s
            """,
            (task_id,)
        )

    def update_current_agent(self, task_id: int, agent: str) -> None:
        """Update which agent is currently working on the task."""
        self.db.execute(
            """
            UPDATE agency_tasks
            SET current_agent = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (agent, task_id)
        )

    def add_cost(self, task_id: int, amount: float) -> None:
        """Add cost atomically using UPDATE ... SET cost = cost + amount."""
        self.db.execute(
            """
            UPDATE agency_tasks
            SET cost_eur = cost_eur + %s, updated_at = NOW()
            WHERE id = %s
            """,
            (amount, task_id)
        )
