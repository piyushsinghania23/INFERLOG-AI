from __future__ import annotations

import re


PII_PATTERNS: list[tuple[str, str, str]] = [
    ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]"),
    ("phone", r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){2}\d{4}\b", "[REDACTED_PHONE]"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
    ("credit_card", r"\b(?:\d[ -]*?){13,16}\b", "[REDACTED_CARD]"),
]


def redact_pii(text: str | None) -> tuple[str | None, list[str]]:
    if text is None:
        return None, []

    redacted = text
    flags: list[str] = []

    for name, pattern, replacement in PII_PATTERNS:
        if re.search(pattern, redacted):
            redacted = re.sub(pattern, replacement, redacted)
            flags.append(name)

    unique_flags = sorted(set(flags))
    return redacted, unique_flags
