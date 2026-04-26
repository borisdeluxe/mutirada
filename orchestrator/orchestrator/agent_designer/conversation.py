"""Conversation state machine for agent designer."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any

from .detector import StackDetector
from .generator import AgentGenerator
from .repo_manager import RepoManager


class SessionState(str, Enum):
    INIT = "INIT"
    DETECTING = "DETECTING"
    ASKING_COMMANDS = "ASKING_COMMANDS"
    ASKING_CONFIRM = "ASKING_CONFIRM"
    ASKING_OVERWRITE = "ASKING_OVERWRITE"
    CLONING = "CLONING"
    GENERATING = "GENERATING"
    REGISTERING = "REGISTERING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


@dataclass
class Session:
    session_id: str
    chat_id: str
    user_id: str
    source: str
    repo_url: str
    state: SessionState
    stack: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def is_active(self) -> bool:
        return self.state not in (
            SessionState.COMPLETE,
            SessionState.ERROR,
            SessionState.CANCELLED,
        )


class ConversationManager:
    """Manages conversation sessions for agent designer."""

    MAX_SESSIONS_PER_USER = 3
    SESSION_TIMEOUT_MINUTES = 30

    def __init__(self, db=None, repos_dir=None):
        self.db = db
        self.detector = StackDetector()
        self.generator = AgentGenerator()
        self.repo_manager = RepoManager(repos_dir)
        self._sessions: Dict[str, Session] = {}

    def start(self, repo_url: str, chat_id: str, user_id: str, source: str) -> Session:
        """Start a new configuration session."""
        active_count = self._count_active_sessions(user_id)
        if active_count >= self.MAX_SESSIONS_PER_USER:
            return Session(
                session_id="",
                chat_id=chat_id,
                user_id=user_id,
                source=source,
                repo_url=repo_url,
                state=SessionState.ERROR,
                data={"error": f"Max {self.MAX_SESSIONS_PER_USER} active sessions. Use /cancel."},
            )

        if not self.repo_manager.validate_url(repo_url):
            return Session(
                session_id="",
                chat_id=chat_id,
                user_id=user_id,
                source=source,
                repo_url=repo_url,
                state=SessionState.ERROR,
                data={"error": "Invalid URL. Allowed: github.com, gitlab.com, bitbucket.org"},
            )

        session_id = str(uuid.uuid4())[:8]
        session = Session(
            session_id=session_id,
            chat_id=chat_id,
            user_id=user_id,
            source=source,
            repo_url=repo_url,
            state=SessionState.DETECTING,
        )

        self._sessions[session_id] = session
        self._save_session(session)

        return session

    def get_active_session(self, chat_id: str, user_id: str) -> Optional[Session]:
        """Get active session for user in channel."""
        for session in self._sessions.values():
            if (
                session.chat_id == chat_id
                and session.user_id == user_id
                and session.is_active
            ):
                if datetime.now() - session.updated_at > timedelta(
                    minutes=self.SESSION_TIMEOUT_MINUTES
                ):
                    session.state = SessionState.ERROR
                    session.data["error"] = "Session expired. Start over with /configure."
                    self._save_session(session)
                    return None
                return session
        return None

    def cancel(self, chat_id: str, user_id: str) -> bool:
        """Cancel active session for user."""
        session = self.get_active_session(chat_id, user_id)
        if session:
            session.state = SessionState.CANCELLED
            session.updated_at = datetime.now()
            self._save_session(session)
            return True
        return False

    def handle_answer(self, chat_id: str, user_id: str, answer: str) -> Optional[Session]:
        """Handle user answer in conversation."""
        session = self.get_active_session(chat_id, user_id)
        if not session:
            return None
        session.updated_at = datetime.now()

        if session.state == SessionState.ASKING_COMMANDS:
            return self._handle_command_answer(session, answer)
        elif session.state == SessionState.ASKING_CONFIRM:
            return self._handle_confirm_answer(session, answer)
        elif session.state == SessionState.ASKING_OVERWRITE:
            return self._handle_overwrite_answer(session, answer)

        return session

    def _handle_command_answer(self, session: Session, answer: str) -> Session:
        current_question = session.data.get("current_question", "test")
        if answer.lower() != "skip":
            session.data[f"{current_question}_command"] = answer

        questions = ["test", "build", "lint"]
        current_idx = questions.index(current_question) if current_question in questions else 0

        if current_idx < len(questions) - 1:
            session.data["current_question"] = questions[current_idx + 1]
        else:
            session.state = SessionState.ASKING_CONFIRM

        self._save_session(session)
        return session

    def _handle_confirm_answer(self, session: Session, answer: str) -> Session:
        if answer.lower() in ("ja", "yes", "y", "ok"):
            return self._execute_configuration(session)
        else:
            session.state = SessionState.CANCELLED
            self._save_session(session)
        return session

    def _handle_overwrite_answer(self, session: Session, answer: str) -> Session:
        if answer.lower() in ("ja", "yes", "y"):
            session.data["overwrite"] = True
            return self._execute_configuration(session)
        else:
            session.state = SessionState.CANCELLED
            self._save_session(session)
        return session

    def _execute_configuration(self, session: Session) -> Session:
        session.state = SessionState.CLONING
        self._save_session(session)

        result = self.repo_manager.clone(session.repo_url)
        if not result.success:
            session.state = SessionState.ERROR
            session.data["error"] = result.error
            self._save_session(session)
            return session

        repo_path = result.path

        if self.repo_manager.check_existing_agents(repo_path) and not session.data.get("overwrite"):
            session.state = SessionState.ASKING_OVERWRITE
            self._save_session(session)
            return session

        session.state = SessionState.GENERATING
        self._save_session(session)

        commands = {
            "test_command": session.data.get("test_command", ""),
            "build_command": session.data.get("build_command", ""),
            "lint_command": session.data.get("lint_command", ""),
        }

        agents = self.generator.generate(session.stack, commands)
        self.repo_manager.write_agents(repo_path, agents)

        session.state = SessionState.REGISTERING
        self._save_session(session)

        repo_name = self.repo_manager.extract_name(session.repo_url)

        session.state = SessionState.COMPLETE
        session.data["repo_name"] = repo_name
        session.data["repo_path"] = str(repo_path)
        session.data["agents_count"] = len(agents)
        self._save_session(session)

        return session

    def _count_active_sessions(self, user_id: str) -> int:
        return sum(1 for s in self._sessions.values() if s.user_id == user_id and s.is_active)

    def _save_session(self, session: Session) -> None:
        self._sessions[session.session_id] = session
        # DB persistence would happen here when self.db is set
