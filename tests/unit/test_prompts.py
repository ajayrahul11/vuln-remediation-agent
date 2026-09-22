"""Prompt hygiene, enforced in CI."""

from __future__ import annotations

import pytest

from vulnagent.prompts.registry import PromptRegistry

REGISTRY = PromptRegistry()
ALL = REGISTRY.all()


def test_registry_is_not_empty() -> None:
    assert len(ALL) == 6


@pytest.mark.parametrize("prompt", ALL, ids=lambda p: p.prompt_id)
def test_every_prompt_has_frontmatter(prompt) -> None:
    assert prompt.version
    assert prompt.description
    assert prompt.body


def test_untrusted_tags_are_balanced() -> None:
    for prompt in ALL:
        assert prompt.body.count("<untrusted_content>") == prompt.body.count(
            "</untrusted_content>"
        ), f"{prompt.prompt_id} has unbalanced untrusted_content tags"


def test_executor_prompt_forbids_manifest_edits() -> None:
    base = REGISTRY.get("system.base_operator").body.lower()
    rails = REGISTRY.get("system.safety_rails").body.lower()
    assert "delete a test" in base
    assert "allowed_files" in rails


def test_break_fix_prompt_says_not_to_touch_the_version() -> None:
    body = REGISTRY.get("execute.dependency_break_fix").body
    assert "do not change the version" in body.lower()


def test_missing_variable_fails_loudly() -> None:
    prompt = REGISTRY.get("execute.dependency_break_fix")
    with pytest.raises(ValueError, match="missing variable"):
        prompt.render(package="x")
