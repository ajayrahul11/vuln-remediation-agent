"""Everything needed to build and test a repo. NOT a security concept -- this is
plain operational metadata a security ticket never carries.

Resolution order (see catalog/repo_config.py): an explicit override in
config/catalog.yaml, else auto-detected from the manifest file actually in the
repo. Fail closed only on ecosystem -- an unrecognised ecosystem escalates
rather than guessing a build command.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vulnagent.domain.enums import Ecosystem


class RepoConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo_full_name: str  # "org/repo"
    default_branch: str = "main"
    ecosystem: Ecosystem
    build_command: str
    test_command: str
    codeowners: list[str] = Field(default_factory=list)
    sandbox_image: str | None = None  # override the default build image for this repo
