from __future__ import annotations

import httpx
import pytest

from vulnagent.cve import CveResolutionError, extract_cve_id, resolve_fixes
from vulnagent.domain import Ecosystem

CVE = {"id": "CVE-2021-44228", "aliases": [], "related": ["GHSA-jfh8-c2jp-5v3q"]}
GHSA = {
    "id": "GHSA-jfh8-c2jp-5v3q",
    "affected": [
        {
            "package": {"ecosystem": "Maven", "name": "org.apache.logging.log4j:log4j-core"},
            "ranges": [
                {"type": "ECOSYSTEM", "events": [{"introduced": "2.0-beta9"}, {"fixed": "2.3.1"},
                                                 {"introduced": "2.4"}, {"fixed": "2.12.2"},
                                                 {"introduced": "2.13.0"}, {"fixed": "2.15.0"}]}
            ],
        },
        {"package": {"ecosystem": "Maven", "name": "other:lib"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "9"}]}]},
    ],
}


def _client() -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        recs = {"CVE-2021-44228": CVE, "GHSA-jfh8-c2jp-5v3q": GHSA}
        rec = recs.get(req.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=rec) if rec else httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_extract_cve_id() -> None:
    assert extract_cve_id("https://app.opencve.io/cve/cve-2021-44228") == "CVE-2021-44228"
    assert extract_cve_id("https://example.com/x") is None


async def test_picks_fixed_version_of_the_range_containing_installed() -> None:
    deps = {"org.apache.logging.log4j:log4j-core": "2.14.1", "unrelated:thing": "1.0"}
    cve, fixes = await resolve_fixes(
        "https://app.opencve.io/cve/CVE-2021-44228", Ecosystem.MAVEN, deps, client=_client()
    )
    assert cve == "CVE-2021-44228"
    assert [(f.package, f.installed_version, f.fixed_version) for f in fixes] == [
        ("org.apache.logging.log4j:log4j-core", "2.14.1", "2.15.0")
    ]


async def test_already_fixed_or_absent_dependency_raises() -> None:
    with pytest.raises(CveResolutionError):
        await resolve_fixes(
            "https://x/CVE-2021-44228", Ecosystem.MAVEN,
            {"org.apache.logging.log4j:log4j-core": "2.17.0"}, client=_client(),
        )


async def test_unknown_cve_raises() -> None:
    with pytest.raises(CveResolutionError):
        await resolve_fixes(
            "https://x/CVE-2099-0001", Ecosystem.MAVEN, {"a:b": "1"}, client=_client()
        )
