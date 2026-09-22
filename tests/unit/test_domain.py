from __future__ import annotations

from vulnagent.domain import Finding, ValidationReport


def test_dedupe_key_is_stable(finding: Finding) -> None:
    assert finding.dedupe_key == finding.model_copy(deep=True).dedupe_key
    other = finding.model_copy(update={"jira_key": "SEC-9999"})
    assert other.dedupe_key != finding.dedupe_key


def test_prompt_facts_never_leaks_raw_description(finding: Finding) -> None:
    """The single most important guard in the codebase."""
    facts = finding.prompt_facts()
    assert "raw_description" not in facts
    assert finding.raw_description not in str(facts)


def test_validation_gate_requires_build_and_tests_and_no_deleted_tests() -> None:
    report = ValidationReport(
        build_passed=True, tests_passed=True, test_count_before=120, test_count_after=120
    )
    assert report.all_gates_passed

    assert not report.model_copy(update={"build_passed": False}).all_gates_passed
    assert not report.model_copy(update={"tests_passed": False}).all_gates_passed
    assert not report.model_copy(update={"test_count_after": 118}).all_gates_passed
