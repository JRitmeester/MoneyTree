import csv
import hashlib
from datetime import date, datetime
from io import StringIO

from .merchant import extract_merchant


def parse_euro(value: str) -> float:
    """Parse European number format: '1.096,41' -> 1096.41, '-21,04' -> -21.04."""
    if not value:
        return 0.0
    return float(value.replace(".", "").replace(",", "."))


def parse_date(value: str) -> date:
    """Parse dd-mm-yyyy date format."""
    return datetime.strptime(value.strip(), "%d-%m-%Y").date()


def compute_hash(tx: dict) -> str:
    """Compute deduplication hash from stable transaction fields."""
    key = f"{tx['datum']}|{tx['rekening']}|{tx['volgnummer']}|{tx['afschriftnummer']}"
    return hashlib.sha256(key.encode()).hexdigest()


def parse_asn_csv(file_content: bytes) -> list[dict]:
    """Parse an ASN Bank CSV export into a list of transaction dicts."""
    # Try UTF-8 with BOM first, fall back to latin-1
    try:
        text = file_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_content.decode("latin-1")

    reader = csv.reader(StringIO(text), delimiter=";", quotechar='"')
    header = next(reader)  # Skip header row

    transactions = []
    for row in reader:
        if not row or not row[0].strip():
            continue

        naam = row[3].strip() or None

        tx = {
            "datum": parse_date(row[0]),
            "rekening": row[1].strip(),
            "tegenrekening": row[2].strip() or None,
            "naam": naam,
            "adres": row[4].strip() or None,
            "postcode": row[5].strip() or None,
            "woonplaats": row[6].strip() or None,
            "valuta_saldo": row[7].strip(),
            "saldo_voor_boeking": parse_euro(row[8]),
            "valuta": row[9].strip(),
            "bedrag": parse_euro(row[10]),
            "verwerkingsdatum": parse_date(row[11]),
            "valutadatum": parse_date(row[12]),
            "code": row[13].strip(),
            "type": row[14].strip(),
            "volgnummer": row[15].strip(),
            "betalingskenmerk": row[16].strip() or None,
            "omschrijving": row[17].strip(),
            "afschriftnummer": row[18].strip(),
            "categorie": row[19].strip() if len(row) > 19 else "Overig",
        }
        tx["merchant_name"] = extract_merchant(tx["omschrijving"], tx["type"], tx["naam"])
        tx["import_hash"] = compute_hash(tx)
        transactions.append(tx)

    return transactions
