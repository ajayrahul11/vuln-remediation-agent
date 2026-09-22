"""Build and test. Nothing else. Your existing PR pipeline re-scans and closes
the loop on the security side -- this gate only proves the service still works.

Cheapest first: build, and only if it passes, test. On failure the error text
goes to state["last_failure"] for apply_fix's retry. route_after_validate
(builder.py) bounds the retries.
"""

from __future__ import annotations

import time

from vulnagent.domain import ValidationReport
from vulnagent.graph.state import RemediationState
from vulnagent.validation.build import run_build
from vulnagent.validation.tests import run_tests


async def run(state: RemediationState) -> dict:
    cfg = state["repo_config"]
    workdir = state["workdir"]
    eco = cfg.ecosystem.value
    before = state.get("baseline_test_count", 0)
    start = time.monotonic()

    built, log = await run_build(workdir, cfg.build_command, eco, image=cfg.sandbox_image)
    if not built:
        report = ValidationReport(
            build_passed=False,
            test_count_before=before,
            duration_seconds=time.monotonic() - start,
            logs_excerpt=log,
            failures=["build failed"],
        )
        return {"validation": report, "last_failure": log}

    passed, count, log = await run_tests(workdir, cfg.test_command, eco, image=cfg.sandbox_image)
    report = ValidationReport(
        build_passed=True,
        tests_passed=passed,
        test_count_before=before,
        test_count_after=count,
        duration_seconds=time.monotonic() - start,
        logs_excerpt=log,
    )
    failures = []
    if not passed:
        failures.append("tests failed")
    if not report.tests_not_deleted:
        failures.append(f"test count dropped {before} -> {count}")
    report = report.model_copy(update={"failures": failures})
    update: dict = {"validation": report}
    if failures:
        update["last_failure"] = "\n".join(failures) + "\n" + log
    return update
