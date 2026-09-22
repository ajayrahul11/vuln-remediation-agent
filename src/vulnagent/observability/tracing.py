"""Langfuse tracing. Optional -- not one of the 16 core steps.

The run_id in the trace must match the one in the PR body and the JIRA
comment; that's what makes "why did this PR happen" answerable later.

TODO: CallbackHandler wired into the one LLM call site (apply_fix's
break-fix retry), trace URL surfaced in the PR and the JIRA comment.
"""
from __future__ import annotations
