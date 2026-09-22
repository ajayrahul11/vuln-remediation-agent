"""Branch, commit, push, open the PR.

  - honours settings.dry_run: logs the PR body, writes nothing to GitHub
  - uses whichever VCS client is configured (PAT or GitHub App)
  - branch name: sec/{jira_key}-{cve_id}; one branch per (repo, CVE) row
  - PR body rendered from prompts/publish/pr_body.md -- a template, not a
    completion. It states plainly that the PR has NOT been re-scanned.

TODO: request reviewers from RepoConfig.codeowners.
"""

from __future__ import annotations

from vulnagent.adapters.vcs import get_vcs_client
from vulnagent.config import get_settings
from vulnagent.graph.nodes.escalate import escalation
from vulnagent.graph.state import RemediationState
from vulnagent.logging import get_logger
from vulnagent.prompts import get_prompt

log = get_logger(__name__)


async def run(state: RemediationState) -> dict:
    settings = get_settings()
    finding = state["finding"]
    repo_config = state["repo_config"]
    patch = state["patch"]
    report = state["validation"]
    workdir = state["workdir"]

    suffix = (finding.cve_id or "fix").lower()
    branch = f"sec/{finding.jira_key}-{suffix}".lower()
    title = f"Security: bump {finding.package} to {finding.fixed_version} ({finding.cve_id})"

    def body(commit_sha: str) -> str:
        return get_prompt("publish.pr_body").render(
            cve_id=finding.cve_id or "n/a",
            jira_key=finding.jira_key,
            jira_url=finding.jira_url or "",
            run_id=state["run_id"],
            package=finding.package,
            installed_version=finding.installed_version,
            fixed_version=finding.fixed_version,
            severity=finding.severity or "n/a",
            change_summary=", ".join(patch.files_changed) or "see diff",
            build_status="passed" if report.build_passed else "failed",
            test_status="passed" if report.tests_passed else "failed",
            test_count_before=report.test_count_before,
            test_count_after=report.test_count_after,
            commit_sha=commit_sha,
            trace_url="n/a",
        )

    if settings.dry_run:
        log.info("dry_run_pr", repo=finding.repo_full_name, branch=branch, title=title,
                 body=body("<not committed>"))  # fmt: skip
        return {
            "terminal_status": "dry_run",
            "decisions": [{"node": "publish_pr", "outcome": "dry_run", "branch": branch}],
        }

    vcs = get_vcs_client()
    try:
        await vcs.create_branch(workdir, branch)
        sha = await vcs.commit_all(workdir, title, paths=patch.files_changed)
        await vcs.push(workdir, branch)
        pr_url = await vcs.open_pr(
            finding.repo_full_name, branch, repo_config.default_branch, title, body(sha), draft=False
        )
    except Exception as exc:  # never crash past writeback: the ticket must hear about it
        return escalation("publish_pr", f"fix validated locally but publishing failed: {exc}")
    return {
        "pr_url": pr_url,
        "terminal_status": "pr_open",
        "patch": patch.model_copy(update={"branch_name": branch, "commit_sha": sha}),
        "decisions": [{"node": "publish_pr", "outcome": "pr_open", "pr_url": pr_url}],
    }
