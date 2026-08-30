"""
FR-13 Dependency Detection — lightweight keyword/co-reference heuristic.
(The TRD marks full semantic dependency reasoning as an LLM responsibility;
this module provides a deterministic MVP pass that catches the common
"X blocks Y" phrasing pattern, e.g. credentials -> deployment -> QA -> demo.)
"""
import re

BLOCK_PATTERNS = [
    re.compile(r"blocked until (.+?)(?:\.|,|$)", re.I),
    re.compile(r"blocked on (.+?)(?:\.|,|$)", re.I),
    re.compile(r"before we can (.+?)(?:\.|,|$)", re.I),
    re.compile(r"can't start until (.+?)(?:\.|,|$)", re.I),
]


def extract_dependency_phrases(text: str) -> list[str]:
    """Returns short phrases describing what a task is blocked on, for matching
    against other task titles during the linking pass in sync.py."""
    phrases = []
    for pattern in BLOCK_PATTERNS:
        for m in pattern.finditer(text):
            phrases.append(m.group(1).strip())
    return phrases
