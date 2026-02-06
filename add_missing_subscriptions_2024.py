"""Add missing subscription and small transactions to YNAB for 2024.

These are subscriptions and small charges that appear on statements but are missing from YNAB.
Reconciliation is a PRECISE process - every transaction must match exactly.
"""

import os
from decimal import Decimal
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()

# Missing transactions identified from statement comparison
MISSING_TRANSACTIONS = [
    # 02/04/24 statement (period 01/05/24 - 02/04/24)
    ("2024-01-08", 0.35, "114-0523457-0029059", "AMZN Mktp US"),
    ("2024-01-10", 136.48, "D01-8389496-9545837", "Amazon Prime Annual"),
    ("2024-01-18", 7.99, "D01-6670799-8781044", "Prime Video Channels"),
    ("2024-01-28", 18.05, "114-7021158-2922610", "AMZN Mktp US"),

    # 05/04/24 statement (period 04/05/24 - 05/04/24)
    ("2024-04-18", 5.90, "D01-0956768-4630627", "Prime Video Channels"),

    # 07/04/24 statement (period 06/05/24 - 07/04/24)
    ("2024-06-04", 21.25, "D01-4191457-1699451", "Amazon Prime Monthly"),
]


def main():
    token = os.getenv("YNAB_TOKEN")
    if not token:
        print("Error: YNAB_TOKEN not found in environment")
        return

    client = YNABClient(token)

    budget_id = "b35a5d8d-39ae-463c-9d76-fdf88182c6f7"
    account_id = "60e777c8-1a41-48af-8a35-b6dbb1807946"  # Chase Amazon

    total = sum(Decimal(str(t[1])) for t in MISSING_TRANSACTIONS)
    print(f"Adding {len(MISSING_TRANSACTIONS)} missing subscription/small transactions...")
    print(f"Total: ${total:.2f}")
    print()

    # Create transactions one at a time
    print("Creating transactions in YNAB...")
    created = 0
    failed = 0

    for date, amount, order_num, desc in MISSING_TRANSACTIONS:
        amount_dec = Decimal(str(amount))
        try:
            result = client.create_transaction(
                budget_id=budget_id,
                account_id=account_id,
                date=date,
                amount=-amount_dec,  # Negative for outflow
                payee_name="Amazon.com",
                memo=f"{order_num} | {desc}",
                approved=False
            )
            created += 1
            print(f"  [{created}] {date}: ${amount:.2f} - {desc}")
        except Exception as e:
            failed += 1
            print(f"  [FAILED] {date}: ${amount:.2f} - {desc}: {e}")

    print()
    print(f"Created: {created} transactions")
    if failed:
        print(f"Failed: {failed}")

    print()
    print("Done! Transactions added as unapproved for review in YNAB.")


if __name__ == "__main__":
    main()
