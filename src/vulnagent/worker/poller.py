"""The entry point. "Scan all the JIRA tasks" is literally this file.

Runs a JQL query, and for each result, atomically claims it (Postgres INSERT
on a UNIQUE jira_key column -- see persistence/audit.claim_ticket) and, only
if the claim succeeded, runs the graph. A ticket another instance already
claimed is skipped with no extra logic needed.

`poll_once()` is called by:
  - `vulnagent poll` (CLI) for a single pass -- what a cron job or a
    Kubernetes CronJob invokes on a schedule
  - `vulnagent poll --watch` for a local dev loop (poll, sleep, repeat)

There is no long-running worker process to deploy in this design. "poll" runs,
processes whatever it finds, and exits. That's simpler to operate than a
queue consumer, and it fits a pull-based system: nothing is waiting on you to
show up in under 100ms the way a webhook receiver would be.
"""

from __future__ import annotations

import uuid

from vulnagent.adapters.jira import JiraClient
from vulnagent.config import get_settings
from vulnagent.graph.runner import run_for_jira_issue
from vulnagent.logging import get_logger
from vulnagent.persistence.audit import claim_ticket, record_run

log = get_logger(__name__)


async def poll_once() -> int:
    """Returns the number of tickets this pass claimed and processed.

    Tickets are processed one at a time, each to completion (or to its own
    bounded retries), before the next -- see the concurrency note below.
    """
    settings = get_settings()
    if settings.kill_switch:
        log.warning("kill_switch_active", op="poll")
        return 0

    issues = await JiraClient().jql(settings.jira_poll_jql)
    processed = 0
    for issue in issues:
        jira_key = issue["key"]
        run_id = str(uuid.uuid4())
        if not await claim_ticket(jira_key, run_id):
            log.debug("already_claimed", jira_key=jira_key)
            continue
        processed += 1
        try:
            await run_for_jira_issue(jira_key, dry_run=settings.dry_run, run_id=run_id)
        except Exception:
            # One bad ticket must not stop the pass. The claim stays, so it is
            # not retried blindly; mark it failed for a human to look at.
            log.exception("run_failed", jira_key=jira_key, run_id=run_id)
            await record_run(run_id, status="failed", finished=True)
    return processed


# Concurrency: process tickets one at a time to start. If two tickets target
# the same repo, running them concurrently means two clones racing the same
# branch namespace. When you do add concurrency (asyncio.gather with a
# semaphore), key it so tickets for the same repo_full_name never run at the
# same time -- e.g. group by repo before dispatching, not just cap total
# in-flight count.
