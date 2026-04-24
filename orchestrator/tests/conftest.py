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

    def execute(self, query, params=None):
        self._queries.append((query, params))
        return MockCursor(self._results.get(query.strip()[:50], []))

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


@pytest.fixture(scope="function")
def test_db(db_url):
    """Fresh database connection with transaction rollback after each test.

    Falls back to MockDB if no database is available.
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
        # Fall back to mock DB for unit tests
        yield MockDB()


@pytest.fixture(scope="function")
def mock_db():
    """Always returns a mock database for pure unit tests."""
    return MockDB()
