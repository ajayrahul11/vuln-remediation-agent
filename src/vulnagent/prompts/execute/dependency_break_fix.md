---
version: "1"
description: Adapt first-party call sites after a dependency bump introduced a breaking API change.
model: patcher
temperature: 0.0
---
A dependency was upgraded to resolve a security advisory. The upgrade compiled
cleanly in isolation but the project build now fails on changed API surface.
Adapt our call sites. Do not revert the upgrade, and do not change the version
in the manifest -- that part is already correct.

UPGRADE: {package} {old_version} -> {new_version}

BUILD OR TEST FAILURE:
<untrusted_content>
{build_error}
</untrusted_content>

RELEVANT SOURCE:
<untrusted_content>
{code_context}
</untrusted_content>

ALLOWED_FILES:
{allowed_files}

Adapt only the call sites named in the failure. If the new API has no
equivalent for what our code does, say so instead of guessing.

{safety_rails}
