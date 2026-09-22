"""What apply_fix needs to actually write the change.

Produced by the prepare node from three things: the Finding (package + fixed
version, already known from the ticket), the manifest file actually found in
the repo, and one deterministic check -- is this package a direct or
transitive dependency. That check is a dependency-graph lookup
(`mvn dependency:tree`, `npm ls`, `pip show`), not a security scan: it tells
you which file to edit, not whether anything is exploitable.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from vulnagent.domain.enums import Ecosystem


class FixTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    ecosystem: Ecosystem
    package: str
    installed_version: str
    fixed_version: str
    manifest_path: str
    is_direct_dependency: bool
    parent_package: str | None = None  # set when transitive: the direct dep that pulls it in
