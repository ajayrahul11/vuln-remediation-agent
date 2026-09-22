from __future__ import annotations

import json
from pathlib import Path

from vulnagent.catalog.dependencies import maven_declared, parse_maven_list
from vulnagent.fixers import maven, npm, pypi
from vulnagent.validation.tests import count_tests

POM = (Path(__file__).parent.parent / "fixtures" / "pom_log4j_property.xml").read_text()
CORE = "org.apache.logging.log4j:log4j-core"


def test_maven_property_version_moves_the_property_only() -> None:
    new, how = maven.bump_pom(POM, CORE, "2.17.1")
    assert "<log4j2.version>2.17.1</log4j2.version>" in new
    assert "${log4j2.version}" in new  # references untouched
    assert "property log4j2.version" in how
    assert new.replace("2.17.1", "2.13.1") == POM  # nothing else changed


def test_maven_literal_version() -> None:
    pom = "<project><dependencies><dependency><groupId>g</groupId><artifactId>a</artifactId>" \
          "<version>1.0</version></dependency></dependencies></project>"
    new, _ = maven.bump_pom(pom, "g:a", "1.1")
    assert "<version>1.1</version>" in new and "1.0" not in new


def test_maven_unversioned_dep_gets_a_management_pin() -> None:
    # spring-boot-starter-web has no <version> (parent-managed): must be pinned, and its
    # <exclusion> of starter-logging must not be mistaken for the dependency.
    new, how = maven.bump_pom(POM, "org.springframework.boot:spring-boot-starter-logging", "2.7.0")
    assert "<dependencyManagement>" in new and "dependencyManagement" in how
    assert new.count("<version>2.7.0</version>") == 1


def test_maven_existing_management_section_is_extended() -> None:
    pom = "<project><dependencyManagement><dependencies></dependencies></dependencyManagement></project>"
    new, _ = maven.bump_pom(pom, "g:a", "1")
    assert new.count("<dependencyManagement>") == 1 and "<artifactId>a</artifactId>" in new


def test_maven_declared_ignores_exclusions_and_parent() -> None:
    declared = maven_declared(POM)
    assert CORE in declared
    assert "org.springframework.boot:spring-boot-starter-logging" not in declared


def test_parse_maven_list() -> None:
    out = "\nThe following files have been resolved:\n   a.b:c:jar:1.2.3:compile\n   x:y:jar:tests:9.9:test\n"
    assert parse_maven_list(out) == {"a.b:c": "1.2.3", "x:y": "9.9"}


def test_pypi_pin_bump_handles_normalisation_and_extras() -> None:
    txt = "Django==3.0\nrequests[security]==2.0.0\nother==1\n"
    assert pypi.bump_pin(txt, "django", "3.2") == "Django==3.2\nrequests[security]==2.0.0\nother==1\n"
    assert pypi.bump_pin(txt, "requests", "2.31") == "Django==3.0\nrequests[security]==2.31\nother==1\n"
    assert pypi.bump_pin(txt, "missing", "1") is None


def test_npm_direct_keeps_range_prefix_and_transitive_uses_overrides() -> None:
    text = json.dumps({"dependencies": {"lodash": "^4.0.0"}}, indent=2)
    new, _ = npm.bump_package_json(text, "lodash", "4.17.21")
    assert json.loads(new)["dependencies"]["lodash"] == "^4.17.21"
    new, how = npm.bump_package_json(text, "minimist", "1.2.8")
    assert json.loads(new)["overrides"] == {"minimist": "1.2.8"} and "override" in how


def test_count_tests(tmp_path: Path) -> None:
    rep = tmp_path / "target" / "surefire-reports"
    rep.mkdir(parents=True)
    (rep / "TEST-a.xml").write_text('<testsuite tests="3"/>')
    (rep / "TEST-b.xml").write_text('<testsuite tests="4"/>')
    assert count_tests(str(tmp_path), "maven", "") == 7
    assert count_tests("", "pypi", "5 passed, 1 skipped in 0.2s") == 6
    assert count_tests("", "npm", "Tests:       2 passed, 12 total") == 12
    assert count_tests("", "go", "--- PASS: TestA\n--- FAIL: TestB\n") == 2
