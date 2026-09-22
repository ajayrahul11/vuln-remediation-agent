from __future__ import annotations

import pytest

from vulnagent.worker import poller


@pytest.fixture
def wired(monkeypatch):
    claimed: set[str] = set()
    ran: list[tuple[str, str]] = []
    statuses: list[str] = []

    class FakeJira:
        async def jql(self, query, *, limit=50):
            return [{"key": "SEC-1"}, {"key": "SEC-2"}, {"key": "SEC-3"}]

    async def claim(key, run_id):
        if key in claimed:
            return False
        claimed.add(key)
        return True

    async def run(key, *, dry_run, run_id):
        if key == "SEC-2":
            raise RuntimeError("boom")
        ran.append((key, run_id))

    async def record(run_id, *, status, **kw):
        statuses.append(status)

    monkeypatch.setattr(poller, "JiraClient", FakeJira)
    monkeypatch.setattr(poller, "claim_ticket", claim)
    monkeypatch.setattr(poller, "run_for_jira_issue", run)
    monkeypatch.setattr(poller, "record_run", record)
    return claimed, ran, statuses


async def test_claims_runs_and_isolates_failures(wired) -> None:
    _, ran, statuses = wired
    assert await poller.poll_once() == 3
    assert [k for k, _ in ran] == ["SEC-1", "SEC-3"]  # SEC-2 crashed, SEC-3 still ran
    assert statuses == ["failed"]


async def test_second_poll_claims_nothing(wired) -> None:
    _, ran, _ = wired
    await poller.poll_once()
    ran.clear()
    assert await poller.poll_once() == 0
    assert ran == []
