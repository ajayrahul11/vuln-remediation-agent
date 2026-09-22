"""The metrics worth watching in this simplified design.

TODO(step 15): register these Prometheus collectors and emit them from the
graph nodes (publish_pr, writeback, escalate, apply_fix).

  vulnagent_runs_total{status}            received | done | escalated | failed
  vulnagent_fix_acceptance_ratio          PRs merged without human edits / PRs opened
  vulnagent_escalations_total{reason}     build_failed | test_failed | unrecognised_ecosystem | ...
  vulnagent_deterministic_fix_ratio       PatchResult.generated_by == "deterministic" / total
                                          -- high is good and honest: most tickets
                                          should never need the LLM at all
  vulnagent_mttr_seconds                  ticket claimed -> PR opened
  vulnagent_run_cost_usd                  LLM spend, near-zero on the common path
  vulnagent_validation_failures_total{gate}   build | tests | tests_not_deleted
  vulnagent_injection_detections_total    guards.scan_for_injection() hits

Deliberately absent: a false-fix rate. This system has no visibility into
whether a merged PR actually resolved the CVE -- that lives in your CI
pipeline's own re-scan results, not here. If you want that number, it needs
to come from there, not from vulnagent.
"""
from __future__ import annotations
