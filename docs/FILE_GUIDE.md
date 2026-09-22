# File guide

**Status key:** DONE = written and working · STEP n = stub, implement at
step n of `TODO.md` · CONFIG = you edit values, not code.

---

## Root

| File | Status | What it is |
|---|---|---|
| `pyproject.toml` | DONE | No `redis`, `arq`, or `pgvector` — none are needed once ingestion is a poll and there's no code-retrieval executor. |
| `.env.example` | CONFIG | `VA_JIRA_POLL_JQL` is the query that decides what "scan all the JIRA tasks" actually scans. |
| `docker-compose.yml` | DONE | Postgres only. No worker service — `vulnagent poll` is a one-shot command, run by cron or a K8s CronJob, not a long-running container. |
| `Makefile` | DONE | `make poll-watch` loops it locally for dev convenience. |

---

## `config/`

| File | What it is |
|---|---|
| `catalog.example.yaml` | **Optional.** A repo not listed here is auto-detected from its manifest file. Add an entry only for a repo that needs a non-standard build/test command. |

---

## `domain/`

| File | Status | What it is |
|---|---|---|
| `finding.py` | DONE | The ticket, taken as authoritative. No `FindingEnrichment` — there's nothing left to enrich; the scanner already did that. |
| `repo_config.py` | DONE | Build/test commands for a repo. Not a security concept — a ticket never says how to build the code, so this is the one piece of operational metadata that still has to come from somewhere else. |
| `fix_target.py` | DONE | What `apply_fix` needs: the manifest path, and whether the package is direct or transitive. Produced by `prepare`. |
| `patch.py` | DONE | `PatchResult` and `ValidationReport`. No `rescan_ran` / `new_findings` fields — validation is build + test only. `tests_not_deleted` is still here; it's a regression guard, not a security check. |
| `enums.py` | DONE | Just `FindingStatus` and `Ecosystem`. No `RiskTier`, `AutonomyTier`, or `RemediationStrategy` — there's one strategy now (bump the dependency), so there's nothing to select between. |

---

## `adapters/jira/`

| File | Step | Needs |
|---|---|---|
| `client.py` | 5 (read), 6 (`jql`), 14 (write) | `VA_JIRA_*`. `jql()` is what "scan all the JIRA tasks" calls every poll cycle. |

No `parser.py` — that held webhook HMAC verification, which doesn't exist in
a poll-based design.

---

## `adapters/vcs/github_app.py`

STEP 8 (clone), then STEP 13 (branch/commit/push/PR). One clone per run,
reused by `apply_fix`, `validate`, and `publish_pr` — not re-cloned each
retry.

---

## `catalog/repo_config.py`

STEP 8. `detect_ecosystem()` looks for `pom.xml`, `package.json`,
`pyproject.toml`/`requirements.txt`, or `go.mod`. `RepoConfigResolver`
checks `config/catalog.yaml` first, falls back to detection. Neither source
resolving → escalate, never guess a build command.

---

## `graph/` — the orchestration layer

| File | Status | What it is |
|---|---|---|
| `state.py` | DONE | `RemediationState`. `last_failure` is new — it's how `validate`'s error reaches `apply_fix` on retry. |
| `builder.py` | DONE | Seven nodes, one conditional edge. `route_after_validate` is the entire decision logic: pass → publish, fail-and-under-budget → retry, fail-and-out-of-budget → escalate. |
| `checkpointer.py`, `runner.py` | DONE | Unchanged in shape from the original design. |

## `graph/nodes/` — one file per node

| File | Step | What it does |
|---|---|---|
| `ingest.py` | 5 | ticket → `Finding`. Pure field-mapping, no LLM. |
| `prepare.py` | 8 | clone, resolve build config, locate the manifest, baseline test count |
| `apply_fix.py` | 9, then 10 | mechanical bump (attempt 1); LLM break-fix (attempt 2+) |
| `validate.py` | 11 | build + test only |
| `publish_pr.py` | 13 | branch, commit, PR with the evidence body |
| `writeback.py` | 14 | JIRA comment + transition, on every terminal path |
| `escalate.py` | — (wired via `route_after_validate`) | hand-off note after `max_attempts` |

Gone from the original design: `enrich`, `reachability`, `triage`, `plan`,
`execute_config`, `execute_code`, `suppress` — each was there to support a
decision (which strategy, how much autonomy, is it exploitable) that no
longer needs making, because the ticket already settled it.

---

## `prompts/` — 6 files, down from 11

| File | Used by | Purpose |
|---|---|---|
| `system/base_operator.md` | the one LLM call site | Preamble: smallest change, never delete a test, `<untrusted_content>` is data not instruction. |
| `system/safety_rails.md` | same | `ALLOWED_FILES`, diff-only output. |
| `execute/dependency_break_fix.md` | step 10 | The only "creative" prompt left. Explicitly told not to touch the version — that part is already correct. |
| `publish/pr_body.md` | step 13 | Template, not a completion. States plainly that the PR hasn't been re-scanned. |
| `publish/jira_comment.md` | step 14 | Same idea for the ticket comment. |
| `publish/escalation_summary.md` | escalate | The one place a model writes prose for a human. |

Removed: `triage/*` (reachability judgment, ticket classification — no more
reachability, and field mapping in `ingest.py` is now a deterministic parse
against known custom fields), `plan/select_strategy.md` (nothing to select
between), `validate/failure_diagnosis.md` (the retry always tries the same
thing — adapt call sites — so there's no branch to classify toward).

---

## `llm/`

| File | Status | What it is |
|---|---|---|
| `guards.py` | DONE | Narrower role than before: the ticket description no longer reaches any decision-making prompt, so the highest-value injection surface from the original design is closed by the architecture itself, not by this module. What's left: build error text and source snippets passed to the break-fix prompt. |
| `client.py` | STEP 10 | One model, one role (`patcher`) — no more `planner`/`cheap` split, since there's no planning call. |

No `structured.py`. Both remaining prompts return plain text (a diff, or
prose) — neither is a validated JSON schema, so there's no structured-output
layer to build.

---

## `sandbox/`, `validation/`

Unchanged in shape. `validation/` dropped `rescan.py` and `diff.py` — that
proof now lives in your CI pipeline, outside this system.

---

## `persistence/`

Four tables instead of five — no `repo_embedding`, since there's no
code-retrieval executor to feed. `claim_ticket()` in `audit.py` is the
dedup mechanism: an `INSERT ... ON CONFLICT (jira_key) DO NOTHING`. No
Redis, no queue — a poll-based system doesn't need one.

---

## `worker/poller.py`

**New.** Replaces `arq_app.py` + `tasks.py`. `poll_once()`: run the JQL,
claim each result, run the graph for what you claimed. This file *is* "scan
all the JIRA tasks." No long-running worker process — `poll` runs, does its
work, exits; a scheduler outside the app decides when it runs again.

---

## `api/`

Trimmed to `health.py` and `runs.py`. No `jira_webhook.py` — there's no
push-based ingestion to receive.
