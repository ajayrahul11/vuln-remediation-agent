"""Immutable audit trail and the ticket claim (the dedup mechanism).

Every run must be able to answer, later: what finding, what model, which
prompt + sha, what diff, what validation result, when.

record_decision is called from every node (see graph/builder.audited),
including escalate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert

from vulnagent.domain import Finding
from vulnagent.persistence.db import get_session
from vulnagent.persistence.models import (
    AgentRun,
    AuditEvent,
    DecisionLog,
    FindingSnapshot,
)


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so pydantic models, enums, datetimes and paths
    all become plain JSONB-safe data."""

    def default(o: Any) -> Any:
        if isinstance(o, BaseModel):
            return o.model_dump(mode="json")
        return str(o)

    return json.loads(json.dumps(value, default=default))


async def record_decision(
    run_id: str,
    node: str,
    *,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    prompt_ref: dict[str, str] | None = None,
) -> None:
    """Append one row to decision_log, plus an audit_event for the same step."""
    inputs_j, outputs_j = _jsonable(inputs), _jsonable(outputs)
    input_hash = hashlib.sha256(
        json.dumps(inputs_j, sort_keys=True).encode()
    ).hexdigest()
    async with get_session() as s:
        s.add(
            DecisionLog(
                run_id=run_id,
                node=node,
                input_hash=input_hash,
                inputs=inputs_j,
                outputs=outputs_j,
                prompt_ref=prompt_ref,
            )
        )
        s.add(
            AuditEvent(
                run_id=run_id,
                event_type="decision",
                node=node,
                detail={"outcome": outputs_j.get("outcome"), "input_hash": input_hash},
            )
        )


async def record_event(
    run_id: str, event_type: str, detail: dict[str, Any], *, node: str | None = None
) -> None:
    """Append a free-standing audit event (guard hits, kill switch, ...)."""
    async with get_session() as s:
        s.add(AuditEvent(run_id=run_id, event_type=event_type, node=node, detail=_jsonable(detail)))


async def record_finding(run_id: str, finding: Finding, *, row_index: int = 0) -> None:
    """Store the Finding as ingested. Idempotent: a graph resume re-running
    ingest does not fail or overwrite the original snapshot."""
    stmt = (
        insert(FindingSnapshot)
        .values(
            run_id=run_id,
            row_index=row_index,
            package=finding.package,
            installed_version=finding.installed_version,
            fixed_version=finding.fixed_version,
            finding=finding.model_dump(mode="json"),
        )
        .on_conflict_do_nothing(index_elements=["run_id", "row_index"])
    )
    async with get_session() as s:
        await s.execute(stmt)


async def record_run(
    run_id: str,
    *,
    status: str,
    attempt: int | None = None,
    repo_full_name: str | None = None,
    finished: bool = False,
) -> bool:
    """Update the agent_run row. Returns False if the run was never claimed
    (e.g. started directly from the CLI), in which case nothing is written."""
    values: dict[str, Any] = {"status": status}
    if attempt is not None:
        values["attempt"] = attempt
    if repo_full_name is not None:
        values["repo_full_name"] = repo_full_name
    if finished:
        values["ended_at"] = datetime.now(UTC)
    async with get_session() as s:
        result = await s.execute(
            update(AgentRun).where(AgentRun.run_id == run_id).values(**values)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]


async def start_run(run_id: str, jira_key: str) -> None:
    """Ensure agent_run has a row for this run when nothing has claimed the
    ticket yet -- i.e. `vulnagent run <key>`, not the poller (which already
    inserted the row via claim_ticket before it ever calls the graph).

    Unlike claim_ticket, this reclaims: `vulnagent run` is documented as "one
    ticket by hand while developing" and is meant to be re-run against the same
    ticket, so a pre-existing row for this jira_key is overwritten rather than
    left to block the insert.
    """
    stmt = (
        insert(AgentRun)
        .values(run_id=run_id, jira_key=jira_key, status="running", attempt=1)
        .on_conflict_do_update(
            index_elements=["jira_key"],
            set_={
                "run_id": run_id,
                "status": "running",
                "attempt": 1,
                "started_at": func.now(),
                "ended_at": None,
            },
        )
    )
    async with get_session() as s:
        await s.execute(stmt)


async def claim_ticket(jira_key: str, run_id: str) -> bool:
    """INSERT ... ON CONFLICT (jira_key) DO NOTHING. True if this call claimed
    the ticket, False if another run already owns it. This one function is
    the entire dedup mechanism -- no Redis, no queue, just a UNIQUE constraint.
    """
    stmt = (
        insert(AgentRun)
        .values(run_id=run_id, jira_key=jira_key, status="running", attempt=1)
        .on_conflict_do_nothing(index_elements=["jira_key"])
        .returning(AgentRun.run_id)
    )
    async with get_session() as s:
        return (await s.execute(stmt)).scalar_one_or_none() is not None
