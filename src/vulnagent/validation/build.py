"""Run the repo's build command in the sandbox."""

from __future__ import annotations

from vulnagent.sandbox import SandboxRunner


async def run_build(
    workdir: str, command: str, ecosystem: str, *, image: str | None = None
) -> tuple[bool, str]:
    """(passed, output_tail). The tail is what apply_fix's retry reads."""
    result = await SandboxRunner(image=image).shell(workdir, command, ecosystem=ecosystem)
    return result.ok, result.output[-6000:]
