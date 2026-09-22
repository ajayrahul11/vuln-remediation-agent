"""The canonical Finding.

The ticket only names WHERE (repo) and WHICH CVE (a link). The package,
installed version and fixed version are unknown at ingest and are filled in
by prepare, once the repo is cloned and the CVE link has been resolved
(see cve/resolver.py).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vulnagent.domain.enums import Ecosystem


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jira_key: str
    jira_url: str | None = None  # plain str: HttpUrl is not checkpoint-serialisable

    cve_url: str | None = None  # the link from the ticket's table
    cve_id: str | None = None
    severity: str | None = None  # kept for the PR/JIRA comment; not used to branch logic

    repo_full_name: str
    ecosystem: Ecosystem | None = None  # None => auto-detect in prepare
    # None until prepare resolves the CVE against the cloned repo.
    package: str | None = None
    installed_version: str | None = None
    fixed_version: str | None = None

    # Free text off the ticket. Quarantined -- never interpolated into a
    # prompt except through wrap_untrusted(). Used only for human-readable
    # context in the PR body / JIRA comment.
    raw_description: str = Field(default="", max_length=32_000)
    raw_payload: dict[str, Any] = Field(default_factory=dict, exclude=True)

    detected_at: datetime | None = None

    @property
    def dedupe_key(self) -> str:
        """Basis for the Postgres UNIQUE constraint that makes polling idempotent."""
        # One ticket carries many (repo, CVE) rows, so the row is part of the key.
        basis = f"{self.jira_key}|{self.repo_full_name}|{self.cve_url or ''}"
        return hashlib.sha256(basis.encode()).hexdigest()[:32]

    def prompt_facts(self) -> dict[str, Any]:
        """The only projection of a Finding allowed into a prompt. No raw_description."""
        return {
            "cve_id": self.cve_id,
            "severity": self.severity,
            "package": self.package,
            "installed_version": self.installed_version,
            "fixed_version": self.fixed_version,
            "ecosystem": self.ecosystem,
        }
