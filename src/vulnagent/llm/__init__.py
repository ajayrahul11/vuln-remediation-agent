"""Lazy exports. guards is on the hot path (apply_fix); it must not drag in
the model stack for callers that only need injection scanning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vulnagent.llm.guards import scan_for_injection, wrap_untrusted

if TYPE_CHECKING:
    from vulnagent.llm.client import get_model

__all__ = ["get_model", "scan_for_injection", "wrap_untrusted"]


def __getattr__(name: str) -> Any:
    if name == "get_model":
        from vulnagent.llm.client import get_model as _get_model

        return _get_model
    raise AttributeError(name)
