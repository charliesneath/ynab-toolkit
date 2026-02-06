"""Add final missing transactions to YNAB for 2024.

Reconciliation is a PRECISE process - every transaction must match exactly.
"""

import os
from decimal import Decimal
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()

# Final missing transactions identified from statement comparison
MISSING_TRANSACTIONS = [
    # 09/04/24 statement - Kindle charge (refund also exists, nets to $0)
    ("2024-08-22", 13.99, "D01-3591459-5753826", "Kindle Svcs"),

    # 12/04/24 statement - subscriptions
    ("2024-11-26", 3.99, "D01-9218283-5881866", "Audible"),
    ("2024-11-26", 3.99, "D01-3472594-0032264", "Kindle Svcs"),
]

# Refund that also needs to be added (as inflow, positive amount)
REFUNDS = [
    # 09/04/24 statement - Kindle refund
    ("2024-08-22", 13.99, "D01-3591459-5753826", "Kindle Svcs Refund"),
]


def main():
    token = os.getenv("YNAB_TOKEN")
    if not token:
        print("Error: YNAB_TOKEN not found in environment")
        return

    client = YNABClient(token)

    budget_id = "b35a5d8d-39ae-463c-9d76-fdf88182c6f7"
    account_id = "60e777c8-1a41-48af-8a35-b6dbb1807946"  # Chase Amazon

    # Add purchases (outflows)
    print(f"Adding {len(MISSING_TRANSACTIONS)} missing purchases...")
    created = 0
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
            print(f"  [{created}] {date}: -${amount:.2f} - {desc}")
        except Exception as e:
            print(f"  [FAILED] {date}: ${amount:.2f} - {desc}: {e}")

    # Add refunds (inflows)
    print(f"\nAdding {len(REFUNDS)} refunds...")
    for date, amount, order_num, desc in REFUNDS:
        amount_dec = Decimal(str(amount))
        try:
            result = client.create_transaction(
                budget_id=budget_id,
                account_id=account_id,
                date=date,
                amount=amount_dec,  # Positive for inflow (refund)
                payee_name="Amazon.com",
                memo=f"{order_num} | {desc}",
                approved=False
            )
            created += 1
            print(f"  [{created}] {date}: +${amount:.2f} - {desc}")
        except Exception as e:
            print(f"  [FAILED] {date}: ${amount:.2f} - {desc}: {e}")

    print(f"\nCreated: {created} transactions")
    print("Done!")


if __name__ == "__main__":
    main()
