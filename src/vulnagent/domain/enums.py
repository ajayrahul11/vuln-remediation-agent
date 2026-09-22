from __future__ import annotations

from enum import StrEnum


class FindingStatus(StrEnum):
    RECEIVED = "received"
    PREPARED = "prepared"
    PATCHED = "patched"
    VALIDATED = "validated"
    PR_OPEN = "pr_open"
    DONE = "done"
    ESCALATED = "escalated"
    FAILED = "failed"


# The ecosystems the default scaffold knows how to bump. Add another by
# extending detect_ecosystem() in catalog/repo_config.py and the command
# table in graph/nodes/apply_fix.py -- both are one small edit.
Ecosystem = StrEnum("Ecosystem", {"MAVEN": "maven", "NPM": "npm", "PYPI": "pypi", "GO": "go"})
