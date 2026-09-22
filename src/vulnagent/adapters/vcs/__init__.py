from vulnagent.adapters.vcs.base import VcsClient
from vulnagent.adapters.vcs.github_app import GitHubAppClient
from vulnagent.adapters.vcs.github_token import GitHubTokenClient


def get_vcs_client() -> VcsClient:
    """PAT client when VA_GITHUB_TOKEN is set, else anonymous-capable PAT client
    if no GitHub App is configured, else the GitHub App client."""
    from vulnagent.config import get_settings

    s = get_settings()
    if s.github_token.get_secret_value() or not s.github_app_id:
        return GitHubTokenClient()
    return GitHubAppClient()  # type: ignore[return-value]


__all__ = ["GitHubAppClient", "GitHubTokenClient", "VcsClient", "get_vcs_client"]
