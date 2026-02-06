"""Add missing December 2023 transactions to YNAB.

These transactions appear on the 01/04/24 statement but are missing from YNAB.
"""

import os
from decimal import Decimal
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()

# Missing transactions from 01/04/24 statement (Dec 4-31, 2023 + Jan 1 tip)
MISSING_TRANSACTIONS = [
    # Format: (date, amount, order_number, description)
    ("2023-12-04", 10.00, "111-4811339-2368245", "Amazon Tips"),
    ("2023-12-04", 7.09, "113-5853054-2345827", "AMZN Mktp US"),
    ("2023-12-09", 50.75, "113-1337352-4632222", "Amazon.com"),
    ("2023-12-09", 45.79, "112-7852205-3533025", "AMZN Mktp US"),
    ("2023-12-10", 209.53, "111-6560665-2005024", "Amazon.com"),
    ("2023-12-11", 22.40, "113-0613442-1995459", "Amazon.com"),
    ("2023-12-11", 10.00, "111-6560665-2005024", "Amazon Tips"),
    ("2023-12-11", 24.01, "114-5465129-3245007", "AMZN Mktp US"),
    ("2023-12-11", 7.38, "112-7165284-0539427", "AMZN Mktp US"),
    ("2023-12-11", 6.84, "113-9450268-7423455", "AMZN Mktp US"),
    ("2023-12-12", 42.51, "114-9723348-6320202", "Amazon.com"),
    ("2023-12-12", 43.53, "114-9723348-6320202", "Amazon.com"),
    ("2023-12-12", 52.59, "114-9723348-6320202", "Amazon.com"),
    ("2023-12-17", 13.80, "112-4954343-5278647", "AMZN Mktp US"),
    ("2023-12-17", 20.12, "112-9783112-2416259", "Amazon.com"),
    ("2023-12-17", 39.33, "113-9345033-1083426", "Amazon.com"),
    ("2023-12-18", 250.83, "111-3109195-5116224", "Amazon.com"),
    ("2023-12-18", 9.98, "112-9134673-4159429", "Amazon.com"),
    ("2023-12-18", 5.49, "114-6744955-0240263", "Amazon.com"),
    ("2023-12-18", 18.17, "112-9221069-3565850", "Amazon.com"),
    ("2023-12-18", 1.05, "D01-3861771-7069037", "Prime Video Channels"),
    ("2023-12-19", 7.65, "114-6298034-7361037", "Amazon.com"),
    ("2023-12-19", 10.00, "111-3109195-5116224", "Amazon Tips"),
    ("2023-12-20", 12.54, "114-7490866-0838635", "Amazon.com"),
    ("2023-12-20", 21.55, "112-5626841-8315450", "AMZN Mktp US"),
    ("2023-12-21", 12.54, "114-7509107-9734620", "Amazon.com"),
    ("2023-12-22", 30.82, "114-9702306-6058657", "AMZN Mktp US"),
    ("2023-12-22", 26.87, "113-2882661-2469869", "Amazon.com"),
    ("2023-12-22", 72.69, "112-2778268-6695455", "AMZN Mktp US"),
    ("2023-12-31", 11.23, "114-3317069-7759430", "AMZN Mktp US"),
    ("2023-12-31", 236.87, "111-6123795-3271435", "Amazon.com"),
]

# Note: The $10 tip on 01/01/24 is already in YNAB (the only transaction in 01/04/24 period)


def main():
    token = os.getenv("YNAB_TOKEN")
    if not token:
        print("Error: YNAB_TOKEN not found in environment")
        return

    client = YNABClient(token)

    budget_id = "b35a5d8d-39ae-463c-9d76-fdf88182c6f7"
    account_id = "60e777c8-1a41-48af-8a35-b6dbb1807946"  # Chase Amazon

    total = sum(Decimal(str(t[1])) for t in MISSING_TRANSACTIONS)
    print(f"Adding {len(MISSING_TRANSACTIONS)} missing December 2023 transactions...")
    print(f"Total: ${total:.2f}")
    print()

    # Create transactions one at a time for reliability
    print("Creating transactions in YNAB...")
    created = 0
    failed = 0

    for i, (date, amount, order_num, desc) in enumerate(MISSING_TRANSACTIONS):
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
            print(f"  [{created}] {date}: ${amount:.2f} - {order_num}")
        except Exception as e:
            failed += 1
            print(f"  [FAILED] {date}: ${amount:.2f} - {order_num}: {e}")

    print()
    print(f"Created: {created} transactions")
    if failed:
        print(f"Failed: {failed}")

    print()
    print("Done! Transactions added as unapproved for review in YNAB.")


if __name__ == "__main__":
    main()
