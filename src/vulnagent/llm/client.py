"""Model router.

Only two prompts call this now: the break-fix retry (apply_fix) and the
escalation summary (escalate). Both want plain text back -- a diff, or a
short note -- not a validated JSON schema, so there is no structured-output
layer in this version. If you add a second decision point that needs a typed
response, that's when to bring back a with_structured_output() helper.

anthropic <-> bedrock on one env var, so a shop that forbids public egress for
source code runs the identical image against Bedrock instead.

TODO(step 10): add token accounting + a daily budget check + a circuit
breaker that trips after N consecutive failures. Budget exceeded should halt
and escalate, never silently skip the call.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from vulnagent.config import get_settings


@lru_cache
def get_model() -> BaseChatModel:
    s = get_settings()
    if s.llm_provider == "bedrock":
        from langchain_aws import ChatBedrockConverse

        return ChatBedrockConverse(model=s.llm_model_patcher, temperature=0, max_tokens=8192)

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=s.llm_model_patcher, temperature=0, max_tokens=8192, timeout=120)
