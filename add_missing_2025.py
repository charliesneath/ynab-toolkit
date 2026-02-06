"""Add missing transactions to YNAB for 2025.

Missing transactions identified from statement comparison:
- Subscriptions (Amazon Prime, Audible, Kindle, Prime Video) with D01 order numbers
- One marketplace purchase missing from YNAB
- One refund missing from YNAB

Reconciliation is a PRECISE process - every transaction must match exactly.
"""

import os
from decimal import Decimal
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()

# Missing transactions identified from statement comparison
MISSING_TRANSACTIONS = [
    # 02/04/25 statement (period 01/05/25 - 02/04/25)
    ("2025-01-10", 105.30, "D01-5728024-8086607", "Amazon Prime"),
    ("2025-02-03", 7.49, "D01-7953878-7737844", "Audible"),
    ("2025-02-03", 10.99, "D01-0724894-5664234", "Kindle Svcs"),

    # 06/04/25 statement (period 05/05/25 - 06/04/25)
    ("2025-05-31", 221.01, "111-2899878-8043410", "AMZN Mktp US"),

    # 08/04/25 statement (period 07/05/25 - 08/04/25)
    ("2025-07-04", 1.19, "D01-8902276-0326604", "Prime Video"),
    ("2025-08-02", 9.95, "D01-7298331-9456215", "Audible"),

    # 09/04/25 statement (period 08/05/25 - 09/04/25)
    ("2025-08-17", 4.99, "D01-0037113-0291469", "Prime Video Channels"),
]

# Refunds that need to be added (as inflow, positive amount)
REFUNDS = [
    # 02/04/25 statement - refund for order 112-0955510-8601833
    ("2025-01-15", 26.23, "112-0955510-8601833", "Refund"),

    # 10/04/25 statement - refund for order 112-3138202-5829045
    ("2025-09-19", 320.45, "112-3138202-5829045", "Refund"),
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

    total_purchases = sum(Decimal(str(t[1])) for t in MISSING_TRANSACTIONS)
    total_refunds = sum(Decimal(str(r[1])) for r in REFUNDS)
    net = total_purchases - total_refunds

    print(f"\nSummary:")
    print(f"  Purchases added: ${total_purchases:.2f}")
    print(f"  Refunds added: ${total_refunds:.2f}")
    print(f"  Net change: ${net:.2f}")
    print(f"  Total transactions created: {created}")
    print("\nDone! Transactions added as unapproved for review in YNAB.")


if __name__ == "__main__":
    main()
