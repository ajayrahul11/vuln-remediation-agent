---
version: "1"
description: Hand-off note for a human engineer when the mechanical fix could not be validated.
model: patcher
temperature: 0.0
---
Write a hand-off note for the engineer who will finish this manually.

FIX ATTEMPTED: {package} {installed_version} -> {fixed_version} in {repo_full_name}

WHAT WAS TRIED ACROSS {attempts} ATTEMPT(S):
{attempt_log}

LAST FAILURE:
<untrusted_content>
{last_failure}
</untrusted_content>

Write at most 120 words: what broke, what was already tried, and the most
likely next step. Name files and error types concretely. Do not apologise,
do not pad, do not restate the ticket.
