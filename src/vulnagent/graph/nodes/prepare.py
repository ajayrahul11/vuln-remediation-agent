"""Clone the repo, work out how to build it, and decide exactly what to change.

  1. clone (PAT, or anonymous for a public repo) into workdir/<run_id>/...
  2. RepoConfigResolver -> build/test commands (catalog override, else detected)
  3. list the repo's dependencies (name -> installed version, direct or not)
  4. resolve the CVE link against those dependencies -> package + fixed version
     (cve/resolver.py; the ticket carries neither)
  5. run the test suite once, before any change: the baseline count that
     ValidationReport.tests_not_deleted compares against. A suite that fails
     before we touch anything makes the gate meaningless -> escalate.
  6. locate the manifest and assemble FixTarget

Anything unresolvable escalates. We do not guess a manifest, a package or a version.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from vulnagent.adapters.vcs import get_vcs_client
from vulnagent.catalog import RepoConfigResolver, list_dependencies
from vulnagent.config import get_settings
from vulnagent.cve import CveResolutionError, resolve_fixes
from vulnagent.domain import Ecosystem, FixTarget
from vulnagent.graph.nodes.escalate import escalation
from vulnagent.graph.state import RemediationState
from vulnagent.logging import get_logger
from vulnagent.validation.tests import run_tests

log = get_logger(__name__)


def locate_manifest(workdir: Path, ecosystem: Ecosystem, package: str) -> str | None:
    if ecosystem == Ecosystem.MAVEN:
        return "pom.xml" if (workdir / "pom.xml").is_file() else None
    if ecosystem == Ecosystem.NPM:
        return "package.json" if (workdir / "package.json").is_file() else None
    if ecosystem == Ecosystem.GO:
        return "go.mod" if (workdir / "go.mod").is_file() else None
    for name in ("requirements.txt", "pyproject.toml"):
        if (workdir / name).is_file():
            return name
    return None


async def run(state: RemediationState) -> dict:
    settings = get_settings()
    finding = state["finding"]
    dest = str(Path(settings.workdir_root) / state["run_id"] / finding.repo_full_name.replace("/", "__"))

    try:
        await get_vcs_client().clone(finding.repo_full_name, "", dest)
    except Exception as exc:
        return escalation("prepare", f"could not clone {finding.repo_full_name}: {exc}")
    workdir = Path(dest)

    cfg = RepoConfigResolver.load().resolve(finding.repo_full_name, workdir)
    if cfg is None:
        return escalation("prepare", "unrecognised repo layout: no known manifest at the repo root")
    eco = cfg.ecosystem

    try:
        inventory = await list_dependencies(dest, eco, image=cfg.sandbox_image)
    except Exception as exc:
        return escalation("prepare", f"could not list dependencies: {exc}")

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            cve_id, fixes = await resolve_fixes(
                finding.cve_url or "",
                eco,
                inventory.versions,
                client=client,
                osv_base_url=settings.osv_base_url,
            )
        except CveResolutionError as exc:
            return escalation("prepare", str(exc))

    # Prefer a direct dependency; then the largest jump. Report the rest, don't drop them.
    fixes.sort(key=lambda f: (f.package not in inventory.direct, f.package))
    fix = fixes[0]
    others = [f"{f.package} {f.installed_version}->{f.fixed_version}" for f in fixes[1:]]

    manifest = locate_manifest(workdir, eco, fix.package)
    if manifest is None:
        return escalation("prepare", f"no manifest found to edit for {fix.package}")

    passed, baseline, tail = await run_tests(
        dest, cfg.test_command, eco.value, image=cfg.sandbox_image
    )
    if not passed:
        return escalation(
            "prepare", f"the test suite already fails before any change; cannot validate a fix:\n{tail[-1500:]}"
        )

    target = FixTarget(
        ecosystem=eco,
        package=fix.package,
        installed_version=fix.installed_version,
        fixed_version=fix.fixed_version,
        manifest_path=manifest,
        is_direct_dependency=fix.package in inventory.direct,
    )
    updated = finding.model_copy(
        update={
            "cve_id": cve_id,
            "ecosystem": eco,
            "package": fix.package,
            "installed_version": fix.installed_version,
            "fixed_version": fix.fixed_version,
        }
    )
    log.info("prepared", package=fix.package, fixed=fix.fixed_version, baseline_tests=baseline)
    return {
        "finding": updated,
        "repo_config": cfg,
        "fix_target": target,
        "workdir": dest,
        "baseline_test_count": baseline,
        "decisions": [
            {
                "node": "prepare",
                "outcome": "ok",
                "package": fix.package,
                "from": fix.installed_version,
                "to": fix.fixed_version,
                "direct": target.is_direct_dependency,
                "osv_ids": list(fix.source_ids),
                "also_affected_not_fixed": others,
                "baseline_tests": baseline,
            }
        ],
    }
