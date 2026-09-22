"""Hand back to a human. Never a silent drop.

`escalation(node, reason)` is the one way any node ends a run as escalated; the
graph then routes through this node to writeback, which comments on and
transitions the ticket. The reason is a deterministic message -- no model call
can fail and swallow an escalation.

TODO: LLM-written summary (prompts/publish/escalation_summary.md) with this
deterministic text as the fallback; assign/label per your JIRA workflow; metric.
"""

from __future__ import annotations

from vulnagent.graph.state import RemediationState
from vulnagent.logging import get_logger

log = get_logger(__name__)


def escalation(node: str, reason: str) -> dict:
    return {
        "terminal_status": "escalated",
        "escalation_reason": reason,
        "decisions": [{"node": node, "outcome": "escalated", "reason": reason}],
    }


async def run(state: RemediationState) -> dict:
    reason = state.get("escalation_reason")
    if not reason:  # arrived via the retry bound, not an explicit escalation
        attempts = state.get("attempt", 1)
        tail = (state.get("last_failure") or "")[-1500:]
        reason = f"build/tests still failing after {attempts} attempt(s):\n{tail}"
    log.warning("escalated", reason=reason[:500])
    return {
        "terminal_status": "escalated",
        "escalation_reason": reason,
        "decisions": [{"node": "escalate", "outcome": "escalated"}],
    }
