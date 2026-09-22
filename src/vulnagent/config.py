"""Typed settings. Every knob is env-driven."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VA_", env_file=".env", extra="ignore", case_sensitive=False
    )

    env: Literal["local", "dev", "staging", "prod"] = "local"
    log_level: str = "INFO"

    dry_run: bool = True
    kill_switch: bool = False

    database_url: str = "postgresql+asyncpg://vulnagent:vulnagent@localhost:5432/vulnagent"

    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: SecretStr = SecretStr("")
    jira_poll_jql: str = 'project = SEC AND status = "To Do" AND labels = auto-remediate'
    jira_transition_done: str = "In Review"
    jira_transition_escalated: str = "Needs Manual Fix"

    # Used when a ticket row gives a bare repo name ("payments-api") not org/repo.
    github_default_org: str = ""
    osv_base_url: str = "https://api.osv.dev"

    # Personal access token (simplest for a personal repo). Fine-grained PAT with
    # Contents + Pull requests read/write on the target repo. Optional for
    # cloning a public repo; required to push and open the PR.
    github_token: SecretStr = SecretStr("")
    github_commit_name: str = "vulnagent"
    github_commit_email: str = "vulnagent@users.noreply.github.com"

    github_app_id: str = ""
    github_installation_id: str = ""
    github_private_key_path: Path = Path("./secrets/github-app.pem")

    llm_provider: Literal["anthropic", "bedrock"] = "anthropic"
    llm_model_patcher: str = "claude-sonnet-4-6"

    max_fix_attempts: int = Field(default=3, ge=1, le=5)
    daily_token_budget: int = 500_000
    sandbox_timeout_seconds: int = 900
    sandbox_mode: Literal["docker", "local"] = "docker"
    workdir_root: Path = Path("workdir")

    catalog_path: Path = Path("config/catalog.yaml")
    prompts_dir: Path | None = None  # None => packaged prompts


@lru_cache
def get_settings() -> Settings:
    return Settings()
