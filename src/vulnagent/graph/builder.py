"""The remediation graph.

Six real nodes plus escalate. One conditional edge. This is the whole thing:

    ingest -> prepare -> apply_fix -> validate --pass--> publish_pr -> writeback
                              ^            |
                              `--- retry --+--fail, attempt<max
                                           |
                                           `--fail, attempt==max--> escalate -> writeback

The LLM still never decides control flow -- it is only ever called inside
apply_fix, as a fallback when the deterministic bump breaks the build.
"""

from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from vulnagent.graph.nodes import apply_fix, escalate, ingest, prepare, publish_pr, validate, writeback
from vulnagent.graph.state import RemediationState
from vulnagent.persistence.audit import record_decision


def route_after_ingest(state: RemediationState) -> Literal["prepare", "escalate"]:
    return "escalate" if state.get("terminal_status") == "escalated" else "prepare"


def route_after_apply_fix(state: RemediationState) -> Literal["validate", "escalate"]:
    patch = state.get("patch")
    return "validate" if patch is not None and patch.succeeded else "escalate"


def route_after_validate(state: RemediationState) -> Literal["publish_pr", "apply_fix", "escalate"]:
    report = state.get("validation")
    if report is not None and report.all_gates_passed:
        return "publish_pr"
    if state.get("attempt", 1) >= state.get("max_attempts", 3):
        return "escalate"
    return "apply_fix"


def audited(name: str, fn):
    """Wrap a node so every execution -- escalate included -- appends a
    decision_log row. Skipped when the state has no run_id (bare unit tests)."""

    async def wrapper(state: RemediationState) -> dict:
        update = await fn(state)
        if run_id := state.get("run_id"):
            await record_decision(
                run_id,
                name,
                inputs={
                    "jira_key": state.get("jira_key"),
                    "row_index": state.get("row_index", 0),
                    "attempt": state.get("attempt", 1),
                },
                outputs={"outcome": _outcome(update), **update},
            )
        return update

    wrapper.__name__ = name
    return wrapper


def _outcome(update: dict) -> str | None:
    decisions = update.get("decisions") or []
    return decisions[-1].get("outcome") if decisions else update.get("terminal_status")


def build_graph(checkpointer: Checkpointer | None = None):
    g = StateGraph(RemediationState)

    g.add_node("ingest", audited("ingest", ingest.run))
    g.add_node("prepare", audited("prepare", prepare.run))
    g.add_node("apply_fix", audited("apply_fix", apply_fix.run))
    g.add_node("validate", audited("validate", validate.run))
    g.add_node("publish_pr", audited("publish_pr", publish_pr.run))
    g.add_node("writeback", audited("writeback", writeback.run))
    g.add_node("escalate", audited("escalate", escalate.run))

    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", route_after_ingest, ["prepare", "escalate"])
    g.add_edge("prepare", "apply_fix")
    g.add_conditional_edges("apply_fix", route_after_apply_fix, ["validate", "escalate"])

    g.add_conditional_edges("validate", route_after_validate, ["publish_pr", "apply_fix", "escalate"])

    g.add_edge("publish_pr", "writeback")
    g.add_edge("escalate", "writeback")
    g.add_edge("writeback", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())
