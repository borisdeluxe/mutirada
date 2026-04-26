"""Pytest fixtures for orchestrator tests."""
import pytest
import os


class MockCursor:
    """Mock cursor for unit tests without real DB."""
    def __init__(self, results=None):
        self._results = results or []
        self._index = 0

    def fetchone(self):
        if self._index < len(self._results):
            result = self._results[self._index]
            self._index += 1
            return result
        return None

    def fetchall(self):
        return self._results


class MockDB:
    """Mock database for unit tests without real DB."""
    def __init__(self):
        self._queries = []
        self._results = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def execute(self, query, params=None):
        self._queries.append((query, params))
        return MockCursor(self._results.get(query.strip()[:50], []))

    def commit(self):
        pass

    def set_result(self, query_prefix, results):
        """Set expected results for queries starting with prefix."""
        self._results[query_prefix] = results


@pytest.fixture(scope="session")
def db_url():
    """Database URL for tests. Uses test database."""
    return os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://agency:test@localhost:5432/agency_test"
    )


class InMemoryDB:
    """In-memory database simulation for unit tests."""

    def __init__(self):
        self._tasks = {}
        self._id_counter = 1
        self._queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def execute(self, query, params=None):
        self._queries.append((query, params))
        query_lower = query.strip().lower()

        if query_lower.startswith("insert into agency_tasks"):
            return self._handle_insert(query, params)
        elif query_lower.startswith("select") and "agency_tasks" in query_lower:
            return self._handle_select(query, params)
        elif query_lower.startswith("update agency_tasks"):
            return self._handle_update(query, params)
        elif query_lower.startswith("delete"):
            return MockCursor([])
        elif query_lower.startswith("begin") or query_lower.startswith("rollback"):
            return MockCursor([])

        return MockCursor([])

    def _handle_insert(self, query, params):
        if params:
            task = {
                'id': self._id_counter,
                'feature_id': params[0] if len(params) > 0 else f'TASK-{self._id_counter}',
                'source': params[1] if len(params) > 1 else 'test',
                'status': 'pending',
                'cost_eur': 0.0,
                'current_agent': None,
                'started_at': None,
                'completed_at': None,
                'error': None,
                'created_at': 'NOW()',
            }
            self._tasks[self._id_counter] = task
            self._id_counter += 1
        return MockCursor([])

    def _handle_select(self, query, params):
        query_lower = query.lower()

        if "status = 'pending'" in query_lower or "status in ('pending')" in query_lower:
            pending = [t for t in self._tasks.values() if t['status'] == 'pending']
            pending.sort(key=lambda x: x['id'])
            return MockCursor(pending)

        if "feature_id =" in query_lower or "feature_id=" in query_lower:
            feature_id = None
            if params:
                feature_id = params[0]
            else:
                # Extract from inline query: WHERE feature_id = 'FAL-001'
                import re
                match = re.search(r"feature_id\s*=\s*'([^']+)'", query)
                if match:
                    feature_id = match.group(1)
            if feature_id:
                matches = [t for t in self._tasks.values() if t['feature_id'] == feature_id]
                # Handle "as cost" alias
                if "as cost" in query_lower:
                    return MockCursor([{'cost': m.get('cost_eur', 0)} for m in matches])
                return MockCursor(matches)

        if "sum(cost_eur)" in query_lower or "coalesce(sum" in query_lower:
            total = sum(t.get('cost_eur', 0) for t in self._tasks.values())
            return MockCursor([{'total': total}])

        return MockCursor(list(self._tasks.values()))

    def _handle_update(self, query, params):
        query_lower = query.lower()
        task_id = None
        feature_id = None

        # Find task_id or feature_id from params
        if params:
            for p in reversed(params):
                if isinstance(p, int):
                    task_id = p
                    break
                elif isinstance(p, str) and p.startswith(('FAL-', 'API-', 'REVIEW-', 'TEST-')):
                    feature_id = p

        # Find task by feature_id if no task_id
        if feature_id and not task_id:
            for tid, t in self._tasks.items():
                if t['feature_id'] == feature_id:
                    task_id = tid
                    break

        if task_id and task_id in self._tasks:
            if "status =" in query_lower:
                if "in_progress" in query_lower:
                    self._tasks[task_id]['status'] = 'in_progress'
                    self._tasks[task_id]['started_at'] = 'NOW()'
                elif "completed" in query_lower:
                    self._tasks[task_id]['status'] = 'completed'
                    self._tasks[task_id]['completed_at'] = 'NOW()'
                    # cost_eur might be in params
                    for p in params:
                        if isinstance(p, (int, float)) and p != task_id:
                            self._tasks[task_id]['cost_eur'] = float(p)
                            break
                elif "failed" in query_lower:
                    self._tasks[task_id]['status'] = 'failed'
                    self._tasks[task_id]['completed_at'] = 'NOW()'
                    # error message might be in params
                    for p in params:
                        if isinstance(p, str):
                            self._tasks[task_id]['error'] = p
                            break
                elif "cancelled" in query_lower:
                    self._tasks[task_id]['status'] = 'cancelled'
                    self._tasks[task_id]['completed_at'] = 'NOW()'

            if "cost_eur" in query_lower and "status" not in query_lower:
                amount = params[0] if len(params) > 0 else 0
                self._tasks[task_id]['cost_eur'] += float(amount)

            if "current_agent" in query_lower:
                for p in params:
                    if isinstance(p, str) and p != 'in_progress':
                        self._tasks[task_id]['current_agent'] = p
                        break

        return MockCursor([])

    def commit(self):
        pass

    def add_task(self, feature_id, status='pending', cost_eur=0.0, source='test'):
        """Helper to add test tasks directly."""
        task = {
            'id': self._id_counter,
            'feature_id': feature_id,
            'source': source,
            'status': status,
            'cost_eur': cost_eur,
            'current_agent': None,
            'started_at': None,
            'completed_at': None,
            'error': None,
            'created_at': 'NOW()',
        }
        self._tasks[self._id_counter] = task
        self._id_counter += 1
        return task

    def get_task(self, task_id):
        """Get task by ID."""
        return self._tasks.get(task_id)


@pytest.fixture(scope="function")
def test_db(db_url):
    """Fresh database connection with transaction rollback after each test.

    Falls back to InMemoryDB if no database is available.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(db_url, row_factory=dict_row, connect_timeout=2)

        # Start transaction
        conn.execute("BEGIN")

        # Clean tables
        conn.execute("DELETE FROM pipeline_metrics")
        conn.execute("DELETE FROM agency_events")
        conn.execute("DELETE FROM agency_tasks")
        conn.execute("DELETE FROM agency_metrics_hourly")
        conn.execute("DELETE FROM agency_live_snapshot")

        yield conn

        # Rollback after test
        conn.execute("ROLLBACK")
        conn.close()
    except Exception:
        # Fall back to in-memory DB for unit tests
        yield InMemoryDB()


@pytest.fixture(scope="function")
def mock_db():
    """Always returns a mock database for pure unit tests."""
    return MockDB()


@pytest.fixture(scope="function")
def api_client():
    """FastAPI test client for API tests."""
    from fastapi.testclient import TestClient
    from orchestrator.api import app
    return TestClient(app)


@pytest.fixture(scope="function")
def api_secret():
    """Get the API secret from the loaded module."""
    from orchestrator.api import API_SECRET
    return API_SECRET
