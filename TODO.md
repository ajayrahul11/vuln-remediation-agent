# Build guide — 16 sequential steps

Steps are strictly linear. Each lists: **Goal**, **External dependency**,
**Files**, **Code**, **Config**, **Verify** (the exact command), **Done when**.
Three **milestones** mark points where you stop and check before continuing.

This build assumes: the JIRA description holds a two-column table of
(repo, CVE link) rows. The package and fixed version are NOT on the ticket --
prepare resolves them from the CVE link (via OSV) against the cloned repo. There is no reachability analysis, no
threat-intel enrichment, and no re-scan inside this system — your existing
PR pipeline re-scans when the PR opens, and a human merge is what actually
closes the loop on the security side. "Done," here, means: local build and
tests passed, and a PR is open.

---
---

# PHASE 0 — Environment and credentials (steps 1–3)

No application code. Prove every external system is reachable before writing
anything that depends on it.

---

## Step 1 — Local environment

**Goal.** Postgres and the toolchain running. No Redis in this design —
Postgres's `UNIQUE` constraint on `jira_key` is the whole dedup mechanism,
since ingestion is a poll, not a webhook.

**External dependency.** Docker (for Postgres, and later the sandbox). Python
3.12+. `uv`.

**Config.**
```bash
cp .env.example .env
cp config/catalog.example.yaml config/catalog.yaml   # optional — see step 8
```

**Verify.**
```bash
uv sync --extra dev
make up                          # postgres only
docker compose ps                # "healthy"
uv run pytest tests/unit -v      # 24 passed
```

**Done when.** 24 unit tests pass. These test the parts that don't need a
live credential yet: domain models, the prompt registry, injection guards,
and the graph's retry-bound logic.

---

## Step 2 — JIRA credentials and ticket field mapping

**Goal.** Read a real ticket, and know exactly which field holds what.

**External dependency.** A JIRA service account.

| Thing | How to get it | Scope |
|---|---|---|
| API token | id.atlassian.com → Security → API tokens | — |
| Service account | ask your platform team for `svc-vulnagent@` | Browse + Comment + Transition on the SEC project only |
| Project key | wherever your scanner files tickets | — |

**Config.**
```
VA_JIRA_BASE_URL=https://yourco.atlassian.net
VA_JIRA_EMAIL=svc-vulnagent@yourco.com
VA_JIRA_API_TOKEN=<token>
```

**Verify.**
```bash
curl -su "$VA_JIRA_EMAIL:$VA_JIRA_API_TOKEN" \
  "$VA_JIRA_BASE_URL/rest/api/3/issue/SEC-1234" | jq '.fields'
```
Save three real tickets to `tests/fixtures/`, **anonymised**, and open them:
```bash
mkdir -p tests/fixtures
curl -su "$VA_JIRA_EMAIL:$VA_JIRA_API_TOKEN" \
  "$VA_JIRA_BASE_URL/rest/api/3/issue/SEC-1234" > tests/fixtures/ticket_1.json
jq '.fields | keys' tests/fixtures/ticket_1.json
```
Confirm `.fields.description` is an ADF table with one row per (repo, CVE
link). No custom fields are needed.

**Also decide your JQL.** What marks a ticket "ready for automated fixing"? A
label, a status, an issue type. Write it down — it becomes `VA_JIRA_POLL_JQL`.

**Done when.** You can point at the exact field for each of the five facts in
one real ticket, and you have a JQL query that returns only tickets meant for
this system.

---

## Step 3 — GitHub App, and LLM access

**Goal.** Mint a token, and get one model call working.

**External dependency — GitHub App.** Org Settings → Developer settings →
GitHub Apps → New.

| Setting | Value |
|---|---|
| Contents | Read and write |
| Pull requests | Read and write |
| Checks | Read only |
| Everything else | No access |
| Install on | one test repo, to start |

Download the `.pem` to `./secrets/github-app.pem` (already gitignored).

**External dependency — LLM.** Anthropic API key, or AWS Bedrock model access.
Bedrock is the usual answer if source code cannot leave your VPC.

**Config.**
```
VA_GITHUB_APP_ID=<app id>
VA_GITHUB_INSTALLATION_ID=<installation id>
VA_GITHUB_PRIVATE_KEY_PATH=./secrets/github-app.pem
VA_LLM_PROVIDER=anthropic        # or bedrock
ANTHROPIC_API_KEY=sk-ant-...
```

**Verify.**
```bash
uv run python -c "
from vulnagent.llm import get_model
print(get_model().invoke('Reply with exactly: OK').content)"
```
For GitHub, a throwaway JWT→token→`GET /installation/repositories` script
(delete it after — the real client lands in step 9).

**Done when.** The model prints `OK`, and you've minted one real GitHub App
token.

---
---

# PHASE 1 — Ingest and prepare (steps 4–8)

Goal: a ticket becomes a durable run row with a cloned repo and a known
target file to edit. Nothing is modified yet.

---

## Step 4 — Database and the dedup mechanism

**Goal.** The one thing that makes polling safe to run repeatedly.

**Files.** `persistence/models.py`, `persistence/audit.py`, an Alembic
migration.

**Code.** Four tables: `agent_run` (with a `UNIQUE` constraint on
`jira_key` — this *is* the dedup, no Redis needed), `finding_snapshot`,
`decision_log`, `audit_event`. In the migration:
```sql
REVOKE UPDATE, DELETE ON audit_event FROM vulnagent_app;
```
`persistence.audit.claim_ticket(jira_key, run_id)` does
`INSERT ... ON CONFLICT (jira_key) DO NOTHING RETURNING run_id` and returns
whether *this* call won the claim.

**Verify.**
```bash
make migrate
uv run python -c "
import asyncio
from vulnagent.persistence.audit import claim_ticket
print(asyncio.run(claim_ticket('SEC-4821','run-1')))   # True
print(asyncio.run(claim_ticket('SEC-4821','run-2')))   # False -- already claimed
"
psql \$VA_DATABASE_URL -c "UPDATE audit_event SET node='x';"   # must FAIL
```

**Done when.** The second claim returns `False`, and the audit table refuses
the UPDATE.

---

## Step 5 — Ticket parser and ingest node

**Goal.** A real ticket becomes a `Finding`.

**Files.** `adapters/jira/client.py` (`get_issue`), `graph/nodes/ingest.py`

**Code.** `adapters/jira/description.py` parses the table into
`(repo, cve_url)` rows; ingest builds a `Finding` for row `row_index`
(package/versions stay `None`). An unparseable table escalates, never guesses.

**Verify.** Test against your three saved fixtures:
```bash
uv run pytest tests/unit/test_ingest.py -v
```

**Tests to write.** One assertion per field, per fixture. A ticket missing
the fixed-version field → escalates, doesn't fall through with `None`.

**Done when.** All three fixtures parse into correct, complete `Finding`
objects.

---

## Step 6 — The poller — this is "scan all the JIRA tasks"

**Goal.** The entry point. No webhook in this design.

**Files.** `adapters/jira/client.py` (`jql`), `worker/poller.py`, `cli.py`
(already has the `poll` command wired)

**Code.** `jql(settings.jira_poll_jql)` → for each issue, `claim_ticket()` →
if claimed, `run_for_jira_key()`. Process tickets one at a time to start (see
the concurrency note already in `poller.py` — don't run two tickets against
the same repo concurrently).

**Verify.**
```bash
uv run vulnagent poll
```
Run it twice in a row with the same ticket still open in JIRA. The second
run must claim nothing (step 4 already proved the mechanism; this proves it
end to end).

**Done when.** Running `poll` twice processes the ticket exactly once.

---

## Step 7 — Sandbox runner

**Goal.** Run builds without risking the host.

**Files.** `sandbox/runner.py`, `sandbox/policies.py` (already written)

**Code.** One ephemeral container per command, egress allowlist per
ecosystem, `169.254.169.254` always blocked (cloud instance metadata — a
malicious `postinstall` script's favourite target), hard timeout, container
always removed.

**Why this still matters even though scanning is out of scope:** you are
still running `npm install` / `mvn` / `pip install` on a dependency graph you
didn't audit. That executes arbitrary third-party code on every single run,
regardless of whether you evaluate its security posture yourself.

**Verify.**
```bash
uv run python -c "
import asyncio
from vulnagent.sandbox import SandboxRunner
r = SandboxRunner()
print(asyncio.run(r.exec('/tmp/x', ['curl','-m','5','http://169.254.169.254/'], ecosystem='npm')))
print(asyncio.run(r.exec('/tmp/x', ['curl','-m','5','https://registry.npmjs.org/'], ecosystem='npm')))"
```
First call fails, second succeeds.

**Done when.** The egress test passes. Don't skip it.

---

## Step 8 — Prepare node: clone, detect, locate

**Goal.** Know where to make the change, before making it.

**External dependency.** The GitHub App from step 3.

**Files.** `catalog/repo_config.py` (`detect_ecosystem`,
`RepoConfigResolver`), `adapters/vcs/github_app.py` (`clone`),
`graph/nodes/prepare.py`

**Code.**
1. `RepoConfigResolver.resolve()`: check `config/catalog.yaml` first; if the
   repo isn't listed, `detect_ecosystem()` from the manifest file actually
   present (`pom.xml` → maven, `package.json` → npm, `pyproject.toml` /
   `requirements.txt` → pypi, `go.mod` → go)
2. Clone into a workdir that persists for the rest of the run
3. Run the test suite **once, before any change**, and record the count —
   this is the baseline `ValidationReport.tests_not_deleted` compares
   against later. Skip this and that guard has nothing to check against.
4. Determine direct vs. transitive: `mvn dependency:tree` / `npm ls --json`
   / `pip show`, inside the sandbox, searching for `finding.package`
5. Build `FixTarget` with the manifest path and dependency position

**This is not a security scan.** It's the same repo introspection any
automated change needs — "where do I write this, and how." No reachability
judgment, no vulnerability assessment.

**Verify.** Point at a real repo with the known package as both a direct and
a transitive dependency (two fixtures) and confirm both classify correctly.

**Done when.** `is_direct_dependency` is correct for both fixtures, and the
baseline test count is recorded.

---

> ## MILESTONE A
> A real ticket now produces a durable run row, a cloned repo, and a known
> target file — with nothing modified and nothing pushed. Demo this before
> continuing.

---
---

# PHASE 2 — Fix and validate (steps 9–12)

---

## Step 9 — Apply the fix, attempt 1: mechanical only

**Goal.** The common case, with zero LLM calls.

**Files.** `graph/nodes/apply_fix.py`

**Code.** One command per ecosystem, using `FixTarget`:

| Ecosystem | Direct | Transitive |
|---|---|---|
| Maven | `versions:use-dep-version -Dversion={fixed}` | `<dependencyManagement>` pin |
| npm | `npm install pkg@{fixed}` | `"overrides"` entry |
| PyPI | edit the pin in `requirements.txt`/`pyproject.toml` | same |
| Go | `go get pkg@{fixed} && go mod tidy` | same |

The package manager resolves the graph — this is a tool call, not a
generation. Emit `PatchResult(generated_by="deterministic")`.

**Verify.** Against a fixture repo with the known vulnerable manifest,
confirm the diff touches only that file.

**Done when.** Both direct and transitive fixtures produce a correct,
minimal diff.

---

## Step 10 — LLM break-fix, for retries only

**Goal.** Handle the case where the bump breaks compilation.

**External dependency.** LLM from step 3.

**Files.** `graph/nodes/apply_fix.py` (the retry branch), `llm/client.py`
(add budget + circuit breaker)

**Code.** On `state["attempt"] > 1`, read `state["last_failure"]` (the build
error from the previous `validate`) and call `execute.dependency_break_fix`,
asking for a unified diff adapting call sites — never a diff touching the
manifest version itself. Emit `PatchResult(generated_by="llm")`.

**Verify.** Craft a fixture where the bump compiles but a downstream call
site breaks; confirm attempt 2 fixes it and attempt 1's manifest change
survives untouched.

**Tests to write.** Malformed LLM output (not a valid diff) → hard fail,
never a guess. A diff touching the manifest itself → rejected.

**Done when.** The break-fix fixture resolves on attempt 2, and both guard
tests pass.

---

## Step 11 — Validate: build + test, that's the whole gate

**Goal.** No re-scan here — your PR pipeline does that.

**Files.** `validation/build.py`, `validation/tests.py`,
`graph/nodes/validate.py`

**Code.** Build, then test, in the sandbox. Parse the test count. Populate
`ValidationReport`. On failure, write the error into `state["last_failure"]`
for the next `apply_fix` attempt.

**Verify.** Craft a patch that deletes a test file — confirm the gate fails
on `tests_not_deleted`, not on the raw pass/fail.

**Done when.** That deleted-test fixture is rejected.

---

## Step 12 — Wire the retry loop

**Goal.** Confirm the bound actually holds end to end.

**Files.** none new — `route_after_validate` in `graph/builder.py` is already
written and already tested (`test_graph_topology.py`)

**Verify.** Force a persistent build failure (a fixture with no possible
fix) and confirm exactly `VA_MAX_FIX_ATTEMPTS` attempts happen, then
escalate — not one more, not one fewer.

**Done when.** The attempt count in `decision_log` matches the config
exactly.

---

> ## MILESTONE B
> A verified local branch exists — build passed, tests passed, nothing
> deleted — and nothing has been pushed anywhere. Inspect ten of these diffs
> by hand before continuing.

---
---

# PHASE 3 — Ship (steps 13–14)

---

## Step 13 — Publish the PR

**Goal.** Push the branch, open the PR.

**Files.** `adapters/vcs/github_app.py` (branch/commit/push/PR),
`graph/nodes/publish_pr.py`

**Code.** Branch `sec/{jira_key}`, signed commit, PR body from
`prompts/publish/pr_body.md`. **State plainly in the body that this PR has
not been re-scanned** and that your CI pipeline is expected to do that —
this one sentence is what stops "Done" from being misread as "verified."

**Verify.** `VA_DRY_RUN=true` first: confirm the full PR body logs and
nothing is pushed. Then flip to `false` on the one test repo.

**Tests to write.** Token never appears in captured logs.

**Done when.** A real PR exists on the test repo with the evidence body.

---

## Step 14 — JIRA writeback

**Goal.** Close the loop.

**Files.** `adapters/jira/client.py` (`add_comment`, `transition`),
`graph/nodes/writeback.py`

**Code.** Comment with the PR link, transition to
`VA_JIRA_TRANSITION_DONE` on success or `VA_JIRA_TRANSITION_ESCALATED` on
failure. **Runs on both paths** — a failed run still has to update its
ticket. This is where "if the build succeeds, the ticket is done" is
implemented: it's the transition name, nothing more.

**Verify.** Force one success and one escalation; confirm both update JIRA
and both write an audit row.

**Done when.** Both paths leave the ticket in the right state.

---

> ## MILESTONE C
> End to end on the test repo: `vulnagent poll` → PR opened → ticket
> transitioned. Do not point this at a real repo yet.

---
---

# PHASE 4 — Operate (steps 15–16)

---

## Step 15 — Kill switch and integration test

**Files.** `api/routes/runs.py`, `tests/integration/test_poll_to_pr.py`
(three cases already stubbed)

**Code.** `POST /admin/kill-switch`, audited. The three integration cases:
happy path, a ticket still in the JQL results after being claimed doesn't
duplicate, a persistent failure escalates at exactly `max_attempts`.

**Done when.** All three pass in CI, and the kill switch halts a new `poll`
call immediately.

---

## Step 16 — Deploy the poller

**External dependency.** Wherever you run scheduled jobs — a Kubernetes
CronJob, a cron entry, an EventBridge-scheduled ECS task.

**Code.** `vulnagent poll` as one command, on a schedule (every 15 minutes is
a reasonable start). It runs, processes whatever the JQL returns, exits.
There is no long-running worker to deploy — that's the trade you get for
ingestion being a poll instead of a push.

**Done when.** A scheduled run has processed a real ticket end to end.

---
---

## Ship gate

- [ ] `make check` green
- [ ] Ran `poll` in `dry_run=true` for a week against live tickets; a human
      compared every proposed diff to what they'd have done by hand
- [ ] Zero cases where a merged PR left the vulnerability in place (check
      this against your CI's own re-scan results, not inside this system)
- [ ] Audit row exists for every run in a 50-run soak, escalations included
- [ ] Kill switch verified

## What's deliberately not here

No reachability analysis, no OSV/EPSS/KEV enrichment, no risk tiering, no
autonomy matrix, no rescan-and-diff, no suppression flow, no Redis/queue. All
of that is real engineering if you later want to auto-fix without a scanner
having already resolved the version, or want the system itself to decide
what's safe to merge automatically. None of it is required for what you
described: fix, build, test, PR, let the existing pipeline verify.
