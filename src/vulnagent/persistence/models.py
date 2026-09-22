"""SQLAlchemy models.

Four tables, no pgvector -- there's no code-retrieval executor in this version,
so there's nothing to embed.

  agent_run          one row per ticket. UNIQUE on jira_key is the whole
                      idempotency mechanism: the poller's INSERT is the claim.
  finding_snapshot    the Finding as ingested, immutable (one per ticket row)
  decision_log        append-only: node, input hash, output, prompt ref
  audit_event         append-only, never updated or deleted

decision_log, audit_event and finding_snapshot deliberately carry no foreign
key to agent_run: an audit write must never fail because a parent row is
missing (e.g. a run started directly from the CLI without a poller claim).

Append-only is enforced in the database (see migrations/versions/0001): the
app role has UPDATE/DELETE revoked, and a trigger rejects them for everyone
else, including the table owner.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AgentRun(Base):
    __tablename__ = "agent_run"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    jira_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    repo_full_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FindingSnapshot(Base):
    __tablename__ = "finding_snapshot"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    row_index: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)
    package: Mapped[str | None] = mapped_column(Text)
    installed_version: Mapped[str | None] = mapped_column(Text)
    fixed_version: Mapped[str | None] = mapped_column(Text)
    finding: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DecisionLog(Base):
    __tablename__ = "decision_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    node: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prompt_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    node: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
