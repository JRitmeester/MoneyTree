from difflib import SequenceMatcher

from ..models import Receipt, Transaction

CONFIDENCE_AUTO_LINK = 0.85
CONFIDENCE_SUGGEST = 0.50


def compute_match_score(receipt: Receipt, tx: Transaction) -> float:
    """Score 0-1 for how well a receipt matches a transaction."""
    score = 0.0

    # 1. Amount match (50% weight) — hard gate
    if receipt.total_amount is None or tx.bedrag is None:
        return 0.0

    tx_abs = abs(tx.bedrag)
    amount_diff = abs(receipt.total_amount - tx_abs)
    if amount_diff < 0.01:
        score += 0.50
    elif amount_diff < 0.10:
        score += 0.40
    else:
        return 0.0  # Amount mismatch is a dealbreaker

    # 2. Date proximity (30% weight)
    if receipt.date and tx.datum:
        day_diff = abs((receipt.date - tx.datum).days)
        if day_diff == 0:
            score += 0.30
        elif day_diff == 1:
            score += 0.20
        elif day_diff <= 3:
            score += 0.10

    # 3. Merchant name similarity (20% weight)
    if receipt.merchant_name and tx.merchant_name:
        ratio = SequenceMatcher(
            None,
            receipt.merchant_name.lower(),
            tx.merchant_name.lower(),
        ).ratio()
        score += 0.20 * ratio

    return score


def find_matches(
    unlinked_receipts: list[Receipt],
    unlinked_transactions: list[Transaction],
) -> list[dict]:
    """Find receipt-transaction matches, scored by confidence."""
    matches = []
    matched_tx_ids: set[int] = set()

    for receipt in unlinked_receipts:
        best_match = None
        best_score = 0.0

        for tx in unlinked_transactions:
            if tx.id in matched_tx_ids:
                continue

            score = compute_match_score(receipt, tx)
            if score > best_score and score >= CONFIDENCE_SUGGEST:
                best_score = score
                best_match = tx

        if best_match:
            matched_tx_ids.add(best_match.id)
            matches.append({
                "receipt_id": receipt.id,
                "transaction_id": best_match.id,
                "confidence": best_score,
                "auto_link": best_score >= CONFIDENCE_AUTO_LINK,
            })

    return matches
