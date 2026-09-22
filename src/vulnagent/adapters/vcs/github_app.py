"""GitHub App client. Least privilege: contents:write, pull_requests:write, checks:read.

TODO(step 12, using clone from step 8): implement.
  - installation_token(): JWT from the app private key -> installation access
    token, cached for 50 minutes (they live 60)
  - clone(): used once per run, by prepare (step 8). The same workdir and
    token are reused by apply_fix, validate, and publish_pr -- don't re-clone.
  - create_branch, commit_all (signed, via the create-commit API), push, open_pr
  - scrub the token from every log line
"""

from __future__ import annotations


class GitHubAppClient:
    async def installation_token(self) -> str:
        raise NotImplementedError("TODO(step 12): JWT -> installation token")

    async def clone(self, repo_full_name: str, ref: str, dest: str) -> str:
        raise NotImplementedError("TODO(step 8)")
