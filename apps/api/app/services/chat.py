"""Chat helpers: repair-number mention parsing."""
import re

# Matches full numbers like TV-MSK-2026-01482 and short refs like #TV-MSK-01482
REPAIR_NUMBER_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{2,4})-([A-Z]{2,4})-(\d{4})-(\d{5})(?![A-Z0-9])"
)
SHORT_REF_RE = re.compile(r"#([A-Z]{2,4})-([A-Z]{2,4})-(\d{5})\b")


def extract_repair_ref(text: str) -> str | None:
    """Return the first repair reference found in the message text."""
    m = REPAIR_NUMBER_RE.search(text) or SHORT_REF_RE.search(text)
    return m.group(0).lstrip("#") if m else None
