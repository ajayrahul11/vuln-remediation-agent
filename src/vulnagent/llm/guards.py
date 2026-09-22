"""Defence in depth for the two places free text still reaches a prompt: the
build/test error output and source context passed to the break-fix call.

The ticket description itself is no longer fed to any decision-making LLM --
apply_fix's attempt-1 path is purely mechanical -- so the highest-value
attack surface from the original design is already closed by the
architecture. This module covers what's left: a malicious dependency's build
output, or a source comment, could still carry injected text.

  L1 structure   -- only Finding.prompt_facts() reaches a prompt by default
  L2 delimiting  -- anything else goes through wrap_untrusted()
  L3 detection   -- a hit is recorded to the audit log; it downgrades nothing
                    automatically in this version, since there's no autonomy
                    tier left to downgrade -- every PR requires review anyway
  L4 capability  -- apply_fix may only touch the manifest (attempt 1) or the
                    files named in the build error (retry), enforced in the
                    executor itself
"""

from __future__ import annotations

import re

_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(the\s+)?(system|previous)",
    r"you\s+are\s+now\s+",
    r"new\s+(instructions?|system\s+prompt)",
    r"</?(system|assistant|human)>",
    r"<\|.*?\|>",
    r"approve\s+(this|the)\s+(pr|pull\s+request|change)",
    r"exfiltrat|curl\s+http|base64\s+-d",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]

_OPEN = "<untrusted_content>"
_CLOSE = "</untrusted_content>"


def scan_for_injection(text: str) -> list[str]:
    return [p.pattern for p in _COMPILED if p.search(text)]


def wrap_untrusted(text: str, *, max_chars: int = 12_000) -> str:
    cleaned = text.replace(_OPEN, "&lt;untrusted_content&gt;").replace(
        _CLOSE, "&lt;/untrusted_content&gt;"
    )
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n...[truncated]"
    return f"{_OPEN}\n{cleaned}\n{_CLOSE}"
