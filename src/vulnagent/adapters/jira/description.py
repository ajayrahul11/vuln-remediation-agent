"""Parse the JIRA description table into (repo, CVE link) rows.

The description is an Atlassian Document Format (ADF) table, two columns:

    | Repo                                      | Vulnerability CVE Ticket           |
    | https://github.com/org/repo (smart link)  | https://app.opencve.io/cve/CVE-... |

Each cell holds a link (smart-link `inlineCard`, or a text node with a `link`
mark) or plain text. The header row and blank rows are skipped. Nothing here
interprets the CVE link -- that is cve/resolver.py's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class TicketParseError(ValueError):
    """The description isn't a table we can safely act on. Escalate; don't guess."""


@dataclass(frozen=True)
class TicketRow:
    repo_full_name: str
    cve_url: str


def _walk(node: Any, texts: list[str], links: list[str]) -> None:
    if isinstance(node, list):
        for child in node:
            _walk(child, texts, links)
        return
    if not isinstance(node, dict):
        return
    kind = node.get("type")
    if kind == "text":
        texts.append(node.get("text", ""))
        for mark in node.get("marks", []):
            if mark.get("type") == "link" and mark.get("attrs", {}).get("href"):
                links.append(mark["attrs"]["href"])
    elif kind in ("inlineCard", "blockCard", "embedCard"):
        url = node.get("attrs", {}).get("url")
        if url:
            links.append(url)
    _walk(node.get("content", []), texts, links)


def _cell(cell: dict[str, Any]) -> tuple[str, str | None]:
    """(visible text, first link) of one table cell."""
    texts: list[str] = []
    links: list[str] = []
    _walk(cell.get("content", []), texts, links)
    text = "".join(texts).strip()
    if links:
        return text, links[0]
    if text.startswith(("http://", "https://")):
        return text, text
    return text, None


def normalize_repo(value: str, default_org: str = "") -> str:
    """'https://github.com/org/repo(.git)' | 'org/repo' | 'repo' -> 'org/repo'."""
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        if parsed.hostname not in ("github.com", "www.github.com"):
            raise TicketParseError(f"repo link is not a github.com URL: {value!r}")
        value = parsed.path
    value = re.sub(r"\.git$", "", value.strip("/"))
    parts = value.split("/")
    if len(parts) == 1 and parts[0] and default_org:
        parts = [default_org, parts[0]]
    if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z0-9._-]+", p) for p in parts[:2]):
        raise TicketParseError(f"cannot read a repo name from {value!r}")
    return f"{parts[0]}/{parts[1]}"


def parse_description_table(description: Any, *, default_org: str = "") -> list[TicketRow]:
    if not isinstance(description, dict):
        raise TicketParseError("description is empty or not an ADF document")

    table = next((n for n in description.get("content", []) if n.get("type") == "table"), None)
    if table is None:
        raise TicketParseError("description has no table")

    rows: list[TicketRow] = []
    for row in table.get("content", []):
        cells = row.get("content", [])
        if len(cells) < 2 or any(c.get("type") == "tableHeader" for c in cells):
            continue
        repo_text, repo_link = _cell(cells[0])
        _, cve_link = _cell(cells[1])
        repo_raw = repo_link or repo_text
        if not repo_raw and not cve_link:
            continue  # blank row
        if not cve_link:
            raise TicketParseError(f"row for {repo_raw!r} has no CVE link")
        if not repo_raw:
            raise TicketParseError(f"row with CVE link {cve_link!r} has no repo")
        rows.append(TicketRow(normalize_repo(repo_raw, default_org), cve_link))

    if not rows:
        raise TicketParseError("table has no repo/CVE rows")
    return rows
