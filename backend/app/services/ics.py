import re

# Matches "ics" as a standalone word (case-insensitive), so "PICSNIC" does not
# match but "ICS" or "Betaalpas ICS Rekening" does.
_ICS_WORD_RE = re.compile(r"\bics\b", re.IGNORECASE)

# The full counterparty name International Card Services uses on statements.
_ICS_FULL_NAME = "international card services"


def is_ics_text(*parts: str | None) -> bool:
    """Config-free heuristic: does any of the given text fields refer to
    International Card Services (the ICS credit-card processor)?

    Matches either the full counterparty name ("International Card
    Services BV") or the standalone word "ics" (so "ICS" alone matches but
    "PICSNIC" does not, since "ics" there isn't a separate word)."""
    text = " ".join(p for p in parts if p)
    if not text:
        return False
    lowered = text.lower()
    if _ICS_FULL_NAME in lowered:
        return True
    return bool(_ICS_WORD_RE.search(text))
