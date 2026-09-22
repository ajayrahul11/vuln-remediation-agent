"""Resolve build/test commands for a repo.

Not a security concept: a JIRA ticket never carries "how do I build this repo,"
so this is the one piece of operational metadata the system still needs from
somewhere other than the ticket.

Resolution order:
  1. config/catalog.yaml override, if the repo is listed there
  2. auto-detect from the manifest file actually present in the clone

Auto-detect covers the common single-manifest case. Multi-module repos,
monorepos, or non-standard test commands need an explicit catalog entry --
that's what the override is for. Fail closed: an unrecognised repo layout
escalates rather than guessing a build command.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from vulnagent.domain import Ecosystem, RepoConfig

_MANIFEST_MARKERS: dict[Ecosystem, tuple[str, ...]] = {
    Ecosystem.MAVEN: ("pom.xml",),
    Ecosystem.NPM: ("package.json",),
    Ecosystem.PYPI: ("pyproject.toml", "requirements.txt", "setup.py"),
    Ecosystem.GO: ("go.mod",),
}

_DEFAULT_COMMANDS: dict[Ecosystem, tuple[str, str]] = {
    Ecosystem.MAVEN: ("mvn -B -ntp clean verify -DskipTests", "mvn -B -ntp test"),
    Ecosystem.NPM: ("npm ci", "npm test -- --ci"),
    Ecosystem.PYPI: ("pip install -e .", "pytest -q"),
    Ecosystem.GO: ("go build ./...", "go test -v ./..."),
}


def detect_ecosystem(workdir: Path) -> Ecosystem | None:
    """First ecosystem whose marker file is at the repo root."""
    for eco, markers in _MANIFEST_MARKERS.items():
        if any((workdir / m).is_file() for m in markers):
            return eco
    return None


def _default_branch(workdir: Path) -> str:
    head = workdir / ".git" / "HEAD"
    try:
        text = head.read_text().strip()
    except OSError:
        return "main"
    return text.removeprefix("ref: refs/heads/") if text.startswith("ref: ") else "main"


class RepoConfigResolver:
    def __init__(self, overrides: dict[str, dict] | None = None) -> None:
        self._overrides = overrides or {}

    @classmethod
    def load(cls, path: Path | None = None) -> RepoConfigResolver:
        """Parse config/catalog.yaml if it exists; a missing file means every repo
        uses auto-detection."""
        from vulnagent.config import get_settings

        path = path or get_settings().catalog_path
        if not path.is_file():
            return cls()
        data = yaml.safe_load(path.read_text()) or {}
        repos = data.get("repos", data)
        if isinstance(repos, list):
            repos = {r["repo_full_name"]: r for r in repos}
        return cls({k: dict(v) for k, v in repos.items()})

    def resolve(self, repo_full_name: str, workdir: Path) -> RepoConfig | None:
        """Override first, else detect_ecosystem() + defaults. None -- never a guess --
        when neither source yields an ecosystem."""
        override = self._overrides.get(repo_full_name, {})
        eco = Ecosystem(override["ecosystem"]) if "ecosystem" in override else None
        eco = eco or detect_ecosystem(workdir)
        if eco is None:
            return None
        build, test = _DEFAULT_COMMANDS[eco]
        return RepoConfig(
            repo_full_name=repo_full_name,
            default_branch=override.get("default_branch") or _default_branch(workdir),
            ecosystem=eco,
            build_command=override.get("build_command", build),
            test_command=override.get("test_command", test),
            codeowners=override.get("codeowners", []),
            sandbox_image=override.get("sandbox_image"),
        )
