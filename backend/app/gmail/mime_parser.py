"""
FR-04 MIME Processing.
Prefers text/plain, falls back to sanitized text/html, strips scripts/styles,
tracking pixels, quoted replies and (heuristically) signatures.
"""
import base64
import re
from bs4 import BeautifulSoup

QUOTE_MARKERS = [
    re.compile(r"^On .{0,80} wrote:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^From:\s.+\nSent:\s.+\nTo:\s.+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^>.*$", re.MULTILINE),
]

SIGNATURE_MARKERS = [
    re.compile(r"^--\s*$", re.MULTILINE),
    re.compile(r"^(Sent from my (iPhone|iPad|Android|Galaxy).*)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(Best regards|Regards|Thanks|Thank you|Cheers|Best),?\s*\n[\w .]{1,40}$",
               re.IGNORECASE | re.MULTILINE),
]


def _b64_decode(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "img", "head", "meta", "link"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return text


def strip_quoted_and_signature(text: str) -> str:
    earliest_cut = len(text)
    for pattern in QUOTE_MARKERS:
        m = pattern.search(text)
        if m:
            earliest_cut = min(earliest_cut, m.start())
    text = text[:earliest_cut]

    for pattern in SIGNATURE_MARKERS:
        m = pattern.search(text)
        if m:
            text = text[: m.start()]

    return text


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_body_from_payload(payload: dict) -> tuple[str, bool]:
    """
    Walk the Gmail `payload` MIME tree.
    Returns (normalized_plain_text_body, has_attachments).
    Prefers text/plain; falls back to sanitized text/html.
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []
    has_attachments = False

    def walk(part: dict):
        nonlocal has_attachments
        mime_type = part.get("mimeType", "")
        filename = part.get("filename") or ""
        body = part.get("body", {})

        if filename and body.get("attachmentId"):
            has_attachments = True

        if mime_type == "text/plain" and body.get("data"):
            plain_parts.append(_b64_decode(body["data"]))
        elif mime_type == "text/html" and body.get("data"):
            html_parts.append(_b64_decode(body["data"]))

        for sub_part in part.get("parts", []) or []:
            walk(sub_part)

    walk(payload)

    if plain_parts:
        raw = "\n".join(plain_parts)
    elif html_parts:
        raw = html_to_text("\n".join(html_parts))
    else:
        raw = ""

    cleaned = strip_quoted_and_signature(raw)
    cleaned = normalize_whitespace(cleaned)
    return cleaned, has_attachments


def parse_header(headers: list[dict], name: str) -> str:
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def parse_sender(from_header: str) -> tuple[str, str]:
    """'Jane Doe <jane@company.com>' -> ('Jane Doe', 'jane@company.com')"""
    match = re.match(r"^(.*?)<(.+?)>$", from_header.strip())
    if match:
        name = match.group(1).strip().strip('"')
        email = match.group(2).strip()
        return name, email
    return "", from_header.strip()
