"""Run builds and tests away from the worker's own environment.

Modes (VA_SANDBOX_MODE):
  docker  (default) one throwaway container per command: CPU/memory/pid limits,
          all capabilities dropped, no-new-privileges, only the workdir mounted,
          no host env passed in, hard timeout, container always removed.
  local   plain subprocess with a scrubbed environment. Dev convenience only --
          it runs third-party build code on your machine.

NOT enforced yet: the per-ecosystem egress allowlist in policies.py. The container
has normal outbound network (Maven/npm need it). Do the network policy at the
cluster/host level before pointing this at repos you do not control.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import time
import uuid
from dataclasses import dataclass

from vulnagent.config import get_settings
from vulnagent.logging import get_logger
from vulnagent.sandbox.policies import RESOURCE_LIMITS

log = get_logger(__name__)

_DEFAULT_IMAGES = {
    "maven": "maven:3.9-eclipse-temurin-11",
    "npm": "node:20",
    "pypi": "python:3.12",
    "go": "golang:1.23",
}
# Package-manager caches persist across runs in named volumes.
_CACHES = {
    "maven": "/root/.m2",
    "npm": "/root/.npm",
    "pypi": "/root/.cache/pip",
    "go": "/go/pkg",
}


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


class SandboxRunner:
    def __init__(self, *, image: str | None = None) -> None:
        self._image = image

    async def exec(
        self, workdir: str, command: list[str], *, ecosystem: str, timeout: int | None = None
    ) -> SandboxResult:
        s = get_settings()
        timeout = timeout or s.sandbox_timeout_seconds
        if s.sandbox_mode == "local":
            return await self._run(command, cwd=workdir, timeout=timeout, env=_local_env())

        name = f"vulnagent-{uuid.uuid4().hex[:12]}"
        image = self._image or _DEFAULT_IMAGES[ecosystem]
        docker = [
            "docker", "run", "--rm", "--name", name,
            "--cpus", RESOURCE_LIMITS["cpu"],
            "--memory", RESOURCE_LIMITS["memory"],
            "--pids-limit", str(RESOURCE_LIMITS["pids"]),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "-v", f"{os.path.abspath(workdir)}:/work", "-w", "/work",
            "-v", f"vulnagent-{ecosystem}-cache:{_CACHES[ecosystem]}",
            image, *command,
        ]  # fmt: skip
        result = await self._run(docker, cwd=None, timeout=timeout, env=_local_env())
        if result.timed_out:
            await self._run(["docker", "rm", "-f", name], cwd=None, timeout=30, env=_local_env())
        return result

    async def shell(
        self, workdir: str, command: str, *, ecosystem: str, timeout: int | None = None
    ) -> SandboxResult:
        """Run a shell command string (from RepoConfig) via `sh -c`."""
        return await self.exec(workdir, ["sh", "-c", command], ecosystem=ecosystem, timeout=timeout)

    async def _run(
        self, command: list[str], *, cwd: str | None, timeout: int, env: dict[str, str]
    ) -> SandboxResult:
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, cwd=cwd, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
        except FileNotFoundError as exc:
            return SandboxResult(127, "", f"{shlex.quote(command[0])} not found: {exc}", 0.0)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            timed_out = False
        except TimeoutError:
            proc.kill()
            out, err = await proc.communicate()
            timed_out = True
        return SandboxResult(
            proc.returncode if proc.returncode is not None else -1,
            out.decode(errors="replace"),
            err.decode(errors="replace"),
            time.monotonic() - start,
            timed_out,
        )


def _local_env() -> dict[str, str]:
    """No secrets: only what a build needs to find its tools."""
    keep = ("PATH", "HOME", "JAVA_HOME", "LANG", "DOCKER_HOST", "TMPDIR")
    return {k: v for k, v in os.environ.items() if k in keep}
