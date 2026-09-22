from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vulnagent.domain import Ecosystem, Finding, RepoConfig
from vulnagent.domain.fix_target import FixTarget


@pytest.fixture
def repo_config() -> RepoConfig:
    return RepoConfig(
        repo_full_name="yourco/payments-api",
        ecosystem=Ecosystem.MAVEN,
        build_command="mvn -B clean verify -DskipTests",
        test_command="mvn -B test",
        codeowners=["@yourco/payments-team"],
    )


@pytest.fixture
def finding() -> Finding:
    return Finding(
        jira_key="SEC-4821",
        cve_id="CVE-2015-7501",
        severity="critical",
        repo_full_name="yourco/payments-api",
        ecosystem=Ecosystem.MAVEN,
        package="commons-collections:commons-collections",
        installed_version="3.2.1",
        fixed_version="3.2.2",
        raw_description="Upgrade commons-collections to 3.2.2.",
        detected_at=datetime.now(UTC),
    )


@pytest.fixture
def fix_target(finding: Finding) -> FixTarget:
    return FixTarget(
        ecosystem=Ecosystem.MAVEN,
        package=finding.package,
        installed_version=finding.installed_version,
        fixed_version=finding.fixed_version,
        manifest_path="pom.xml",
        is_direct_dependency=True,
    )
