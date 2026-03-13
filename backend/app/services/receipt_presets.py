"""Receipt parsing presets for known store formats."""

import re

import pdfplumber


def _extract_pdf_lines(pdf_path: str) -> tuple[list[str], str]:
    """Extract text lines and full text from a PDF."""
    all_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                all_text.append(page_text)

    full_text = "\n".join(all_text)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    return lines, full_text


def _parse_dutch_amount(s: str) -> float:
    """Convert '12,99' or '1.234,56' to float."""
    return float(s.replace(".", "").replace(",", "."))


def parse_albert_heijn(pdf_path: str) -> dict:
    """Parse an Albert Heijn digital receipt PDF."""
    lines, full_text = _extract_pdf_lines(pdf_path)

    # --- Products: lines between BONUSKAART and first SUBTOTAAL ---
    line_items = []
    in_products = False
    for line in lines:
        upper = line.upper()
        if "BONUSKAART" in upper:
            in_products = True
            continue
        if "SUBTOTAAL" in upper and in_products:
            break
        if not in_products:
            continue

        # Match product lines: "2 KROK SCHNITZ 3,29 6,58 B" or "1 AH QUICHE 3,99"
        # Trailing letter (B = Bonus indicator) is optional
        match = re.match(
            r"^(\d+)\s+(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})"
            r"(?:\s+(\d{1,3}(?:\.\d{3})*,\d{2}))?\s*[A-Z]?\s*$",
            line,
        )
        if match:
            qty = int(match.group(1))
            desc = match.group(2).strip()
            amount1 = _parse_dutch_amount(match.group(3))
            amount2 = _parse_dutch_amount(match.group(4)) if match.group(4) else None

            if qty > 1 and amount2 is not None:
                # Two amounts: first is unit price, second is line total
                unit_price = amount1
            else:
                unit_price = amount1

            line_items.append({
                "description": desc,
                "amount": round(unit_price, 2),
                "quantity": qty,
            })

    # --- Voordeel (discount) ---
    voordeel_match = re.search(r"UW VOORDEEL\s+(\d{1,3}(?:\.\d{3})*,\d{2})", full_text)
    if voordeel_match:
        discount = _parse_dutch_amount(voordeel_match.group(1))
        line_items.append({
            "description": "Voordeel",
            "amount": round(-discount, 2),
            "quantity": 1,
        })

    # --- Koopzegels (savings stamps) ---
    koopzegels_match = re.search(
        r"(\d+)\s+KOOPZEGELS?\s+(\d{1,3}(?:\.\d{3})*,\d{2})", full_text
    )
    if koopzegels_match:
        stamp_amount = _parse_dutch_amount(koopzegels_match.group(2))
        line_items.append({
            "description": "Koopzegels",
            "amount": round(stamp_amount, 2),
            "quantity": 1,
        })

    # --- Total: first TOTAAL line that isn't BTW-related ---
    total_amount = None
    for line in lines:
        if re.match(r"^TOTAAL\s+(\d{1,3}(?:\.\d{3})*,\d{2})$", line):
            total_amount = _parse_dutch_amount(
                re.match(r"^TOTAAL\s+(\d{1,3}(?:\.\d{3})*,\d{2})$", line).group(1)
            )
            break

    # --- Date: dd-mm-yyyy in footer ---
    receipt_date = None
    for line in reversed(lines):
        date_match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", line)
        if date_match:
            d, m, y = date_match.groups()
            try:
                from datetime import date
                parsed = date(int(y), int(m), int(d))
                receipt_date = parsed.isoformat()
                break
            except ValueError:
                continue

    return {
        "date": receipt_date,
        "total_amount": total_amount,
        "merchant_name": "Albert Heijn",
        "line_items": line_items,
        "raw_text": full_text,
    }


PRESETS: dict[str, callable] = {
    "albert_heijn": parse_albert_heijn,
}
