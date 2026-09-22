"""Bump the dependency. Deterministic first, LLM only as a fallback.

ATTEMPT 1: mechanical bump only (fixers/) -- a file edit or package-manager call.
RETRY (a previous validate failed): read state["last_failure"] and ask the model
  for a minimal unified diff that adapts call sites. Guards: only files named in
  the failure may change, never the manifest, and the diff must apply cleanly.
  A malformed or out-of-bounds diff is a hard failure, never a guess.

`attempt` is incremented here on retries, so validate -> route_after_validate
sees attempt == max_attempts after the last allowed try.
"""

from __future__ import annotations

import asyncio
import re

from vulnagent.domain import PatchResult
from vulnagent.fixers import FixError, apply_mechanical
from vulnagent.graph.state import RemediationState
from vulnagent.llm import get_model
from vulnagent.llm.guards import scan_for_injection
from vulnagent.logging import get_logger
from vulnagent.prompts import get_prompt

log = get_logger(__name__)

_SOURCE_TOKEN = re.compile(r"[\w./-]+\.(?:java|kt|scala|groovy|py|js|ts|tsx|go)\b")
_FORBIDDEN = re.compile(r"(^\.github/|Dockerfile|credential|secret|\.pem$|\.key$)", re.I)


async def _git(workdir: str, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=workdir,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace")


async def _snapshot(workdir: str) -> tuple[str, list[str]]:
    """Cumulative diff and changed files vs HEAD (survives across attempts)."""
    _, diff = await _git(workdir, "diff", "HEAD")
    _, names = await _git(workdir, "diff", "HEAD", "--name-only")
    return diff, [n for n in names.splitlines() if n]


async def _allowed_files(workdir: str, failure: str, manifest: str) -> list[str]:
    _, tracked = await _git(workdir, "ls-files")
    tracked_files = tracked.splitlines()
    found: list[str] = []
    for token in dict.fromkeys(_SOURCE_TOKEN.findall(failure)):
        for path in tracked_files:
            if (token == path or token.endswith("/" + path)) and path != manifest:
                if not _FORBIDDEN.search(path) and path not in found:
                    found.append(path)
    return found[:5]


def _diff_paths(diff: str) -> set[str]:
    paths = set()
    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ")):
            p = line[4:].split("\t")[0].strip()
            if p != "/dev/null":
                paths.add(re.sub(r"^[ab]/", "", p))
    return paths


async def _llm_break_fix(state: RemediationState) -> PatchResult:
    workdir = state["workdir"]
    target = state["fix_target"]
    failure = state.get("last_failure", "")
    if hits := scan_for_injection(failure):
        log.warning("injection_pattern_in_build_output", patterns=hits)

    allowed = await _allowed_files(workdir, failure, target.manifest_path)
    if not allowed:
        return PatchResult(
            succeeded=False, generated_by="llm", error="failure names no editable source file"
        )
    context = "\n\n".join(
        f"=== {p}\n{(await asyncio.to_thread(_read, workdir, p))}" for p in allowed
    )
    prompt = get_prompt("execute.dependency_break_fix").render(
        package=target.package,
        old_version=target.installed_version,
        new_version=target.fixed_version,
        build_error=failure[-6000:],
        code_context=context,
        allowed_files="\n".join(allowed),
        safety_rails=get_prompt("system.safety_rails").body,
    )
    try:
        reply = await get_model().ainvoke(prompt)
    except Exception as exc:
        return PatchResult(succeeded=False, generated_by="llm", error=f"model call failed: {exc}")
    text = reply.content if isinstance(reply.content, str) else "".join(
        b.get("text", "") for b in reply.content if isinstance(b, dict)
    )
    text = re.sub(r"^```\w*\n|\n```\s*$", "", text.strip())

    if text.startswith("CANNOT_PATCH") or not text.startswith(("--- ", "diff --git")):
        return PatchResult(succeeded=False, generated_by="llm", error=text[:300] or "empty reply")
    touched = _diff_paths(text)
    if not touched or not touched <= set(allowed):
        return PatchResult(
            succeeded=False, generated_by="llm",
            error=f"diff touches files outside ALLOWED_FILES: {sorted(touched - set(allowed))}",
        )  # fmt: skip

    patch_file = f"{workdir}/.vulnagent.patch"
    await asyncio.to_thread(_write, patch_file, text + "\n")
    code, out = await _git(workdir, "apply", "--check", patch_file)
    if code == 0:
        code, out = await _git(workdir, "apply", patch_file)
    await asyncio.to_thread(_remove, patch_file)
    if code != 0:
        return PatchResult(succeeded=False, generated_by="llm", error=f"diff did not apply: {out}")
    return PatchResult(succeeded=True, generated_by="llm")


def _read(workdir: str, rel: str) -> str:
    with open(f"{workdir}/{rel}", encoding="utf-8", errors="replace") as fh:
        return fh.read()[:20_000]


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _remove(path: str) -> None:
    import os

    os.remove(path)


async def run(state: RemediationState) -> dict:
    workdir = state["workdir"]
    retry = bool(state.get("last_failure"))
    attempt = state.get("attempt", 1) + (1 if retry else 0)

    if not retry:
        target = state["fix_target"]
        try:
            how = await apply_mechanical(
                target, workdir, image=state["repo_config"].sandbox_image
            )
        except (FixError, ValueError, OSError) as exc:
            result = PatchResult(succeeded=False, error=str(exc))
        else:
            result = PatchResult(succeeded=True, generated_by="deterministic")
            log.info("bumped", how=how)
    else:
        result = await _llm_break_fix(state)

    diff, files = await _snapshot(workdir)
    result = result.model_copy(update={"diff": diff, "files_changed": files})
    update: dict = {
        "patch": result,
        "attempt": attempt,
        "decisions": [
            {
                "node": "apply_fix",
                "attempt": attempt,
                "generated_by": result.generated_by,
                "succeeded": result.succeeded,
                "files": files,
                "error": result.error,
            }
        ],
    }
    if not result.succeeded:
        update["terminal_status"] = "escalated"
        update["escalation_reason"] = f"could not apply a fix (attempt {attempt}): {result.error}"
    return update
