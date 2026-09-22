from __future__ import annotations

import httpx

from vulnagent.adapters.jira import JiraClient


async def test_jql_paginates_and_respects_limit() -> None:
    pages = iter(
        [
            {"issues": [{"key": "A-1"}, {"key": "A-2"}], "nextPageToken": "t1"},
            {"issues": [{"key": "A-3"}], "isLast": True},
        ]
    )
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json=next(pages))

    client = JiraClient(transport=httpx.MockTransport(handler))
    issues = await client.jql("project = SEC")
    assert [i["key"] for i in issues] == ["A-1", "A-2", "A-3"]
    assert seen[1]["nextPageToken"] == "t1"
