"""Security tests for critical vulnerabilities."""
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


class TestApiSecretValidation:
    """API_SECRET must not have a default value in production."""

    def test_api_fails_without_secret_env_var(self):
        """Should raise error if AGENCY_API_SECRET env var is not set."""
        import importlib
        import sys

        # Save original module state
        original_api_secret = os.environ.get('AGENCY_API_SECRET')
        api_module_name = 'orchestrator.api'

        # Remove the module from cache to force fresh import
        if api_module_name in sys.modules:
            saved_module = sys.modules.pop(api_module_name)
        else:
            saved_module = None

        try:
            # Clear env var
            if 'AGENCY_API_SECRET' in os.environ:
                del os.environ['AGENCY_API_SECRET']

            # Importing should fail
            with pytest.raises(ValueError, match="AGENCY_API_SECRET"):
                import orchestrator.api
        finally:
            # Restore original state
            if original_api_secret is not None:
                os.environ['AGENCY_API_SECRET'] = original_api_secret

            # Restore the cached module
            if saved_module is not None:
                sys.modules[api_module_name] = saved_module


class TestFeatureIdValidation:
    """feature_id must be validated to prevent path traversal."""

    def _make_request(self, tmp_path, feature_id):
        """Helper to make a test request with fresh client."""
        from orchestrator.api import app, API_SECRET
        client = TestClient(app)
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.commit = MagicMock()

        with patch('orchestrator.api.get_db', return_value=mock_db):
            with patch('orchestrator.api.PIPELINE_DIR', tmp_path):
                return client.post(
                    "/api/tasks",
                    json={"title": "Test", "feature_id": feature_id},
                    headers={"X-Agency-Secret": API_SECRET}
                )

    def test_rejects_path_traversal_in_feature_id(self, tmp_path):
        """Should reject feature_id containing path traversal."""
        response = self._make_request(tmp_path, "../../../etc/passwd")
        assert response.status_code == 422  # Pydantic validation error

    def test_rejects_absolute_path_in_feature_id(self, tmp_path):
        """Should reject feature_id starting with /."""
        response = self._make_request(tmp_path, "/etc/passwd")
        assert response.status_code == 422  # Pydantic validation error

    def test_rejects_null_bytes_in_feature_id(self, tmp_path):
        """Should reject feature_id containing null bytes."""
        response = self._make_request(tmp_path, "FAL-001\x00.txt")
        assert response.status_code == 422  # Pydantic validation error

    def test_accepts_valid_feature_id(self, tmp_path):
        """Should accept valid feature_id patterns."""
        response = self._make_request(tmp_path, "FAL-123")
        assert response.status_code == 201

    def test_accepts_feature_id_with_underscores(self, tmp_path):
        """Should accept feature_id with underscores and dashes."""
        response = self._make_request(tmp_path, "API_TASK-2024-001")
        assert response.status_code == 201


class TestShellInjectionPrevention:
    """Input content must be properly escaped for shell commands."""

    def test_input_content_is_shell_escaped(self, tmp_path):
        """Should use shlex.quote for input content in shell commands."""
        import shlex
        from pathlib import Path
        from unittest.mock import MagicMock, patch, call

        # Create mock DB
        mock_db = MagicMock()

        # Patch subprocess.run to capture the command
        captured_commands = []
        def capture_run(cmd, **kwargs):
            captured_commands.append(cmd)
            return MagicMock(returncode=0)

        with patch('orchestrator.main.subprocess.run', side_effect=capture_run):
            from orchestrator.main import Orchestrator

            orch = Orchestrator(
                db=mock_db,
                pipeline_dir=tmp_path / "pipeline",
                worktree_dir=tmp_path / "worktrees",
            )

            # Create malicious input file
            feature_dir = tmp_path / "pipeline" / "EVIL-001"
            feature_dir.mkdir(parents=True)
            input_file = feature_dir / "input.md"

            # This content would execute arbitrary commands if not escaped
            malicious_content = "'; rm -rf / #"
            input_file.write_text(malicious_content)

            # Start agent session
            orch.start_agent_session(
                agent="test_agent",
                feature_id="EVIL-001",
                task_id=1,
            )

        # Verify command was captured
        assert len(captured_commands) > 0

        # The tmux command includes the shell command as last argument
        tmux_cmd = captured_commands[0]
        shell_cmd = tmux_cmd[-1]  # Last argument is the shell command

        # The malicious content should be properly escaped
        # shlex.quote would turn '; rm -rf / #' into ''\'' rm -rf / #'\'''
        # or similar safe form - the key is that semicolon should not break out
        assert "rm -rf" not in shell_cmd or shlex.quote(malicious_content) in shell_cmd

    def test_backtick_injection_prevented(self, tmp_path):
        """Should prevent backtick command substitution."""
        from unittest.mock import MagicMock, patch

        mock_db = MagicMock()
        captured_commands = []

        def capture_run(cmd, **kwargs):
            captured_commands.append(cmd)
            return MagicMock(returncode=0)

        with patch('orchestrator.main.subprocess.run', side_effect=capture_run):
            from orchestrator.main import Orchestrator

            orch = Orchestrator(
                db=mock_db,
                pipeline_dir=tmp_path / "pipeline",
                worktree_dir=tmp_path / "worktrees",
            )

            feature_dir = tmp_path / "pipeline" / "EVIL-002"
            feature_dir.mkdir(parents=True)
            input_file = feature_dir / "input.md"
            input_file.write_text("`whoami`")

            orch.start_agent_session(
                agent="test_agent",
                feature_id="EVIL-002",
                task_id=2,
            )

        assert len(captured_commands) > 0
        shell_cmd = captured_commands[0][-1]

        # Backticks should be escaped or quoted
        # The raw backtick should not appear unescaped
        assert "`whoami`" not in shell_cmd or "'" in shell_cmd

    def test_dollar_paren_injection_prevented(self, tmp_path):
        """Should prevent $(command) substitution."""
        from unittest.mock import MagicMock, patch

        mock_db = MagicMock()
        captured_commands = []

        def capture_run(cmd, **kwargs):
            captured_commands.append(cmd)
            return MagicMock(returncode=0)

        with patch('orchestrator.main.subprocess.run', side_effect=capture_run):
            from orchestrator.main import Orchestrator

            orch = Orchestrator(
                db=mock_db,
                pipeline_dir=tmp_path / "pipeline",
                worktree_dir=tmp_path / "worktrees",
            )

            feature_dir = tmp_path / "pipeline" / "EVIL-003"
            feature_dir.mkdir(parents=True)
            input_file = feature_dir / "input.md"
            input_file.write_text("$(cat /etc/passwd)")

            orch.start_agent_session(
                agent="test_agent",
                feature_id="EVIL-003",
                task_id=3,
            )

        assert len(captured_commands) > 0
        shell_cmd = captured_commands[0][-1]

        # $() should be escaped
        assert "$(cat" not in shell_cmd or "'" in shell_cmd
