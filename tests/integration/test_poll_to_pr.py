"""End-to-end happy path: a real ticket, a scratch repo, a real PR.

TODO(step 16): implement with testcontainers (postgres only) plus a
throwaway GitHub repo containing a known-vulnerable pom.xml.

  1. seed one JIRA ticket (mocked JiraClient.jql response)
  2. run `poll_once()`
  3. assert a branch exists, a PR is open, and the PR body states plainly
     that it has not been re-scanned
  4. assert JiraClient.transition was called with settings.jira_transition_done
  5. run poll_once() again with the same mocked ticket still returned by jql
     -> assert NO second PR (the UNIQUE constraint on jira_key is doing its job)
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="TODO(step 16)")
async def test_poll_to_pr_happy_path() -> None: ...


@pytest.mark.skip(reason="TODO(step 16)")
async def test_ticket_still_in_jql_results_after_claim_does_not_duplicate() -> None: ...


@pytest.mark.skip(reason="TODO(step 16)")
async def test_persistent_build_failure_escalates_after_max_attempts() -> None: ...
