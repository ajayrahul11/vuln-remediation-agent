"""Sandbox egress policy. The agent runs builds on untrusted-adjacent code.

Allow only what a build genuinely needs. Everything else is denied so a malicious
postinstall script in a bumped package cannot phone home or reach your VPC.
"""

from __future__ import annotations

ALLOWED_EGRESS = {
    "maven": ["repo.maven.apache.org", "repo1.maven.org"],
    "npm": ["registry.npmjs.org"],
    "pypi": ["pypi.org", "files.pythonhosted.org"],
    "go": ["proxy.golang.org", "sum.golang.org"],
    "common": ["github.com", "codeload.github.com"],
}

DENY_ALWAYS = ["169.254.169.254"]  # cloud instance metadata -- credential theft vector

RESOURCE_LIMITS = {
    "cpu": "2",
    "memory": "4g",
    "pids": 512,
    "timeout_seconds": 900,
    "read_only_root": True,
    "no_new_privileges": True,
    "drop_capabilities": ["ALL"],
}
