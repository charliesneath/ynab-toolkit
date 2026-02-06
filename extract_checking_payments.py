"""
Extract Amazon card payments from Chase checking statements.
Matches them with Amazon card "Payment Thank You" transactions.
"""

import csv
from pathlib import Path
from datetime import datetime
from decimal import Decimal


def load_checking_payments(csv_path: Path, card_last4: str = None) -> list[dict]:
    """Load payments to credit card from checking CSV.

    Args:
        csv_path: Path to checking account CSV
        card_last4: Last 4 digits of card to match (from config_private.py)
    """
    # Load card identifier from config if not provided
    if card_last4 is None:
        try:
            from config_private import CARD_IDENTIFIERS
            card_last4 = CARD_IDENTIFIERS.get("amazon_card", "")
        except ImportError:
            card_last4 = ""

    payments = []

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            payee = row.get("Payee", "")
            # Match "Payment To Chase Card Ending IN XXXX" but exclude "Cancelled"
            if card_last4 and card_last4 in payee and "Cancelled" not in payee and "Payment To Chase Card" in payee:
                date_str = row.get("Date", "")
                outflow = row.get("Outflow", "").replace("$", "").replace(",", "").strip()

                if date_str and outflow:
                    try:
                        dt = datetime.strptime(date_str, "%m/%d/%Y")
                        payments.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "amount": Decimal(outflow),
                            "source": "checking",
                            "description": payee
                        })
                    except ValueError:
                        pass

    return payments


def load_amazon_payments(csv_dir: Path) -> list[dict]:
    """Load Payment Thank You transactions from Amazon card CSVs."""
    payments = []

    for csv_file in sorted(csv_dir.glob("ynab_amazon_*.csv")):
        with open(csv_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                payee = row.get("Payee", "")
                if "Payment Thank You" in payee:
                    date_str = row.get("Date", "")
                    inflow = row.get("Inflow", "").replace("$", "").replace(",", "").strip()

                    if date_str and inflow:
                        try:
                            dt = datetime.strptime(date_str, "%m/%d/%Y")
                            payments.append({
                                "date": dt.strftime("%Y-%m-%d"),
                                "amount": Decimal(inflow),
                                "source": "amazon_card",
                                "description": payee
                            })
                        except ValueError:
                            pass

    return payments


def match_payments(checking_payments: list[dict], amazon_payments: list[dict]) -> list[dict]:
    """Match checking outflows with Amazon card inflows by amount and date."""
    matched = []
    unmatched_amazon = list(amazon_payments)

    for cp in checking_payments:
        cp_date = datetime.strptime(cp["date"], "%Y-%m-%d")

        best_match = None
        best_diff = None

        for ap in unmatched_amazon:
            if ap["amount"] == cp["amount"]:
                ap_date = datetime.strptime(ap["date"], "%Y-%m-%d")
                diff = abs((cp_date - ap_date).days)
                if diff <= 3 and (best_diff is None or diff < best_diff):
                    best_match = ap
                    best_diff = diff

        if best_match:
            matched.append({
                "date": cp["date"],
                "amount": cp["amount"],
                "checking_date": cp["date"],
                "amazon_date": best_match["date"],
                "matched": True,
                "description": cp.get("description", "")
            })
            unmatched_amazon.remove(best_match)
        else:
            matched.append({
                "date": cp["date"],
                "amount": cp["amount"],
                "checking_date": cp["date"],
                "amazon_date": None,
                "matched": False,
                "source": "checking_only",
                "description": cp.get("description", "")
            })

    # Add unmatched Amazon payments
    for ap in unmatched_amazon:
        matched.append({
            "date": ap["date"],
            "amount": ap["amount"],
            "checking_date": None,
            "amazon_date": ap["date"],
            "matched": False,
            "source": "amazon_only",
            "description": ap.get("description", "")
        })

    return sorted(matched, key=lambda x: x["date"])


def write_transfer_csv(matched: list[dict], output_path: Path):
    """Write matched payments as YNAB transfer CSV (for checking account side)."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Payee", "Memo", "Outflow", "Inflow"])

        for m in matched:
            if m["matched"]:
                # Format date as MM/DD/YYYY
                dt = datetime.strptime(m["checking_date"], "%Y-%m-%d")
                date_str = dt.strftime("%m/%d/%Y")
                writer.writerow([
                    date_str,
                    "Transfer: Chase Amazon",
                    "Credit card payment",
                    f"{m['amount']:.2f}",
                    ""
                ])


def write_amazon_card_csv(matched: list[dict], output_path: Path):
    """Write Amazon card payment inflows CSV.

    - Matched payments: Transfer from checking
    - Unmatched payments: Generic 'Credit Card Payment' for manual review
    """
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Payee", "Memo", "Outflow", "Inflow"])

        for m in matched:
            # Skip checking-only (those are outflows from checking, not relevant to Amazon card)
            if m.get("source") == "checking_only":
                continue

            if m["matched"]:
                # Matched: Transfer from checking
                dt = datetime.strptime(m["amazon_date"], "%Y-%m-%d")
                date_str = dt.strftime("%m/%d/%Y")
                writer.writerow([
                    date_str,
                    "Transfer: Chase Checking",
                    "Credit card payment",
                    "",
                    f"{m['amount']:.2f}"
                ])
            elif m.get("source") == "amazon_only":
                # Unmatched Amazon payment: needs manual review
                dt = datetime.strptime(m["amazon_date"], "%Y-%m-%d")
                date_str = dt.strftime("%m/%d/%Y")
                writer.writerow([
                    date_str,
                    "Credit Card Payment",
                    "NEEDS REVIEW - source account unknown",
                    "",
                    f"{m['amount']:.2f}"
                ])


def main():
    checking_csv = Path("data/checking_all.csv")
    amazon_dir = Path("data/amazon")
    output_transfers_csv = Path("data/checking_amazon_transfers.csv")
    output_amazon_csv = Path("data/amazon_card_payments.csv")

    if not checking_csv.exists():
        print(f"Error: {checking_csv} not found")
        print("Run: python3.11 bank_to_ynab.py chase-checking 'data/chase checking/statements/'*.pdf -o data/checking_all.csv")
        return

    # Load checking payments
    print("Loading checking payments...")
    checking_payments = load_checking_payments(checking_csv)
    print(f"Found {len(checking_payments)} payments to credit card")

    # Load Amazon card payments
    print("\nLoading Amazon card payments...")
    amazon_payments = load_amazon_payments(amazon_dir)
    print(f"Found {len(amazon_payments)} 'Payment Thank You' transactions")

    # Match them
    print("\nMatching payments...")
    matched = match_payments(checking_payments, amazon_payments)

    # Report
    matched_count = sum(1 for m in matched if m["matched"])
    unmatched_checking = sum(1 for m in matched if not m["matched"] and m.get("source") == "checking_only")
    unmatched_amazon = sum(1 for m in matched if not m["matched"] and m.get("source") == "amazon_only")

    print(f"\nResults:")
    print(f"  Matched: {matched_count}")
    print(f"  Checking only (no Amazon match): {unmatched_checking}")
    print(f"  Amazon only (no checking match): {unmatched_amazon}")

    # Write CSVs
    write_transfer_csv(matched, output_transfers_csv)
    write_amazon_card_csv(matched, output_amazon_csv)

    print(f"\nOutput files:")
    print(f"  Checking transfers: {output_transfers_csv} ({matched_count} transfers)")
    print(f"  Amazon card payments: {output_amazon_csv} ({matched_count} transfers + {unmatched_amazon} unmatched)")

    print("\n" + "=" * 80)
    print("MATCHED PAYMENTS:")
    print("=" * 80)
    for m in matched:
        if m["matched"]:
            print(f"  {m['date']} ${m['amount']:>10.2f}  (checking: {m['checking_date']}, amazon: {m['amazon_date']})")

    if unmatched_checking:
        print("\n" + "=" * 80)
        print("UNMATCHED - Checking only (paid from checking, no match in Amazon card):")
        print("=" * 80)
        for m in matched:
            if not m["matched"] and m.get("source") == "checking_only":
                print(f"  {m['date']} ${m['amount']:>10.2f}  {m.get('description', '')}")

    if unmatched_amazon:
        print("\n" + "=" * 80)
        print("UNMATCHED - Amazon only (payment received, but not from this checking account):")
        print("=" * 80)
        for m in matched:
            if not m["matched"] and m.get("source") == "amazon_only":
                print(f"  {m['date']} ${m['amount']:>10.2f}  {m.get('description', '')}")


if __name__ == "__main__":
    main()
