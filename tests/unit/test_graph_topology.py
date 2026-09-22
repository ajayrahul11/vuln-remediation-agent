"""The graph must compile, and the retry loop must actually be bounded."""

from __future__ import annotations

from vulnagent.domain import ValidationReport
from vulnagent.graph.builder import build_graph, route_after_validate


def test_graph_compiles() -> None:
    graph = build_graph()
    nodes = set(graph.get_graph().nodes)
    for expected in ("ingest", "prepare", "apply_fix", "validate", "publish_pr", "writeback", "escalate"):
        assert expected in nodes


def test_retry_is_bounded() -> None:
    failing = ValidationReport(build_passed=False)

    assert route_after_validate({"validation": failing, "attempt": 1, "max_attempts": 3}) == "apply_fix"
    assert route_after_validate({"validation": failing, "attempt": 3, "max_attempts": 3}) == "escalate"


def test_passing_validation_publishes() -> None:
    passing = ValidationReport(build_passed=True, tests_passed=True, test_count_before=10, test_count_after=10)
    assert route_after_validate({"validation": passing, "attempt": 1, "max_attempts": 3}) == "publish_pr"


def test_no_validation_report_yet_does_not_crash() -> None:
    # ingest/prepare/apply_fix haven't reached validate yet in some partial state
    assert route_after_validate({"attempt": 1, "max_attempts": 3}) == "apply_fix"


def test_ingest_and_apply_fix_failures_escalate() -> None:
    from vulnagent.domain import PatchResult
    from vulnagent.graph.builder import route_after_apply_fix, route_after_ingest

    assert route_after_ingest({"terminal_status": "escalated"}) == "escalate"
    assert route_after_ingest({}) == "prepare"
    assert route_after_apply_fix({"patch": PatchResult(succeeded=False)}) == "escalate"
    assert route_after_apply_fix({"patch": PatchResult(succeeded=True)}) == "validate"
    assert route_after_apply_fix({}) == "escalate"
