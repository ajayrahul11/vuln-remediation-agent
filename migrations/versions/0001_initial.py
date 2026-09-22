"""agent_run, finding_snapshot, decision_log, audit_event

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_ts = dict(type_=sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "agent_run",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("jira_key", sa.Text, nullable=False, unique=True),  # the dedup
        sa.Column("repo_full_name", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("started_at", **_ts),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "finding_snapshot",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("row_index", sa.Integer, primary_key=True, server_default="0"),
        sa.Column("package", sa.Text),
        sa.Column("installed_version", sa.Text),
        sa.Column("fixed_version", sa.Text),
        sa.Column("finding", JSONB, nullable=False),
        sa.Column("created_at", **_ts),
    )
    op.create_table(
        "decision_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Text, nullable=False, index=True),
        sa.Column("node", sa.Text, nullable=False),
        sa.Column("input_hash", sa.Text, nullable=False),
        sa.Column("inputs", JSONB, nullable=False),
        sa.Column("outputs", JSONB, nullable=False),
        sa.Column("prompt_ref", JSONB),
        sa.Column("created_at", **_ts),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Text, nullable=False, index=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("node", sa.Text),
        sa.Column("detail", JSONB, nullable=False),
        sa.Column("created_at", **_ts),
    )

    # Append-only. Two layers: a trigger (binds every role, including the table
    # owner and the local-dev superuser) and a REVOKE for the production app role.
    op.execute(
        """
        CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: % not permitted', TG_TABLE_NAME, TG_OP;
        END $$;
        """
    )
    for table in ("audit_event", "decision_log", "finding_snapshot"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()"
        )

    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vulnagent_app') THEN
                CREATE ROLE vulnagent_app NOLOGIN;
            END IF;
        END $$;
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON agent_run TO vulnagent_app")
    op.execute(
        "GRANT SELECT, INSERT ON finding_snapshot, decision_log, audit_event TO vulnagent_app"
    )
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO vulnagent_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_event FROM vulnagent_app")


def downgrade() -> None:
    for table in ("audit_event", "decision_log", "finding_snapshot", "agent_run"):
        op.drop_table(table)
    op.execute("DROP FUNCTION forbid_mutation()")
