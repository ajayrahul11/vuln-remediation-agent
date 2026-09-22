"""Bump a pinned requirement in requirements.txt / pyproject.toml."""

from __future__ import annotations

import re

_PIN = re.compile(r"(?P<pre>^|[\"'\s])(?P<name>[A-Za-z0-9_.-]+)(?P<extras>\[[^\]]*\])?==[\w.+!-]+", re.M)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def bump_pin(text: str, package: str, fixed: str) -> str | None:
    """Replace `package==old` with `package==fixed`. None if no pin matched."""
    changed = False

    def sub(m: re.Match[str]) -> str:
        nonlocal changed
        if _norm(m["name"]) != _norm(package):
            return m[0]
        changed = True
        return f"{m['pre']}{m['name']}{m['extras'] or ''}=={fixed}"

    out = _PIN.sub(sub, text)
    return out if changed else None
