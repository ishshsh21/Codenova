"""
Class-audience detection.

A student often receives mail meant for a different class/division (e.g. a
"Class B: lab submission due Friday" notice while they are in Class A). That
mail is useful context but it is not the student's work, so it must never be
ranked as a high-priority task.

Given the user's own classes (free text such as "A", "Class A", "Div B",
"SY-A"), this module decides who a message is addressed to:

- MINE         the message names one of the user's classes
- OTHER_CLASS  the message names a class, and none of them are the user's
- GENERAL      no class is named (or the user hasn't listed any classes)

Only the subject and the opening of the body are inspected: that is where an
audience is stated ("Dear Class B students", "[SY-B] Practical schedule"),
and it avoids treating "see section 3" deep in a body as an audience.
"""
import re
from dataclasses import dataclass

MINE = "MINE"
OTHER_CLASS = "OTHER_CLASS"
GENERAL = "GENERAL"

AUDIENCE_SCAN_CHARS = 400

# Year prefixes used by Indian colleges (FY/SY/TY/LY, FE/SE/TE/BE) followed by
# the division letter: "SY-B". In mail the hyphen is required, otherwise
# ordinary capitalised words ("FYI", "FEB", "SEE") would read as classes;
# what the user types in their profile may omit it ("SYB", "sy b").
_YEAR = r"FY|SY|TY|LY|FE|SE|TE|BE"
_YEAR_DIV = re.compile(rf"\b({_YEAR})-([A-Z])\b")
_USER_YEAR_DIV = re.compile(rf"({_YEAR})([A-Z])")
# "Class B", "Div. A", "Division C", "Batch B2", "Group 3", "Section A".
# The keyword is case-insensitive; the identifier must be written in capitals
# (or digits) so ordinary words ("a class a day", "class is") don't match.
_KEYWORD_ID = re.compile(
    r"\b((?i:class|div|division|batch|group|section|sec))\b\.?\s*[-:#]?\s*([A-Z]{1,2}\d{0,2}|\d{1,2}[A-Z]?)\b"
)
_STRIP_WORDS = re.compile(r"\b(?:class|div|division|batch|group|section|sec)\b\.?", re.I)


@dataclass(frozen=True)
class ClassRef:
    year: str | None
    ident: str

    @property
    def label(self) -> str:
        return f"{self.year}-{self.ident}" if self.year else f"Class {self.ident}"

    def matches(self, other: "ClassRef") -> bool:
        if self.ident != other.ident:
            return False
        return self.year is None or other.year is None or self.year == other.year


def parse_user_class(entry: str) -> ClassRef | None:
    """Normalize one user-entered class ("Class A", "sy-a", "B2") to a ClassRef."""
    text = entry.strip().upper()
    if not text:
        return None
    year_div = _USER_YEAR_DIV.fullmatch(re.sub(r"[\s-]", "", text))
    if year_div:
        return ClassRef(year_div.group(1), year_div.group(2))
    ident = re.sub(r"[^A-Z0-9]", "", _STRIP_WORDS.sub("", text))
    return ClassRef(None, ident) if ident else None


def mentioned_classes(subject: str, body: str) -> list[ClassRef]:
    text = f"{subject}\n{body[:AUDIENCE_SCAN_CHARS]}"
    refs: list[ClassRef] = []
    for m in _YEAR_DIV.finditer(text):
        refs.append(ClassRef(m.group(1), m.group(2)))
    for m in _KEYWORD_ID.finditer(text):
        keyword, ident = m.group(1).lower(), m.group(2)
        # "Section 3" is almost always a document section, not an audience.
        if keyword in ("section", "sec") and ident[0].isdigit():
            continue
        refs.append(ClassRef(None, ident))
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(refs))


@dataclass(frozen=True)
class Audience:
    kind: str
    label: str
    reason: str | None


def detect_audience(subject: str, body: str, my_classes: list[str] | None) -> Audience:
    mine = [ref for ref in (parse_user_class(c) for c in (my_classes or [])) if ref]
    if not mine:
        return Audience(GENERAL, "", None)

    # Course codes or custom names ("CS201", "Robotics Club") the user listed
    # are matched literally, anywhere in the opening text.
    opening = f"{subject}\n{body[:AUDIENCE_SCAN_CHARS]}"
    for entry in my_classes or []:
        entry = entry.strip()
        if len(entry) >= 3 and re.search(rf"(?<!\w){re.escape(entry)}(?!\w)", opening, re.I):
            return Audience(MINE, entry, f"Addressed to your class ({entry})")

    mentioned = mentioned_classes(subject, body)
    if not mentioned:
        return Audience(GENERAL, "", None)

    for ref in mentioned:
        if any(ref.matches(own) for own in mine):
            return Audience(MINE, ref.label, f"Addressed to your class ({ref.label})")

    others = ", ".join(ref.label for ref in mentioned[:2])
    return Audience(OTHER_CLASS, others, f"For {others}, not your class: kept as info only")
