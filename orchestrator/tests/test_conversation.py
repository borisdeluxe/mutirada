"""Tests for ConversationManager state machine."""
import pytest
from orchestrator.agent_designer.conversation import ConversationManager, SessionState


def test_start_session_returns_session():
    cm = ConversationManager(db=None)
    session = cm.start("https://github.com/test/repo", "channel123", "user456", "slack")

    assert session is not None
    assert session.user_id == "user456"
    assert session.chat_id == "channel123"
    assert session.state in [SessionState.DETECTING, SessionState.ERROR]


def test_session_requires_user_id():
    cm = ConversationManager(db=None)
    cm.start("https://github.com/test/repo", "channel123", "user456", "slack")
    session = cm.get_active_session("channel123", "user789")

    assert session is None


def test_cancel_session():
    cm = ConversationManager(db=None)
    cm.start("https://github.com/test/repo", "channel123", "user456", "slack")

    result = cm.cancel("channel123", "user456")
    assert result is True

    session = cm.get_active_session("channel123", "user456")
    assert session is None or session.state == SessionState.CANCELLED
