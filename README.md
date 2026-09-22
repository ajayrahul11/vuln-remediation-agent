# vulnagent

Fix JIRA-filed security findings: bump the dependency, build, test, open a PR.

```
JIRA poll -> ingest -> prepare -> apply_fix -> validate -> publish_pr -> writeback
                                       ^             |
                                       `--- retry ---+--escalate (after max attempts)
```

The scanner that filed the ticket has already resolved the vulnerability,
the package, and the fixed version. This system's job starts at *how* to
apply that fix — not *whether* to, and not confirming afterward that it
worked. Re-scanning happens in your existing PR pipeline; a human merge is
what actually closes the security loop.

---

## Read these in order

| Doc | What it answers |
|---|---|
| **[docs/DESIGN.md](docs/DESIGN.md)** | How it works: flow diagram, sequence diagram, external dependencies, data model, failure modes. **Start here.** |
| **[docs/FILE_GUIDE.md](docs/FILE_GUIDE.md)** | What every file is and what step implements it. |
| **[TODO.md](TODO.md)** | 16 sequential build steps, each with the credential it needs and the command that verifies it. |

---

## Quickstart

```bash
uv sync --extra dev
cp .env.example .env                        # VA_DRY_RUN=true by default
cp config/catalog.example.yaml config/catalog.yaml   # optional
make up && make migrate
make check                                   # ruff + mypy + pytest
uv run vulnagent poll                        # one poll pass, once credentials are wired
```

There's no long-running worker to start. `vulnagent poll` runs, processes
whatever JIRA's JQL returns, and exits — schedule it with cron or a
Kubernetes CronJob. `make poll-watch` loops it locally for development.

---

## Running it

The entry point is the `vulnagent` CLI (`vulnagent.cli:main`).

```bash
uv run vulnagent poll                          # one pass over JIRA, then exit (= make poll)
uv run vulnagent poll --watch --interval 900   # local loop (= make poll-watch)
uv run vulnagent run SCRUM-2                   # one ticket by hand, dry-run by default
uv run vulnagent run SCRUM-2 --no-dry-run      # really push a branch, open a PR, write to JIRA
uv run vulnagent validate-catalog              # lint config/catalog.yaml
make api                                       # optional FastAPI on :8080 (health + runs only)
```

Needed in `.env`:

- **Postgres:** `VA_DATABASE_URL` (`make up && make migrate`).
- **JIRA:** `VA_JIRA_BASE_URL`, `VA_JIRA_EMAIL`, `VA_JIRA_API_TOKEN`, `VA_JIRA_POLL_JQL`.
- **GitHub:** `VA_GITHUB_TOKEN`. It can be blank to clone a public repo, but pushing and opening PRs needs it.
- **LLM:** `ANTHROPIC_API_KEY`. It is only used on retries.
- **Docker:** must be running, because the sandbox defaults to Docker (`VA_SANDBOX_MODE`). `local` mode runs builds on your machine.
- **Safety:** `VA_DRY_RUN=true` keeps a run read-only. `VA_KILL_SWITCH=true` halts everything.

Start with `VA_DRY_RUN=true`. The run goes through validate and logs the PR
body, but writes nothing to GitHub or JIRA.

---

## Execution flow

```
cli.main()                                          cli.py
 └─ "poll" → poll_once()                            worker/poller.py
      ├─ kill switch on? → return 0
      ├─ JiraClient().jql(VA_JIRA_POLL_JQL)         → issues
      └─ for each issue:
          ├─ claim_ticket(jira_key, run_id)         INSERT on UNIQUE jira_key; skip if claimed
          └─ run_for_jira_issue()                   graph/runner.py
              ├─ parse the description table        → N rows (repo, CVE link)
              └─ for each row, sequentially: run_for_jira_key(row_index=i)
                  ├─ postgres_checkpointer() + build_graph()
                  ├─ graph.ainvoke(state)           thread_id = key:row:run_id
                  └─ record_run(status, attempt, repo)
```

`vulnagent run <KEY>` skips the poll and claim steps and calls
`run_for_jira_issue` directly.

### The LangGraph pipeline

Every node is wrapped by `audited()`, which appends a `decision_log` row.

```
START → ingest ──ok──→ prepare → apply_fix ──ok──→ validate ──pass──→ publish_pr → writeback → END
           │                        │                 │  ▲                             ▲
           └─escalated─┐            └─failed─┐        │  └─fail, attempt<max ──────────┘ (to apply_fix)
                       ▼                     ▼        └─fail, attempt==max─→ escalate ─┘
                    escalate ←───────────────┘
```

| Step | File | What it does |
|---|---|---|
| **ingest** | `graph/nodes/ingest.py` | Fetches the issue, parses the description table, and builds a `Finding` (repo, CVE link, CVE id) for `row_index`. A parse failure escalates. |
| **prepare** | `graph/nodes/prepare.py` | Clones the repo to `workdir/<run_id>/…`. Resolves build and test commands from the catalog or by auto-detection. Lists dependencies and resolves the CVE link to a package and fixed version via OSV. Locates the manifest and runs the tests once to record a baseline test count. Escalates if anything is unresolvable or the baseline already fails. |
| **apply_fix** | `graph/nodes/apply_fix.py` | Attempt 1 is a deterministic version bump (`fixers/`: maven, npm, pypi), with no LLM. On retry the LLM proposes a minimal diff. That diff may only touch source files named in the build error, never the manifest, and must pass `git apply --check`. Anything else is a hard failure. |
| **validate** | `graph/nodes/validate.py` | Runs the build, then the tests, in the sandbox. Guards against deleted tests by comparing the count to the baseline. Pass goes to `publish_pr`. Fail goes back to `apply_fix` while `attempt < VA_MAX_FIX_ATTEMPTS` (default 3), otherwise to `escalate`. |
| **publish_pr** | `graph/nodes/publish_pr.py` | In a dry run it logs the PR body and stops. Otherwise it creates branch `sec/<jira-key>-<cve>`, commits, pushes, and opens the PR. |
| **escalate** | `graph/nodes/escalate.py` | Records the reason and hands the ticket to a human. Never a silent drop. |
| **writeback** | `graph/nodes/writeback.py` | Always runs. Comments on the JIRA ticket and transitions it (`In Review` on PR open, `Needs Manual Fix` on escalation). A dry run writes nothing. |

An exception in one ticket is logged and the run is recorded as `failed`.
The poll pass then continues with the next ticket, and finally prints
`processed N ticket(s)`.

---

## What's here, and what isn't

Kept: LangGraph orchestration (the LLM never decides control flow), a
sandboxed build environment, the build+test validation gate with a
deleted-test guard, and an immutable audit trail.

Not here, on purpose: reachability analysis, threat-intel enrichment, risk
tiering, rescan-and-diff, and any push-based ingestion. All of these existed
in an earlier, broader version of this design to support decisions (which
strategy, how much autonomy, is this exploitable) that don't need making
once a ticket already carries the resolved fix. See `docs/DESIGN.md` for the
full list and the reasoning.

---

## The one thing to watch

This system trusts your PR pipeline's re-scan completely — it can't see your
CI at all. "Done" means the local build and tests passed and a PR is open,
not that the CVE is confirmed gone. Worth periodically confirming that
re-scan is actually wired the way you expect, since nothing here will notice
if it isn't. Full reasoning in `docs/DESIGN.md`, section 3.
