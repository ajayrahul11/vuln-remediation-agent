"""Fetch the JIRA issue and turn one row of its description table into a Finding.

The description holds a two-column table: repo, and a link to the CVE. A ticket
may list several rows; `state["row_index"]` picks which one this run handles
(graph/runner.run_for_jira_issue starts one run per row). The package and
versions are NOT known here -- prepare resolves them from the CVE link once the
repo is cloned.

An unreadable description or a bad row escalates. A ticket we cannot parse is
not a ticket we can safely fix.

The Finding is persisted as a finding_snapshot; the decision_log row is written
by graph/builder.audited around every node.
"""

from __future__ import annotations

from vulnagent.adapters.jira import JiraClient
from vulnagent.adapters.jira.description import TicketParseError, parse_description_table
from vulnagent.config import get_settings
from vulnagent.cve import extract_cve_id
from vulnagent.domain import Finding
from vulnagent.graph.state import RemediationState
from vulnagent.persistence.audit import record_finding


async def run(state: RemediationState) -> dict:
    settings = get_settings()
    key = state["jira_key"]
    idx = state.get("row_index", 0)

    issue = await JiraClient().get_issue(key)
    fields = issue.get("fields", {})
    try:
        rows = parse_description_table(
            fields.get("description"), default_org=settings.github_default_org
        )
        row = rows[idx]
    except (TicketParseError, IndexError) as exc:
        reason = str(exc) or f"row {idx} does not exist"
        return {
            "terminal_status": "escalated",
            "escalation_reason": f"cannot parse {key} description: {reason}",
            "decisions": [{"node": "ingest", "outcome": "escalated", "reason": reason}],
        }

    base = settings.jira_base_url.rstrip("/")
    finding = Finding(
        jira_key=key,
        jira_url=f"{base}/browse/{key}" if base else None,
        repo_full_name=row.repo_full_name,
        cve_url=row.cve_url,
        cve_id=extract_cve_id(row.cve_url),
        raw_description=fields.get("summary") or "",
    )
    if run_id := state.get("run_id"):
        await record_finding(run_id, finding, row_index=idx)
    return {
        "finding": finding,
        "decisions": [
            {"node": "ingest", "outcome": "ok", "repo": row.repo_full_name, "cve_url": row.cve_url}
        ],
    }
