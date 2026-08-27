import re

# Trailing store/terminal number, e.g. "Albert Heijn 1492" -> "Albert Heijn".
# Shared by extract_merchant() and normalize_merchant_name() so both agree on
# what counts as a "store number" suffix.
_TRAILING_STORE_NUMBER_RE = re.compile(r"\s+\d+$")


def normalize_merchant_name(name: str) -> str:
    """Normalize a merchant name for grouping: lowercased, terminal store
    number stripped. Used by the recurring-payment detector to group
    transactions that lack a stable counterparty IBAN."""
    stripped = _TRAILING_STORE_NUMBER_RE.sub("", name.strip())
    return stripped.lower()


def extract_merchant(omschrijving: str, tx_type: str, naam: str | None = None) -> str | None:
    """Extract a clean merchant name from a transaction."""
    if tx_type == "BEA":
        # BEA pattern: "Albert Heijn 1492     >ENSCHEDE  1.11.2025 17U55 ..."
        match = re.match(r"^(.+?)\s*>", omschrijving)
        if match:
            raw = match.group(1).strip()
            # Remove trailing store/terminal numbers: "Albert Heijn 1492" -> "Albert Heijn"
            cleaned = _TRAILING_STORE_NUMBER_RE.sub("", raw)
            # Handle "BCK*" prefix (third-party terminal): "BCK*AH-Wallerbosch" -> "AH-Wallerbosch"
            cleaned = re.sub(r"^BCK\*", "", cleaned)
            cleaned = re.sub(r"^CCV\*", "", cleaned)
            cleaned = re.sub(r"^SumUp\s*\*", "", cleaned)
            cleaned = re.sub(r"^Zettle_\*", "", cleaned)
            return cleaned.strip() or None
    elif tx_type == "RTI":
        # Refund: "Foot Locker 1316      >Enschede ..."
        match = re.match(r"^(.+?)\s*>", omschrijving)
        if match:
            raw = match.group(1).strip()
            cleaned = _TRAILING_STORE_NUMBER_RE.sub("", raw)
            return cleaned.strip() or None

    # For IDE, EIC, POV, etc. — use Naam field
    if naam:
        return naam.strip()

    return None
