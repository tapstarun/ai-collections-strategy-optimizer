"""Responsible-AI guardrails for message generation.

Three jobs:
  1. redact_pii        — mask sensitive data BEFORE it ever reaches the LLM.
  2. sanitize_untrusted— neutralise borrower-supplied free text so it can't act as
                         instructions to the model (prompt-injection defence).
  3. check_output      — scan the LLM's reply for aggressive/threatening language or
                         leaked PII; on any hit the caller discards it and uses a safe
                         template instead.

Design principle: the LLM only ever produces *message text*. It can never change a
segment, action, or escalation. So even a successful prompt injection cannot alter a
financial decision — the worst case is bad text, which `check_output` catches.
"""
from __future__ import annotations

import re

# --- PII patterns (mask before sending to the LLM, and detect in its output) ---
_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("[EMAIL]", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # Order matters: detect long account/card/govt-id digit runs BEFORE phone, so a
    # 12-digit account isn't mislabelled as a phone number.
    ("[ID]", re.compile(r"\b\d{11,18}\b")),
    ("[PHONE]", re.compile(r"(?<!\d)(?:\+?\d[\s-]?){10}(?!\d)")),
]

# --- Prohibited tone: threatening / harassing / coercive language --------------
_PROHIBITED_TERMS: list[str] = [
    "arrest", "arrested", "jail", "prison", "police", "lawsuit", "sue you",
    "threat", "threaten", "seize", "repossess immediately", "ruin", "destroy",
    "consequences will be severe", "or else", "we will come", "harass",
    "shame", "worthless", "criminal", "warrant",
]

# --- Injection trigger phrases to strip from untrusted borrower text -----------
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)ignore (all |any )?(previous|prior|above) instructions"),
    re.compile(r"(?i)\bsystem\s*:"),
    re.compile(r"(?i)\b(assistant|user)\s*:"),
    re.compile(r"(?i)reveal (the )?(internal|system) (rules|prompt|instructions)"),
    re.compile(r"(?i)disregard .{0,30}(rules|instructions)"),
]


def redact_pii(text: str | None) -> str:
    """Replace emails, phones, and long ID numbers with masked placeholders."""
    if not text:
        return ""
    out = text
    for placeholder, pattern in _PII_PATTERNS:
        out = pattern.sub(placeholder, out)
    return out


def sanitize_untrusted(text: str | None) -> str:
    """Strip injection trigger phrases from borrower-supplied free text, then redact PII.

    The result is only ever embedded as clearly-delimited *data* in the prompt, never as
    instructions.
    """
    if not text:
        return ""
    cleaned = text
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[removed]", cleaned)
    return redact_pii(cleaned).strip()


def check_output(text: str) -> tuple[bool, str | None]:
    """Validate an LLM-generated message. Returns (is_safe, reason_if_unsafe)."""
    lowered = text.lower()
    for term in _PROHIBITED_TERMS:
        if term in lowered:
            return False, f"prohibited term: '{term}'"
    for _placeholder, pattern in _PII_PATTERNS:
        if pattern.search(text):
            return False, "output contains a PII-like pattern"
    if not text.strip():
        return False, "empty output"
    return True, None
