"""CVE link -> which dependency to bump, and to what.

Called by prepare AFTER the repo is cloned, because the answer depends on
what the repo actually ships: a CVE can name many packages, and only the ones
present in the repo's dependency tree at an affected version are relevant.

  1. CVE id from the link (or, failing that, from the page it points at)
  2. OSV records for that id and its aliases (GHSA-...), fetched from
     api.osv.dev -- structured `affected[].ranges[].events[].fixed` data
  3. keep the affected packages the repo depends on, at a version inside an
     affected range, and take that range's `fixed` version

The linked page is untrusted. Only a regex-matched CVE id is ever taken from
it; its text never reaches an LLM.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import httpx
from packaging.version import InvalidVersion, Version

from vulnagent.domain.enums import Ecosystem

_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_OSV_ECOSYSTEM = {
    Ecosystem.MAVEN: "Maven",
    Ecosystem.NPM: "npm",
    Ecosystem.PYPI: "PyPI",
    Ecosystem.GO: "Go",
}
_MAX_RECORDS = 10


class CveResolutionError(RuntimeError):
    """No safe fix could be determined. Escalate with this message."""


@dataclass(frozen=True)
class ResolvedFix:
    package: str
    installed_version: str
    fixed_version: str
    source_ids: tuple[str, ...]


def extract_cve_id(text: str) -> str | None:
    m = _CVE_RE.search(text)
    return m.group(0).upper() if m else None


async def fetch_cve_id(url: str, client: httpx.AsyncClient) -> str:
    """CVE id from the link itself, else from the linked page."""
    if cve := extract_cve_id(url):
        return cve
    try:
        resp = await client.get(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise CveResolutionError(f"could not open CVE link {url}: {exc}") from exc
    if cve := extract_cve_id(str(resp.url) + "\n" + resp.text[:200_000]):
        return cve
    raise CveResolutionError(f"no CVE id found at {url}")


def _norm(name: str, ecosystem: Ecosystem) -> str:
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == Ecosystem.PYPI else name


def _vkey(v: str) -> tuple:
    v = v.lstrip("vV")
    try:
        return (0, Version(v))
    except InvalidVersion:
        return (1, tuple(int(n) for n in re.findall(r"\d+", v)))


def _fixed_for(installed: str, ranges: list[dict]) -> str | None:
    """The `fixed` bound of the affected interval containing `installed`."""
    for rng in ranges:
        if rng.get("type") not in ("ECOSYSTEM", "SEMVER"):
            continue
        introduced: str | None = None
        for ev in rng.get("events", []):
            if "introduced" in ev:
                introduced = ev["introduced"]
            elif "fixed" in ev and introduced is not None:
                lo_ok = introduced == "0" or _vkey(installed) >= _vkey(introduced)
                if lo_ok and _vkey(installed) < _vkey(ev["fixed"]):
                    return ev["fixed"]
                introduced = None
    return None


async def _osv_records(cve_id: str, client: httpx.AsyncClient, base_url: str) -> list[dict]:
    async def get(vuln_id: str) -> dict | None:
        resp = await client.get(f"{base_url}/v1/vulns/{vuln_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    try:
        first = await get(cve_id)
        if first is None:
            raise CveResolutionError(f"{cve_id} not found in OSV")
        records, seen = [first], {cve_id}
        for other in [*first.get("aliases", []), *first.get("related", [])]:
            if other in seen or len(records) >= _MAX_RECORDS:
                continue
            seen.add(other)
            if rec := await get(other):
                records.append(rec)
        return records
    except httpx.HTTPError as exc:
        raise CveResolutionError(f"OSV lookup failed for {cve_id}: {exc}") from exc


async def resolve_fixes(
    cve_url: str,
    ecosystem: Ecosystem,
    dependencies: Mapping[str, str],
    *,
    client: httpx.AsyncClient,
    osv_base_url: str = "https://api.osv.dev",
) -> tuple[str, list[ResolvedFix]]:
    """Returns (cve_id, fixes). `dependencies` maps package name -> installed
    version for the cloned repo. Raises CveResolutionError if nothing in the
    repo is affected at a version we can fix."""
    cve_id = await fetch_cve_id(cve_url, client)
    records = await _osv_records(cve_id, client, osv_base_url.rstrip("/"))

    installed = {_norm(n, ecosystem): (n, v) for n, v in dependencies.items()}
    osv_eco = _OSV_ECOSYSTEM[ecosystem]
    found: dict[str, tuple[str, str, set[str]]] = {}

    for rec in records:
        for aff in rec.get("affected", []):
            pkg = aff.get("package", {})
            if pkg.get("ecosystem", "").split(":")[0] != osv_eco:
                continue
            hit = installed.get(_norm(pkg.get("name", ""), ecosystem))
            if hit is None:
                continue
            name, version = hit
            fixed = _fixed_for(version, aff.get("ranges", []))
            if fixed is None:
                continue
            prev = found.get(name)
            if prev is None or _vkey(fixed) > _vkey(prev[1]):
                found[name] = (version, fixed, {rec["id"]} | (prev[2] if prev else set()))
            else:
                prev[2].add(rec["id"])

    if not found:
        raise CveResolutionError(
            f"{cve_id}: no {osv_eco} dependency in this repo is in an affected range with a "
            "known fix version"
        )
    fixes = [
        ResolvedFix(name, ver, fixed, tuple(sorted(ids)))
        for name, (ver, fixed, ids) in sorted(found.items())
    ]
    return cve_id, fixes
