from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    succeeded: bool
    diff: str = ""
    files_changed: list[str] = Field(default_factory=list)
    branch_name: str | None = None
    commit_sha: str | None = None
    generated_by: str = "deterministic"  # "deterministic" | "llm"
    error: str | None = None


class ValidationReport(BaseModel):
    """No PR without both gates. No rescan here -- that runs in your PR pipeline."""

    model_config = ConfigDict(extra="forbid")

    build_passed: bool = False
    tests_passed: bool = False
    test_count_before: int = 0
    test_count_after: int = 0

    duration_seconds: float = 0.0
    logs_excerpt: str = ""
    failures: list[str] = Field(default_factory=list)

    @property
    def tests_not_deleted(self) -> bool:
        """Guard against a 'fix' that makes the suite pass by removing coverage."""
        return self.test_count_after >= self.test_count_before

    @property
    def all_gates_passed(self) -> bool:
        return self.build_passed and self.tests_passed and self.tests_not_deleted
