"""Agent Designer - automatic pipeline configuration for new repos."""

from .conversation import ConversationManager, Session, SessionState
from .detector import StackDetectionResult, StackDetector
from .generator import AgentGenerator
from .repo_manager import RepoManager

__all__ = [
    "AgentGenerator",
    "ConversationManager",
    "RepoManager",
    "Session",
    "SessionState",
    "StackDetector",
    "StackDetectionResult",
]
