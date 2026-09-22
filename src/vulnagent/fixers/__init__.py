"""Deterministic dependency bumps: a file edit or a package-manager call, never a model."""

from __future__ import annotations

from pathlib import Path

from vulnagent.domain import Ecosystem, FixTarget
from vulnagent.fixers import maven, npm, pypi
from vulnagent.sandbox import SandboxRunner


class FixError(RuntimeError):
    pass


async def apply_mechanical(target: FixTarget, workdir: str, *, image: str | None = None) -> str:
    """Edit the manifest in `workdir`. Returns a one-line description of the change."""
    root = Path(workdir)
    manifest = root / target.manifest_path
    fixed, pkg = target.fixed_version, target.package

    if target.ecosystem == Ecosystem.MAVEN:
        new, how = maven.bump_pom(manifest.read_text(), pkg, fixed)
        manifest.write_text(new)
        return how

    if target.ecosystem == Ecosystem.NPM:
        new, how = npm.bump_package_json(manifest.read_text(), pkg, fixed)
        manifest.write_text(new)
        if (root / "package-lock.json").is_file():  # let npm regenerate the lockfile
            res = await SandboxRunner(image=image).shell(
                workdir, "npm install --package-lock-only --ignore-scripts", ecosystem="npm"
            )
            if not res.ok:
                raise FixError("npm lockfile update failed:\n" + res.output[-1500:])
        return how

    if target.ecosystem == Ecosystem.PYPI:
        text = manifest.read_text()
        out = pypi.bump_pin(text, pkg, fixed)
        if out is None:
            if manifest.name != "requirements.txt":
                raise FixError(f"{pkg} is not pinned in {manifest.name}; cannot bump mechanically")
            out = text.rstrip("\n") + f"\n{pkg}=={fixed}\n"
        manifest.write_text(out)
        return f"pin {pkg}=={fixed} in {manifest.name}"

    if target.ecosystem == Ecosystem.GO:
        ver = fixed if fixed.startswith("v") else f"v{fixed}"
        res = await SandboxRunner(image=image).shell(
            workdir, f"go get {pkg}@{ver} && go mod tidy", ecosystem="go"
        )
        if not res.ok:
            raise FixError("go get failed:\n" + res.output[-1500:])
        return f"go get {pkg}@{ver}"

    raise FixError(f"no fixer for ecosystem {target.ecosystem}")
