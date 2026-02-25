import re
from datetime import date

_reader = None


def get_reader():
    """Lazy-load EasyOCR reader (takes ~2s first time, ~1-2GB RAM)."""
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["nl", "en"], gpu=False)
    return _reader


def find_amount(text: str) -> float | None:
    """Find a European-format amount in text: '12,99' or '1.234,56'."""
    match = re.search(r"€?\s*(\d{1,3}(?:\.\d{3})*,\d{2})", text)
    if match:
        return float(match.group(1).replace(".", "").replace(",", "."))
    return None


def extract_date(texts: list[str]) -> str | None:
    """Extract date from OCR text lines."""
    for text in texts:
        # dd-mm-yyyy, dd/mm/yyyy, dd.mm.yyyy, dd-mm-yy
        match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", text)
        if match:
            d, m, y = match.groups()
            if len(y) == 2:
                y = "20" + y
            try:
                parsed = date(int(y), int(m), int(d))
                # Sanity: not in the future, not before 2020
                if date(2020, 1, 1) <= parsed <= date(2030, 12, 31):
                    return parsed.isoformat()
            except ValueError:
                continue
    return None


def extract_total(texts: list[str]) -> float | None:
    """Extract total amount, looking for keywords first, then largest amount."""
    total_keywords = ["totaal", "total", "te betalen", "subtotaal", "pin", "betaald"]

    for i, text in enumerate(texts):
        lower = text.lower()
        if any(kw in lower for kw in total_keywords):
            # Look for amount in same line
            amount = find_amount(text)
            if amount is not None:
                return amount
            # Look in next line
            if i + 1 < len(texts):
                amount = find_amount(texts[i + 1])
                if amount is not None:
                    return amount

    # Fallback: largest amount
    amounts = []
    for t in texts:
        a = find_amount(t)
        if a is not None:
            amounts.append(a)
    return max(amounts) if amounts else None


def extract_merchant(texts: list[str]) -> str | None:
    """Extract merchant name — usually first non-numeric, non-date lines."""
    skip_patterns = [
        r"^\d+[./-]\d+",  # date-like
        r"^€",  # amount
        r"^\d+,\d{2}$",  # just a price
        r"^(bon|kassabon|klantenbon|factuur|btw)",  # receipt headers
    ]
    for text in texts[:5]:  # Check first 5 lines
        text = text.strip()
        if len(text) < 2:
            continue
        skip = False
        for pat in skip_patterns:
            if re.match(pat, text, re.IGNORECASE):
                skip = True
                break
        if not skip and len(text) >= 3:
            return text
    return None


def extract_line_items(texts: list[str]) -> list[dict]:
    """Extract line items — lines with a description and price."""
    items = []
    skip_keywords = {"totaal", "subtotaal", "pin", "contant", "te betalen",
                     "btw", "statiegeld", "korting", "betaald", "retour",
                     "wissel", "change", "total"}

    i = 0
    while i < len(texts):
        text = texts[i]

        # Strategy 1: description and amount on same line
        match = re.match(r"^(.+?)\s{2,}(\d{1,3}(?:\.\d{3})*,\d{2})\s*$", text)
        if not match:
            match = re.match(r"^(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*$", text)

        if match:
            desc = match.group(1).strip()
            amount_str = match.group(2)
            if len(desc) >= 2 and not any(kw in desc.lower() for kw in skip_keywords):
                amount = float(amount_str.replace(".", "").replace(",", "."))
                items.append({"description": desc, "amount": amount, "quantity": 1})
            i += 1
            continue

        # Strategy 2: description on this line, amount on next line
        if i + 1 < len(texts):
            next_text = texts[i + 1].strip()
            amount_match = re.match(r"^(\d{1,3}(?:\.\d{3})*,\d{2})$", next_text)
            if amount_match:
                desc = text.strip()
                if len(desc) >= 2 and not any(kw in desc.lower() for kw in skip_keywords):
                    amount = float(amount_match.group(1).replace(".", "").replace(",", "."))
                    # Skip if desc looks like a date or pure number
                    if not re.match(r"^\d+[./-]\d+", desc) and not re.match(r"^\d+$", desc):
                        items.append({"description": desc, "amount": amount, "quantity": 1})
                        i += 2
                        continue

        i += 1

    return items


def process_receipt(image_path: str) -> dict:
    """Run OCR on a receipt image and extract structured data."""
    reader = get_reader()
    results = reader.readtext(image_path)

    # Filter low-confidence results
    texts = [text for (_, text, conf) in results if conf > 0.3]
    full_text = "\n".join(texts)

    return {
        "date": extract_date(texts),
        "total_amount": extract_total(texts),
        "merchant_name": extract_merchant(texts),
        "line_items": extract_line_items(texts),
        "raw_text": full_text,
    }
