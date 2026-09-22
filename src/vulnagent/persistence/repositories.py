"""Thin read helpers over agent_run / finding_snapshot / decision_log for the
runs API (step 15)."""

from __future__ import annotations

from sqlalchemy import select

from vulnagent.persistence.db import get_session
from vulnagent.persistence.models import AgentRun, DecisionLog, FindingSnapshot


async def get_run(run_id: str) -> AgentRun | None:
    async with get_session() as s:
        return await s.get(AgentRun, run_id)


async def get_run_by_jira_key(jira_key: str) -> AgentRun | None:
    async with get_session() as s:
        return (
            await s.execute(select(AgentRun).where(AgentRun.jira_key == jira_key))
        ).scalar_one_or_none()


async def list_runs(limit: int = 50) -> list[AgentRun]:
    async with get_session() as s:
        rows = await s.execute(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit))
        return list(rows.scalars())


async def get_findings(run_id: str) -> list[FindingSnapshot]:
    async with get_session() as s:
        rows = await s.execute(
            select(FindingSnapshot)
            .where(FindingSnapshot.run_id == run_id)
            .order_by(FindingSnapshot.row_index)
        )
        return list(rows.scalars())


async def get_decisions(run_id: str) -> list[DecisionLog]:
    async with get_session() as s:
        rows = await s.execute(
            select(DecisionLog).where(DecisionLog.run_id == run_id).order_by(DecisionLog.id)
        )
        return list(rows.scalars())
