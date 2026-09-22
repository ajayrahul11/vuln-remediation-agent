"""GitHub client authenticated with a personal access token (PAT).

The simple alternative to a GitHub App, e.g. for a personal repo.

  clone      works with NO token for a public repo; with a token for private ones
  push / PR  need a token with Contents + Pull requests read/write on the repo

The token is handed to git through GIT_CONFIG_* environment variables as an
Authorization header. It is never put in a URL, so it isn't written to
`.git/config`, shown in `ps`, or echoed in git's error output.
"""

from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path

import httpx

from vulnagent.config import get_settings
from vulnagent.logging import get_logger

log = get_logger(__name__)

_API = "https://api.github.com"


class GitError(RuntimeError):
    pass


class GitHubTokenClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        self._token = s.github_token.get_secret_value()
        self._name = s.github_commit_name
        self._email = s.github_commit_email
        self._transport = transport

    # ---- git plumbing -------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if self._token:
            basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
            env.update(
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {basic}",
            )
        return env

    def _scrub(self, text: str) -> str:
        if not self._token:
            return text
        basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
        return text.replace(self._token, "***").replace(basic, "***")

    async def _git(self, *args: str, cwd: str | None = None) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            env=self._env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        text = self._scrub(out.decode(errors="replace"))
        if proc.returncode != 0:
            raise GitError(f"git {args[0]} failed ({proc.returncode}): {text.strip()}")
        return text.strip()

    def _require_token(self, action: str) -> None:
        if not self._token:
            raise GitError(f"{action} needs VA_GITHUB_TOKEN (a PAT with write access to the repo)")

    # ---- VcsClient ----------------------------------------------------

    async def clone(self, repo_full_name: str, ref: str, dest: str) -> str:
        """Clone into `dest`. `ref` = branch to check out, or "" for the default branch."""
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--depth", "50"]
        if ref:
            args += ["--branch", ref]
        await self._git(*args, f"https://github.com/{repo_full_name}.git", dest)
        log.info("cloned", repo=repo_full_name, authenticated=bool(self._token))
        return dest

    async def create_branch(self, workdir: str, branch: str) -> None:
        await self._git("checkout", "-b", branch, cwd=workdir)

    async def commit_all(
        self, workdir: str, message: str, paths: list[str] | None = None
    ) -> str:
        """Unsigned commit -- the REST create-commit API's signing is App-only.
        With `paths`, stage only those files, so build output (target/, node_modules/)
        the repo forgot to gitignore never lands in the commit."""
        await self._git("add", "--", *paths, cwd=workdir) if paths else await self._git(
            "add", "-A", cwd=workdir
        )
        await self._git(
            "-c", f"user.name={self._name}", "-c", f"user.email={self._email}",
            "commit", "-m", message, cwd=workdir,
        )  # fmt: skip
        return await self._git("rev-parse", "HEAD", cwd=workdir)

    async def push(self, workdir: str, branch: str) -> None:
        self._require_token("push")
        await self._git("push", "--set-upstream", "origin", branch, cwd=workdir)

    async def open_pr(
        self, repo_full_name: str, head: str, base: str, title: str, body: str, draft: bool
    ) -> str:
        self._require_token("open_pr")
        async with httpx.AsyncClient(
            base_url=_API,
            transport=self._transport,
            timeout=30,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        ) as client:
            resp = await client.post(
                f"/repos/{repo_full_name}/pulls",
                json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
            )
            if resp.status_code >= 400:
                raise GitError(f"open_pr failed ({resp.status_code}): {resp.text[:500]}")
            return resp.json()["html_url"]
