"""Bump a dependency in package.json: edit the spec if direct, else add an
`overrides` entry so the resolver picks the fixed version for the transitive dep."""

from __future__ import annotations

import json
import re


def bump_package_json(text: str, package: str, fixed: str) -> tuple[str, str]:
    data = json.loads(text)
    indent = 2
    if m := re.search(r"\n( +)\"", text):
        indent = len(m.group(1))
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        spec = data.get(section, {}).get(package)
        if spec is not None:
            prefix = re.match(r"^[\^~]", spec)
            data[section][package] = (prefix.group(0) if prefix else "") + fixed
            how = f"set {package} to {data[section][package]} in {section}"
            break
    else:
        data.setdefault("overrides", {})[package] = fixed
        how = f"add override {package} = {fixed}"
    return json.dumps(data, indent=indent) + "\n", how
