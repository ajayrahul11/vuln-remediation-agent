"""Entry point used by the poller and the CLI."""

from __future__ import annotations

import uuid

from vulnagent.config import get_settings
from vulnagent.graph.builder import build_graph
from vulnagent.graph.checkpointer import postgres_checkpointer
from vulnagent.logging import bind_run, get_logger
from vulnagent.persistence.audit import record_run, start_run

log = get_logger(__name__)


async def run_for_jira_key(
    jira_key: str, *, dry_run: bool = True, row_index: int = 0, run_id: str | None = None
) -> dict:
    settings = get_settings()
    # Authoritative, not merged with the env default: the poller always passes
    # settings.dry_run explicitly (so VA_DRY_RUN still governs unattended runs),
    # and `vulnagent run --no-dry-run` must be able to override it for a manual
    # run -- `dry_run or settings.dry_run` used to make that impossible whenever
    # VA_DRY_RUN=true, which is the shipped default.
    settings.dry_run = dry_run
    if settings.kill_switch:
        log.warning("kill_switch_active", jira_key=jira_key)
        return {"terminal_status": "halted"}

    run_id = run_id or str(uuid.uuid4())  # the poller passes the run_id it claimed
    bind_run(run_id=run_id, jira_key=jira_key)

    async with postgres_checkpointer() as cp:
        graph = build_graph(checkpointer=cp)
        thread_id = f"{jira_key}:{row_index}:{run_id}"
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}
        initial = {
            "run_id": run_id,
            "jira_key": jira_key,
            "row_index": row_index,
            "attempt": 1,
            "max_attempts": settings.max_fix_attempts,
            "decisions": [],
            "errors": [],
        }
        result = await graph.ainvoke(initial, config=config)
    finished = result.get("terminal_status") is not None
    await record_run(
        run_id,
        status=result.get("terminal_status") or "running",
        attempt=result.get("attempt"),
        repo_full_name=result["finding"].repo_full_name if result.get("finding") else None,
        finished=finished,
    )
    return result


async def run_for_jira_issue(
    jira_key: str, *, dry_run: bool = True, run_id: str | None = None
) -> list[dict]:
    """One run per (repo, CVE) row in the ticket's description table, sequentially
    (two rows on the same repo must not race the same branch namespace)."""
    from vulnagent.adapters.jira import JiraClient
    from vulnagent.adapters.jira.description import TicketParseError, parse_description_table

    settings = get_settings()
    issue = await JiraClient().get_issue(jira_key)
    try:
        n = len(
            parse_description_table(
                issue.get("fields", {}).get("description"),
                default_org=settings.github_default_org,
            )
        )
    except TicketParseError:
        n = 1  # let ingest record the parse failure and escalate

    claimed = run_id is not None  # the poller already inserted this row via claim_ticket
    run_id = run_id or str(uuid.uuid4())  # rows share one run_id: one ticket, one claim
    if not claimed:
        await start_run(run_id, jira_key)  # e.g. `vulnagent run` -- nothing claimed this yet
    return [
        await run_for_jira_key(jira_key, dry_run=dry_run, row_index=i, run_id=run_id)
        for i in range(n)
    ]
