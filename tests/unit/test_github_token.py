from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from vulnagent.adapters.vcs.github_token import GitError, GitHubTokenClient
from vulnagent.config import get_settings


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VA_GITHUB_TOKEN", "ghp_secret123")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_token_goes_in_env_header_not_url() -> None:
    env = GitHubTokenClient()._env()
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
    assert "ghp_secret123" not in env["GIT_CONFIG_VALUE_0"]  # base64-encoded


def test_scrub_hides_token_and_encoded_header() -> None:
    c = GitHubTokenClient()
    basic = c._env()["GIT_CONFIG_VALUE_0"].split()[-1]
    assert c._scrub(f"fatal ghp_secret123 {basic}") == "fatal *** ***"


async def test_commit_and_branch_in_a_local_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "pom.xml").write_text("<a/>")
    c = GitHubTokenClient()
    await c.create_branch(str(tmp_path), "sec/x")
    sha = await c.commit_all(str(tmp_path), "msg")
    assert len(sha) == 40


async def test_push_without_token_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VA_GITHUB_TOKEN", "")
    get_settings.cache_clear()
    with pytest.raises(GitError, match="VA_GITHUB_TOKEN"):
        await GitHubTokenClient().push("/tmp", "b")


async def test_open_pr_posts_and_returns_url() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/repos/o/r/pulls"
        assert req.headers["authorization"] == "Bearer ghp_secret123"
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/1"})

    c = GitHubTokenClient(transport=httpx.MockTransport(handler))
    assert await c.open_pr("o/r", "sec/x", "main", "t", "b", False) == "https://github.com/o/r/pull/1"
