"""Tests for task queue operations."""
import pytest
from datetime import datetime, timezone

from orchestrator.task_queue import TaskQueue, Task, TaskStatus


class TestTaskQueue:
    """Task queue should manage persistent tasks in Postgres."""

    def test_fetch_pending_returns_oldest_first(self, task_queue: TaskQueue):
        """Pending tasks should be returned in FIFO order."""
        task = task_queue.fetch_pending()

        assert task is not None
        assert task.status == TaskStatus.PENDING
        assert task.feature_id == "FAL-001"  # Oldest pending task

    def test_fetch_pending_returns_none_when_empty(self, empty_task_queue: TaskQueue):
        """Should return None when no pending tasks exist."""
        task = empty_task_queue.fetch_pending()

        assert task is None

    def test_fetch_pending_skips_in_progress(self, task_queue: TaskQueue):
        """Should not return tasks that are already in progress."""
        # First fetch gets FAL-001
        task1 = task_queue.fetch_pending()
        task_queue.start_task(task1.id)

        # Second fetch should get FAL-002, not FAL-001
        task2 = task_queue.fetch_pending()

        assert task2.feature_id == "FAL-002"

    def test_start_task_updates_status(self, task_queue: TaskQueue):
        """Starting a task should set status to in_progress and record start time."""
        task = task_queue.fetch_pending()

        task_queue.start_task(task.id)

        updated = task_queue.get_task(task.id)
        assert updated.status == TaskStatus.IN_PROGRESS
        assert updated.started_at is not None

    def test_complete_task_records_cost(self, task_queue: TaskQueue):
        """Completing a task should record final cost and completion time."""
        task = task_queue.fetch_pending()
        task_queue.start_task(task.id)

        task_queue.complete_task(task.id, cost_eur=1.50)

        updated = task_queue.get_task(task.id)
        assert updated.status == TaskStatus.COMPLETED
        assert updated.cost_eur == 1.50
        assert updated.completed_at is not None

    def test_fail_task_records_error(self, task_queue: TaskQueue):
        """Failing a task should record error message."""
        task = task_queue.fetch_pending()
        task_queue.start_task(task.id)

        task_queue.fail_task(task.id, error="Gate check failed: security issues")

        updated = task_queue.get_task(task.id)
        assert updated.status == TaskStatus.FAILED
        assert "security issues" in updated.error

    def test_cancel_task_sets_cancelled_status(self, task_queue: TaskQueue):
        """Cancelling a task should set status to cancelled."""
        task = task_queue.fetch_pending()

        task_queue.cancel_task(task.id)

        updated = task_queue.get_task(task.id)
        assert updated.status == TaskStatus.CANCELLED

    def test_update_current_agent(self, task_queue: TaskQueue):
        """Should track which agent is currently working on the task."""
        task = task_queue.fetch_pending()
        task_queue.start_task(task.id)

        task_queue.update_current_agent(task.id, "implementer")

        updated = task_queue.get_task(task.id)
        assert updated.current_agent == "implementer"

    def test_add_cost_increments_atomically(self, task_queue: TaskQueue):
        """Adding cost should use atomic increment, not read-then-write."""
        task = task_queue.fetch_pending()
        task_queue.start_task(task.id)

        task_queue.add_cost(task.id, 0.50)
        task_queue.add_cost(task.id, 0.30)

        updated = task_queue.get_task(task.id)
        assert updated.cost_eur == 0.80


@pytest.fixture
def task_queue(test_db):
    """Task queue with test tasks."""
    # Add test tasks using helper (works with both real DB and InMemoryDB)
    if hasattr(test_db, 'add_task'):
        test_db.add_task('FAL-001', status='pending')
        test_db.add_task('FAL-002', status='pending')
        test_db.add_task('FAL-003', status='in_progress')
    else:
        test_db.execute("""
            INSERT INTO agency_tasks (feature_id, source, status, created_at)
            VALUES
                ('FAL-001', 'test', 'pending', NOW() - INTERVAL '2 hours'),
                ('FAL-002', 'test', 'pending', NOW() - INTERVAL '1 hour'),
                ('FAL-003', 'test', 'in_progress', NOW())
        """)
    return TaskQueue(test_db)


@pytest.fixture
def empty_task_queue(test_db):
    """Task queue with no pending tasks."""
    return TaskQueue(test_db)
