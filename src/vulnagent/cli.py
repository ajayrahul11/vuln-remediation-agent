"""CLI. Two commands: `run` for driving one ticket by hand while developing,
`poll` for the real entry point.
"""

from __future__ import annotations

import argparse
import asyncio
import time


def main() -> None:
    parser = argparse.ArgumentParser(prog="vulnagent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run the graph for one JIRA issue key")
    run.add_argument("jira_key")
    run.add_argument("--no-dry-run", action="store_true")

    poll = sub.add_parser("poll", help="run one JQL poll pass; what a cron job invokes")
    poll.add_argument("--watch", action="store_true", help="loop locally instead of exiting")
    poll.add_argument("--interval", type=int, default=900)

    sub.add_parser("validate-catalog", help="lint config/catalog.yaml, if present")

    args = parser.parse_args()

    if args.cmd == "run":
        from vulnagent.graph.runner import run_for_jira_issue

        results = asyncio.run(run_for_jira_issue(args.jira_key, dry_run=not args.no_dry_run))
        for i, r in enumerate(results):
            print(f"[row {i}] {r.get('terminal_status')}", r.get("pr_url") or "")
            if r.get("escalation_reason"):
                print("  reason:", r["escalation_reason"][:800])
            for d in r.get("decisions", []):
                print("  -", d)
    elif args.cmd == "poll":
        from vulnagent.worker.poller import poll_once

        async def _loop() -> None:
            while True:
                n = await poll_once()
                print(f"processed {n} ticket(s)")
                if not args.watch:
                    return
                time.sleep(args.interval)

        asyncio.run(_loop())
    elif args.cmd == "validate-catalog":
        from vulnagent.catalog import RepoConfigResolver

        RepoConfigResolver.load()
        print("catalog OK (or absent -- auto-detection will be used for every repo)")
