"""Run tests and count them.

The count matters as much as pass/fail: a dropped count means a fix made the
suite pass by removing coverage, not by fixing anything.
"""

from __future__ import annotations

import re
import defusedxml.ElementTree as ET
from pathlib import Path

from vulnagent.sandbox import SandboxRunner


def count_tests(workdir: str, ecosystem: str, output: str) -> int:
    if ecosystem == "maven":  # surefire + failsafe JUnit XML
        total = 0
        for report in Path(workdir).rglob("TEST-*.xml"):
            try:
                total += int(ET.parse(report).getroot().get("tests", 0))
            except (ET.ParseError, ValueError):
                continue
        return total
    if ecosystem == "npm":  # jest/vitest: "Tests:  12 passed, 12 total"
        m = re.search(r"Tests:.*?(\d+) total", output)
        return int(m.group(1)) if m else 0
    if ecosystem == "pypi":  # pytest summary: "12 passed, 1 skipped in 0.3s"
        return sum(
            int(n) for n, kind in re.findall(r"(\d+) (passed|failed|error|skipped)", output)
        )
    if ecosystem == "go":
        return len(re.findall(r"^\s*--- (?:PASS|FAIL|SKIP):", output, re.MULTILINE))
    return 0


async def run_tests(
    workdir: str, command: str, ecosystem: str, *, image: str | None = None
) -> tuple[bool, int, str]:
    """(passed, test_count, output_tail)."""
    result = await SandboxRunner(image=image).shell(workdir, command, ecosystem=ecosystem)
    return result.ok, count_tests(workdir, ecosystem, result.output), result.output[-6000:]
