"""Stack detection for repositories."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DETECTION_PRIORITY = [
    "shopify-app",
    "shopware-plugin",
    "react-vite",
    "fastapi",
]

STACK_SIGNATURES = {
    "shopify-app": {
        "required": ["shopify.app.toml"],
        "optional": ["package.json"],
        "package_markers": ["@shopify/shopify-app-remix", "@shopify/polaris"],
        "description": "Shopify App (React Router + Prisma + Polaris)",
    },
    "shopware-plugin": {
        "required": ["composer.json"],
        "composer_markers": ["shopware/core"],
        "optional_dirs": ["src/Resources/app/administration"],
        "description": "Shopware Plugin (PHP + Guzzle + Vue)",
    },
    "react-vite": {
        "required": ["package.json"],
        "optional": ["vite.config.ts", "vite.config.js"],
        "package_markers": ["react", "vite"],
        "description": "React + Vite + TypeScript",
    },
    "fastapi": {
        "required": ["pyproject.toml"],
        "pyproject_markers": ["fastapi"],
        "description": "FastAPI + Python",
    },
}

DEFAULT_COMMANDS = {
    "shopify-app": {
        "test": "npm test",
        "build": "npm run build",
        "lint": "npm run lint",
    },
    "shopware-plugin": {
        "test": "./vendor/bin/phpunit",
        "build": "npm --prefix src/Resources/app/administration run build",
        "lint": "./vendor/bin/phpstan analyse",
    },
    "react-vite": {
        "test": "npm test",
        "build": "npm run build",
        "lint": "npm run lint",
    },
    "fastapi": {
        "test": "pytest",
        "build": "echo 'No build step'",
        "lint": "ruff check .",
    },
}


@dataclass
class StackDetectionResult:
    stack: Optional[str] = None
    confidence: float = 0.0
    detected_files: list = field(default_factory=list)
    suggested_commands: dict = field(default_factory=dict)
    description: str = ""
    questions: list = field(default_factory=list)


class StackDetector:
    """Detects project stack from repository files."""

    def detect(self, repo_path: Path) -> StackDetectionResult:
        """Detect stack type from repository."""
        for stack_name in DETECTION_PRIORITY:
            signature = STACK_SIGNATURES[stack_name]
            result = self._check_stack(repo_path, stack_name, signature)
            if result.stack:
                return result

        return StackDetectionResult(
            stack=None,
            confidence=0.0,
            questions=["Stack nicht erkannt. Unterstützt: FastAPI, React, Shopify, Shopware"],
        )

    def _check_stack(
        self, repo_path: Path, stack_name: str, signature: dict
    ) -> StackDetectionResult:
        """Check if repo matches a specific stack signature."""
        detected_files = []
        confidence = 0.0

        # Check required files - any missing required file disqualifies the stack
        for required in signature.get("required", []):
            if (repo_path / required).exists():
                detected_files.append(required)
                confidence += 0.3
            else:
                return StackDetectionResult()

        # Check optional files
        for optional in signature.get("optional", []):
            if (repo_path / optional).exists():
                detected_files.append(optional)
                confidence += 0.1

        # Check optional directories
        for optional_dir in signature.get("optional_dirs", []):
            if (repo_path / optional_dir).is_dir():
                detected_files.append(optional_dir)
                confidence += 0.1

        # Check package.json markers
        if "package_markers" in signature:
            package_json = repo_path / "package.json"
            if package_json.exists():
                try:
                    data = json.loads(package_json.read_text())
                    deps = {
                        **data.get("dependencies", {}),
                        **data.get("devDependencies", {}),
                    }
                    for marker in signature["package_markers"]:
                        if marker in deps:
                            confidence += 0.2
                except (json.JSONDecodeError, IOError):
                    pass

        # Check composer.json markers
        if "composer_markers" in signature:
            composer_json = repo_path / "composer.json"
            if composer_json.exists():
                try:
                    data = json.loads(composer_json.read_text())
                    deps = {
                        **data.get("require", {}),
                        **data.get("require-dev", {}),
                    }
                    for marker in signature["composer_markers"]:
                        if marker in deps:
                            confidence += 0.3
                except (json.JSONDecodeError, IOError):
                    pass

        # Check pyproject.toml markers
        if "pyproject_markers" in signature:
            pyproject = repo_path / "pyproject.toml"
            if pyproject.exists():
                content = pyproject.read_text().lower()
                for marker in signature["pyproject_markers"]:
                    if marker.lower() in content:
                        confidence += 0.3

        if confidence > 0:
            suggested = self._detect_commands(repo_path, stack_name)
            return StackDetectionResult(
                stack=stack_name,
                confidence=min(confidence, 1.0),
                detected_files=detected_files,
                suggested_commands=suggested,
                description=signature.get("description", stack_name),
            )

        return StackDetectionResult()

    def _detect_commands(self, repo_path: Path, stack_name: str) -> dict:
        """Try to detect actual commands from project files."""
        defaults = DEFAULT_COMMANDS.get(stack_name, {}).copy()

        package_json = repo_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                scripts = data.get("scripts", {})
                if "test" in scripts:
                    defaults["test"] = "npm test"
                if "build" in scripts:
                    defaults["build"] = "npm run build"
                if "lint" in scripts:
                    defaults["lint"] = "npm run lint"
            except (json.JSONDecodeError, IOError):
                pass

        return defaults
