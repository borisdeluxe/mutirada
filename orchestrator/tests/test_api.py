"""Tests for task submission API."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from orchestrator.api import app, API_SECRET


class TestTaskSubmitEndpoint:
    """POST /api/tasks should create tasks."""

    def test_submit_creates_task(self, client, mock_db, tmp_path):
        """Should insert task and return feature_id."""
        with patch('orchestrator.api.get_db', return_value=mock_db):
            with patch('orchestrator.api.PIPELINE_DIR', tmp_path):
                response = client.post(
                    "/api/tasks",
                    json={"title": "Add rate limiting", "body": "Max 100 req/min"},
                    headers={"X-Agency-Secret": API_SECRET}
                )

        assert response.status_code == 201
        data = response.json()
        assert "feature_id" in data
        assert data["status"] == "pending"

    def test_submit_without_secret_rejected(self, client):
        """Should reject requests without secret."""
        response = client.post(
            "/api/tasks",
            json={"title": "Test"}
        )

        assert response.status_code == 401

    def test_submit_with_wrong_secret_rejected(self, client):
        """Should reject requests with wrong secret."""
        response = client.post(
            "/api/tasks",
            json={"title": "Test"},
            headers={"X-Agency-Secret": "wrong-secret"}
        )

        assert response.status_code == 401

    def test_submit_with_custom_id(self, client, mock_db, tmp_path):
        """Should accept custom feature_id."""
        with patch('orchestrator.api.get_db', return_value=mock_db):
            with patch('orchestrator.api.PIPELINE_DIR', tmp_path):
                response = client.post(
                    "/api/tasks",
                    json={"title": "Test", "feature_id": "FAL-99"},
                    headers={"X-Agency-Secret": API_SECRET}
                )

        assert response.status_code == 201
        assert response.json()["feature_id"] == "FAL-99"

    def test_submit_writes_input_md(self, client, mock_db, tmp_path):
        """Should write input.md file."""
        with patch('orchestrator.api.get_db', return_value=mock_db):
            with patch('orchestrator.api.PIPELINE_DIR', tmp_path):
                response = client.post(
                    "/api/tasks",
                    json={"title": "Test", "body": "Description", "feature_id": "TEST-1"},
                    headers={"X-Agency-Secret": API_SECRET}
                )

        assert response.status_code == 201
        input_file = tmp_path / "TEST-1" / "input.md"
        assert input_file.exists()


class TestReviewEndpoint:
    """POST /api/review should create review tasks."""

    def test_review_path(self, client, mock_db, tmp_path):
        """Should create review task for path."""
        with patch('orchestrator.api.get_db', return_value=mock_db):
            with patch('orchestrator.api.PIPELINE_DIR', tmp_path):
                response = client.post(
                    "/api/review",
                    json={"target": "src/api/billing.py"},
                    headers={"X-Agency-Secret": API_SECRET}
                )

        assert response.status_code == 201
        assert "REVIEW-" in response.json()["feature_id"]

    def test_review_pr(self, client, mock_db, tmp_path):
        """Should create review task for PR."""
        with patch('orchestrator.api.get_db', return_value=mock_db):
            with patch('orchestrator.api.PIPELINE_DIR', tmp_path):
                response = client.post(
                    "/api/review",
                    json={"pr_number": 42},
                    headers={"X-Agency-Secret": API_SECRET}
                )

        assert response.status_code == 201


class TestStatusEndpoint:
    """GET /api/status should return pipeline state."""

    def test_status_returns_tasks(self, client):
        """Should return active tasks."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"feature_id": "FAL-47", "status": "in_progress", "current_agent": "implementer", "cost_eur": 1.5}
        ]
        mock_cursor.fetchone.return_value = {"total": 5.0}
        mock_conn.execute.return_value = mock_cursor

        with patch('orchestrator.api.get_db', return_value=mock_conn):
            response = client.get(
                "/api/status",
                headers={"X-Agency-Secret": API_SECRET}
            )

        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "budget" in data

    def test_status_without_secret_rejected(self, client):
        """Should reject without auth."""
        response = client.get("/api/status")
        assert response.status_code == 401


class TestHealthEndpoint:
    """GET /health should be public."""

    def test_health_no_auth_required(self, client):
        """Should not require auth."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)
