"""Agent Designer - automatic pipeline configuration for new repos."""

from .detector import StackDetectionResult, StackDetector
from .generator import AgentGenerator
from .repo_manager import RepoManager

__all__ = [
    "AgentGenerator",
    "RepoManager",
    "StackDetector",
    "StackDetectionResult",
]
