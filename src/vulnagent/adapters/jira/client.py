"""JIRA REST client. Async httpx.

get_issue (ingest), add_comment and transition (writeback) are implemented; both
writes honour settings.dry_run; jql feeds the poller.
"""

from __future__ import annotations

from typing import Any

import httpx

from vulnagent.config import get_settings
from vulnagent.logging import get_logger

log = get_logger(__name__)


class JiraClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        self._base = s.jira_base_url.rstrip("/")
        self._auth = (s.jira_email, s.jira_api_token.get_secret_value())
        self._transport = transport

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base, auth=self._auth, transport=self._transport, timeout=30
        )

    async def get_issue(self, key: str) -> dict[str, Any]:
        async with self._http() as client:
            resp = await client.get(
                f"/rest/api/3/issue/{key}",
                params={"fields": "summary,description,priority,status"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

    async def jql(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Issues matching `query`, up to `limit`. Used by the poller. The query
        need not exclude tickets already claimed: worker/poller.py drops those via
        the UNIQUE claim in Postgres.
        """
        issues: list[dict[str, Any]] = []
        token: str | None = None
        async with self._http() as client:
            while len(issues) < limit:
                body: dict[str, Any] = {
                    "jql": query,
                    "fields": ["summary", "status"],
                    "maxResults": min(limit - len(issues), 100),
                }
                if token:
                    body["nextPageToken"] = token
                resp = await client.post("/rest/api/3/search/jql", json=body)
                resp.raise_for_status()
                data = resp.json()
                issues.extend(data.get("issues", []))
                token = data.get("nextPageToken")
                if not token or data.get("isLast", False):
                    break
        return issues[:limit]

    async def add_comment(self, key: str, body: str) -> None:
        """`body` is JIRA wiki markup (the v2 API renders it; v3 wants ADF)."""
        if get_settings().dry_run:
            log.info("dry_run_jira_comment", key=key, body=body)
            return
        async with self._http() as client:
            resp = await client.post(f"/rest/api/2/issue/{key}/comment", json={"body": body})
            resp.raise_for_status()

    async def transition(self, key: str, transition_name: str) -> None:
        """Move the issue via the workflow transition (or target status) with this name."""
        if get_settings().dry_run:
            log.info("dry_run_jira_transition", key=key, to=transition_name)
            return
        async with self._http() as client:
            resp = await client.get(f"/rest/api/2/issue/{key}/transitions")
            resp.raise_for_status()
            wanted = transition_name.lower()
            for t in resp.json().get("transitions", []):
                if wanted in (t["name"].lower(), t.get("to", {}).get("name", "").lower()):
                    post = await client.post(
                        f"/rest/api/2/issue/{key}/transitions", json={"transition": {"id": t["id"]}}
                    )
                    post.raise_for_status()
                    return
            names = [t["name"] for t in resp.json().get("transitions", [])]
            raise LookupError(f"{key} has no transition {transition_name!r}; available: {names}")
