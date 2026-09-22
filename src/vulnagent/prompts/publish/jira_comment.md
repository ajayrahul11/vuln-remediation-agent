---
version: "1"
description: JIRA comment template posted on every terminal state.
temperature: 0.0
---
*vulnagent run {run_id}* — status: *{terminal_status}*

{outcome_line}

||Field||Value||
|Package|{package} {installed_version} -> {fixed_version}|
|Local build|{build_status}|
|Local tests|{test_status}|
|Attempts|{attempts}|

{evidence_block}

This reflects local build and test results only. The security fix is
confirmed once this repository's CI pipeline (which re-scans on the PR)
passes and the PR is merged.

Trace: {trace_url}
