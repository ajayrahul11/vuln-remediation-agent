from __future__ import annotations

import json
from pathlib import Path

import pytest

from vulnagent.adapters.jira.description import (
    TicketParseError,
    normalize_repo,
    parse_description_table,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "ticket_1.json"


def test_real_ticket_fixture_parses_one_row_and_skips_header_and_blank() -> None:
    desc = json.loads(FIXTURE.read_text())["fields"]["description"]
    rows = parse_description_table(desc)
    assert len(rows) == 1
    assert rows[0].repo_full_name == "ajayrahul11/springboot-log4j-fix"
    assert rows[0].cve_url == "https://app.opencve.io/cve/CVE-2026-49844"


def _table(*rows: list[list[dict]]) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableCell", "content": [{"type": "paragraph", "content": c}]}
                            for c in row
                        ],
                    }
                    for row in rows
                ],
            }
        ],
    }


def test_text_and_link_mark_cells_and_bare_repo_name() -> None:
    link = {"type": "text", "text": "CVE", "marks": [{"type": "link", "attrs": {"href": "https://x/CVE-2021-44228"}}]}
    desc = _table([[{"type": "text", "text": "payments-api"}], [link]])
    [row] = parse_description_table(desc, default_org="yourco")
    assert (row.repo_full_name, row.cve_url) == ("yourco/payments-api", "https://x/CVE-2021-44228")


def test_missing_cve_link_is_an_error_not_a_guess() -> None:
    desc = _table([[{"type": "text", "text": "org/repo"}], [{"type": "text", "text": "TBD"}]])
    with pytest.raises(TicketParseError):
        parse_description_table(desc)


@pytest.mark.parametrize("bad", [None, "plain text", {"type": "doc", "content": []}])
def test_no_table_is_an_error(bad: object) -> None:
    with pytest.raises(TicketParseError):
        parse_description_table(bad)


def test_normalize_repo() -> None:
    assert normalize_repo("https://github.com/o/r.git") == "o/r"
    with pytest.raises(TicketParseError):
        normalize_repo("https://gitlab.com/o/r")
    with pytest.raises(TicketParseError):
        normalize_repo("just-a-name")
