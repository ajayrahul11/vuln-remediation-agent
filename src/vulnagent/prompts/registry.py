"""Prompts live on disk as versioned Markdown, never inline in Python.

Why this matters at enterprise scale:
  * a prompt change is a reviewable diff with a CODEOWNER, not a buried string
  * every render records prompt_id + sha256, so an audit trail can answer
    "which exact instructions produced this patch nine months ago"
  * the eval harness can pin a prompt version and A/B it in CI

Format: YAML frontmatter + body. Body uses str.format-style {placeholders}.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PACKAGED_ROOT = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    version: str
    model_hint: str | None
    temperature: float
    description: str
    body: str
    path: Path

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body.encode()).hexdigest()[:16]

    def render(self, **kwargs: Any) -> str:
        try:
            return self.body.format(**kwargs)
        except KeyError as exc:  # fail loudly: a missing var is a silent bug
            raise ValueError(f"prompt {self.prompt_id} missing variable {exc}") from exc

    def audit_ref(self) -> dict[str, str]:
        return {"prompt_id": self.prompt_id, "version": self.version, "sha256": self.sha256}


def _parse(path: Path) -> Prompt:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    _, fm_raw, body = text.split("---", 2)
    fm = yaml.safe_load(fm_raw) or {}
    rel = path.relative_to(_PACKAGED_ROOT).with_suffix("")
    return Prompt(
        prompt_id=str(rel).replace("/", "."),
        version=str(fm.get("version", "0")),
        model_hint=fm.get("model"),
        temperature=float(fm.get("temperature", 0.0)),
        description=fm.get("description", ""),
        body=body.strip(),
        path=path,
    )


class PromptRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _PACKAGED_ROOT
        self._cache: dict[str, Prompt] = {}

    def get(self, prompt_id: str) -> Prompt:
        if prompt_id not in self._cache:
            path = self.root / (prompt_id.replace(".", "/") + ".md")
            if not path.exists():
                raise FileNotFoundError(f"no prompt {prompt_id} at {path}")
            self._cache[prompt_id] = _parse(path)
        return self._cache[prompt_id]

    def all(self) -> list[Prompt]:
        return [_parse(p) for p in sorted(self.root.rglob("*.md"))]


@lru_cache
def _registry() -> PromptRegistry:
    from vulnagent.config import get_settings

    return PromptRegistry(get_settings().prompts_dir)


def get_prompt(prompt_id: str) -> Prompt:
    return _registry().get(prompt_id)
