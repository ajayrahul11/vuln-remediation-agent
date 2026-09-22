from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from vulnagent.domain import Finding, FixTarget, PatchResult, RepoConfig, ValidationReport


class RemediationState(TypedDict, total=False):
    run_id: str
    jira_key: str
    row_index: int  # which (repo, CVE) row of the ticket's description table

    finding: Finding
    repo_config: RepoConfig
    fix_target: FixTarget

    workdir: str
    baseline_test_count: int  # tests before any change; the tests_not_deleted baseline
    patch: PatchResult
    validation: ValidationReport
    last_failure: str  # error text from the previous validate, read by apply_fix on retry

    attempt: int
    max_attempts: int

    decisions: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]

    terminal_status: str
    pr_url: str
    escalation_reason: str
