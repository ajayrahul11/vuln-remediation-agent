"""Operator surface: inspect a run, flip the kill switch.

TODO(step 15): implement.
  GET  /runs/{jira_key}     decision log + patch + validation report
  POST /admin/kill-switch   flips settings.kill_switch, audited, requires auth
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{jira_key}")
async def get_run(jira_key: str) -> dict[str, str]:
    raise NotImplementedError("TODO(step 15)")
