from __future__ import annotations

from fastapi import APIRouter

from vulnagent.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, object]:
    s = get_settings()
    return {"status": "ok", "env": s.env, "dry_run": s.dry_run, "kill_switch": s.kill_switch}
