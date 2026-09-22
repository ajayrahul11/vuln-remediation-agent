"""What does this repo depend on, at what version, and directly or not?

Operational bookkeeping to decide WHICH file to edit -- not a vulnerability scan.
Maven needs the build tool (transitives are only known after resolution), so it
runs `dependency:list` in the sandbox. npm/pypi/go are read from manifests and
lockfiles statically.
"""

from __future__ import annotations

import json
import re
import tomllib
import defusedxml.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from vulnagent.domain import Ecosystem
from vulnagent.sandbox import SandboxRunner


@dataclass
class DependencyInventory:
    versions: dict[str, str] = field(default_factory=dict)  # name -> installed version
    direct: set[str] = field(default_factory=set)


def parse_maven_list(output: str) -> dict[str, str]:
    """`group:artifact:type[:classifier]:version:scope` lines from dependency:list."""
    out: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.strip().split(":")
        if len(parts) in (5, 6) and re.fullmatch(r"[\w.-]+", parts[0]):
            out.setdefault(f"{parts[0]}:{parts[1]}", parts[-2])
    return out


def maven_declared(pom_text: str) -> set[str]:
    """group:artifact pairs declared in the pom's own <dependencies> (not in
    dependencyManagement, not inherited)."""
    root = ET.fromstring(pom_text)
    ns = {"m": root.tag[1:].split("}")[0]} if root.tag.startswith("{") else {}
    q = "m:" if ns else ""
    deps = root.find(f"{q}dependencies", ns)
    found: set[str] = set()
    for d in deps.findall(f"{q}dependency", ns) if deps is not None else []:
        g, a = d.find(f"{q}groupId", ns), d.find(f"{q}artifactId", ns)
        if g is not None and a is not None:
            found.add(f"{g.text}:{a.text}")
    return found


def _npm(workdir: Path) -> DependencyInventory:
    inv = DependencyInventory()
    pkg = json.loads((workdir / "package.json").read_text())
    inv.direct = set(pkg.get("dependencies", {})) | set(pkg.get("devDependencies", {}))
    lock = workdir / "package-lock.json"
    if lock.is_file():
        for path, meta in json.loads(lock.read_text()).get("packages", {}).items():
            if path.startswith("node_modules/") and "version" in meta:
                inv.versions[path.rsplit("node_modules/", 1)[-1]] = meta["version"]
    for name in inv.direct:  # fall back to declared specs when there is no lockfile
        inv.versions.setdefault(name, re.sub(r"^[\^~>=<\s]+", "", pkg.get("dependencies", {}).get(
            name, pkg.get("devDependencies", {}).get(name, ""))))
    return inv


def _pypi(workdir: Path) -> DependencyInventory:
    inv = DependencyInventory()
    lines: list[str] = []
    req = workdir / "requirements.txt"
    if req.is_file():
        lines += req.read_text().splitlines()
    pyproject = workdir / "pyproject.toml"
    if pyproject.is_file():
        lines += tomllib.loads(pyproject.read_text()).get("project", {}).get("dependencies", [])
    for line in lines:
        m = re.match(r"\s*([A-Za-z0-9_.-]+)\s*(?:\[[^\]]*\])?\s*==\s*([\w.+!-]+)", line)
        if m:
            name = re.sub(r"[-_.]+", "-", m.group(1)).lower()
            inv.versions[name] = m.group(2)
            inv.direct.add(name)
    return inv


def _go(workdir: Path) -> DependencyInventory:
    inv = DependencyInventory()
    for m in re.finditer(r"^\s*(?:require\s+)?([\w./~-]+)\s+(v[\w.+-]+)(\s*//\s*indirect)?",
                         (workdir / "go.mod").read_text(), re.MULTILINE):
        if m.group(1) in ("module", "go", "require", "replace", "exclude"):
            continue
        inv.versions[m.group(1)] = m.group(2)
        if not m.group(3):
            inv.direct.add(m.group(1))
    return inv


async def list_dependencies(
    workdir: str, ecosystem: Ecosystem, *, image: str | None = None
) -> DependencyInventory:
    root = Path(workdir)
    if ecosystem == Ecosystem.NPM:
        return _npm(root)
    if ecosystem == Ecosystem.PYPI:
        return _pypi(root)
    if ecosystem == Ecosystem.GO:
        return _go(root)

    result = await SandboxRunner(image=image).shell(
        workdir,
        "mvn -B -ntp -q dependency:list -DoutputFile=/tmp/deps.txt -DappendOutput=false "
        ">/tmp/mvn.log 2>&1; rc=$?; cat /tmp/deps.txt 2>/dev/null; "
        "[ $rc -eq 0 ] || { echo '#MVN_FAILED'; tail -40 /tmp/mvn.log; }",
        ecosystem="maven",
    )
    if "#MVN_FAILED" in result.stdout or not result.ok:
        raise RuntimeError("mvn dependency:list failed:\n" + result.output[-2000:])
    return DependencyInventory(
        versions=parse_maven_list(result.stdout),
        direct=maven_declared((root / "pom.xml").read_text()),
    )
