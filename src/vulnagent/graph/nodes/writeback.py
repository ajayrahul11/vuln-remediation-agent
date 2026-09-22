"""Close the loop in JIRA. Always runs, on the success, dry-run and escalate paths.

Comments (prompts/publish/jira_comment.md), then transitions the ticket:
settings.jira_transition_done after a PR is opened, jira_transition_escalated on
escalation. A dry run comments/transitions nothing (the client logs instead).
A transition that does not exist in this project's workflow is recorded in
state["errors"] rather than failing the run -- the PR is already open.

"Done" means: local build and tests passed and a PR is open for review. It does
not mean the CVE is confirmed closed; the comment says so plainly.
"""

from __future__ import annotations

from vulnagent.adapters.jira import JiraClient
from vulnagent.config import get_settings
from vulnagent.graph.state import RemediationState
from vulnagent.logging import get_logger
from vulnagent.prompts import get_prompt

log = get_logger(__name__)


def _status(flag: bool | None) -> str:
    return "n/a" if flag is None else ("passed" if flag else "failed")


async def run(state: RemediationState) -> dict:
    settings = get_settings()
    key = state["jira_key"]
    status = state.get("terminal_status", "unknown")
    finding = state.get("finding")
    report = state.get("validation")

    if status == "pr_open":
        outcome, evidence = f"Pull request opened: {state.get('pr_url')}", ""
    elif status == "dry_run":
        outcome, evidence = "Dry run: validation passed; no branch or PR was created.", ""
    else:
        outcome = "Could not fix automatically; needs a person."
        evidence = "{code}\n" + (state.get("escalation_reason") or "no reason recorded")[:3000] + "\n{code}"

    body = get_prompt("publish.jira_comment").render(
        run_id=state.get("run_id", "n/a"),
        terminal_status=status,
        outcome_line=outcome,
        package=getattr(finding, "package", None) or "n/a",
        installed_version=getattr(finding, "installed_version", None) or "n/a",
        fixed_version=getattr(finding, "fixed_version", None) or "n/a",
        build_status=_status(report.build_passed if report else None),
        test_status=_status(report.tests_passed if report else None),
        attempts=state.get("attempt", 1),
        evidence_block=evidence,
        trace_url="n/a",
    )

    jira = JiraClient()
    errors: list[str] = []
    try:
        await jira.add_comment(key, body)
        target = {
            "pr_open": settings.jira_transition_done,
            "escalated": settings.jira_transition_escalated,
        }.get(status)
        if target:
            await jira.transition(key, target)
    except Exception as exc:  # the run's real work is already done; report, don't crash
        log.warning("jira_writeback_failed", key=key, error=str(exc))
        errors.append(f"jira writeback: {exc}")
    return {"errors": errors, "decisions": [{"node": "writeback", "status": status}]}
