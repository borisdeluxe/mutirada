"""Agent Designer - automatic pipeline configuration for new repos."""

from .detector import StackDetectionResult, StackDetector
from .repo_manager import RepoManager

__all__ = [
    "RepoManager",
    "StackDetector",
    "StackDetectionResult",
]
