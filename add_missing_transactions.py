"""Add missing transactions to YNAB for reconciliation."""

import os
from decimal import Decimal
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()

# IDs from previous reconciliation work
BUDGET_ID = "b35a5d8d-39ae-463c-9d76-fdf88182c6f7"
ACCOUNT_ID = "60e777c8-1a41-48af-8a35-b6dbb1807946"  # Chase Amazon

# Missing 2022 transactions ($70.40)
MISSING_2022 = [
    {
        "date": "2022-03-02",
        "payee_name": "Amazon",
        "amount": -5000,  # milliunits, negative for outflow
        "memo": "Order 114-6482719-2637056 (Delivery Tip - reconciliation)",
    },
    {
        "date": "2022-06-25",
        "payee_name": "Amazon",
        "amount": -990,  # $0.99
        "memo": "Order D01-2011426-9465850 (AMZN Digital - reconciliation)",
    },
    {
        "date": "2022-06-26",
        "payee_name": "Amazon",
        "amount": -64410,  # $64.41
        "memo": "Order 112-0216325-7789843 (reconciliation)",
    },
]

# Missing December 2022 transactions ($1,033.13)
# From the 01/04/23 statement - these are dated Dec 2022 but posted to Jan statement
MISSING_DEC_2022 = [
    {
        "date": "2022-12-04",
        "payee_name": "Amazon",
        "amount": -40720,  # $40.72
        "memo": "Order 112-7419003-9785040 (reconciliation)",
    },
    {
        "date": "2022-12-04",
        "payee_name": "Amazon",
        "amount": -19960,  # $19.96
        "memo": "Order 113-9937148-1259441 (reconciliation)",
    },
    {
        "date": "2022-12-08",
        "payee_name": "Amazon",
        "amount": -52990,  # $52.99
        "memo": "Order 112-5474000-5338609 (reconciliation)",
    },
    {
        "date": "2022-12-09",
        "payee_name": "Amazon",
        "amount": -7530,  # $7.53
        "memo": "Order 113-2769197-8249817 (reconciliation)",
    },
    {
        "date": "2022-12-08",
        "payee_name": "Amazon",
        "amount": -65390,  # $65.39
        "memo": "Order 112-5122266-3064260 (reconciliation)",
    },
    {
        "date": "2022-12-09",
        "payee_name": "Amazon",
        "amount": -50590,  # $50.59
        "memo": "Order 113-0430179-8281032 (reconciliation)",
    },
    {
        "date": "2022-12-09",
        "payee_name": "Amazon",
        "amount": -54680,  # $54.68
        "memo": "Order 113-0430179-8281032 (reconciliation)",
    },
    {
        "date": "2022-12-10",
        "payee_name": "Amazon",
        "amount": -376410,  # $376.41
        "memo": "Order 112-1540397-9726646 (reconciliation)",
    },
    {
        "date": "2022-12-11",
        "payee_name": "Amazon",
        "amount": -10000,  # $10.00
        "memo": "Order 112-1540397-9726646 (Delivery Tip - reconciliation)",
    },
    {
        "date": "2022-12-13",
        "payee_name": "Amazon",
        "amount": -73330,  # $73.33
        "memo": "Order 112-4716046-0515433 (reconciliation)",
    },
    {
        "date": "2022-12-14",
        "payee_name": "Amazon",
        "amount": -38120,  # $38.12
        "memo": "Order 113-0463040-5446660 (reconciliation)",
    },
    {
        "date": "2022-12-16",
        "payee_name": "Amazon",
        "amount": -22080,  # $22.08
        "memo": "Order 113-7896624-1169836 (reconciliation)",
    },
    {
        "date": "2022-12-19",
        "payee_name": "Amazon",
        "amount": -173310,  # $173.31
        "memo": "Order 112-5627733-5524203 (reconciliation)",
    },
    {
        "date": "2022-12-20",
        "payee_name": "Amazon",
        "amount": -10000,  # $10.00
        "memo": "Order 112-5627733-5524203 (Delivery Tip - reconciliation)",
    },
    {
        "date": "2022-12-21",
        "payee_name": "Amazon",
        "amount": -28600,  # $28.60
        "memo": "Order 112-4287600-0329001 (reconciliation)",
    },
    {
        "date": "2022-12-20",
        "payee_name": "Amazon",
        "amount": -9420,  # $9.42
        "memo": "Order 112-9440679-1578603 (reconciliation)",
    },
]

# Missing 2023 D01 transactions (Prime/subscriptions) - $222.91
MISSING_2023_D01 = [
    {
        "date": "2023-01-11",
        "payee_name": "Amazon Prime",
        "amount": -139000,  # $139.00
        "memo": "Order D01-2099050-9219419 (Amazon Prime - reconciliation)",
    },
    {
        "date": "2023-01-14",
        "payee_name": "Amazon Prime Video",
        "amount": -7990,  # $7.99
        "memo": "Order D01-0597095-7273857 (Prime Video - reconciliation)",
    },
    {
        "date": "2023-04-18",
        "payee_name": "Amazon Prime Video",
        "amount": -1740,  # $1.74
        "memo": "Order D01-8960034-0809865 (Prime Video - reconciliation)",
    },
    {
        "date": "2023-07-16",
        "payee_name": "Amazon Prime Video",
        "amount": -19990,  # $19.99
        "memo": "Order D01-8156727-5289803 (Prime Video - reconciliation)",
    },
    {
        "date": "2023-07-18",
        "payee_name": "Amazon Prime Video",
        "amount": -6990,  # $6.99
        "memo": "Order D01-0330919-3629056 (Prime Video Channels - reconciliation)",
    },
    {
        "date": "2023-08-06",
        "payee_name": "Amazon Prime Video",
        "amount": -3990,  # $3.99
        "memo": "Order D01-5883376-5126608 (Prime Video - reconciliation)",
    },
    {
        "date": "2023-08-08",
        "payee_name": "Amazon Kindle",
        "amount": -14990,  # $14.99
        "memo": "Order D01-7351203-9049808 (Kindle Svcs - reconciliation)",
    },
    {
        "date": "2023-08-20",
        "payee_name": "Amazon Prime Video",
        "amount": -3790,  # $3.79
        "memo": "Order D01-9106242-2973069 (Prime Video - reconciliation)",
    },
    {
        "date": "2023-09-18",
        "payee_name": "Amazon Prime Video",
        "amount": -4690,  # $4.69
        "memo": "Order D01-6387994-4294608 (Prime Video Channels - reconciliation)",
    },
    {
        "date": "2023-11-18",
        "payee_name": "Amazon Prime Video",
        "amount": -5960,  # $5.96
        "memo": "Order D01-6189180-4179410 (Prime Video Channels - reconciliation)",
    },
    {
        "date": "2023-11-26",
        "payee_name": "Amazon Prime Video",
        "amount": -9990,  # $9.99
        "memo": "Order D01-5401704-3737842 (Prime Video - reconciliation)",
    },
    {
        "date": "2023-11-26",
        "payee_name": "Amazon Prime Video",
        "amount": -3790,  # $3.79
        "memo": "Order D01-0232320-3693010 (Prime Video - reconciliation)",
    },
]


def add_transactions(transactions, description):
    """Add transactions to YNAB one at a time."""
    token = os.getenv("YNAB_TOKEN")
    if not token:
        print("Error: YNAB_TOKEN not found in environment")
        return False

    client = YNABClient(token)

    print(f"\n{description}")
    print(f"Adding {len(transactions)} transactions...")

    # Calculate total
    total = sum(t["amount"] for t in transactions) / -1000
    print(f"Total: ${total:.2f}")

    created_count = 0
    error_count = 0

    for t in transactions:
        try:
            amount = Decimal(t["amount"]) / 1000  # Convert milliunits to dollars
            result = client.create_transaction(
                budget_id=BUDGET_ID,
                account_id=ACCOUNT_ID,
                date=t["date"],
                amount=amount,
                payee_name=t["payee_name"],
                memo=t.get("memo"),
                approved=False,
                flag_color="yellow",
            )
            created_count += 1
            print(f"  Added: {t['date']} ${abs(t['amount']/1000):.2f} - {t['memo'][:50]}...")
        except Exception as e:
            error_count += 1
            print(f"  Error adding {t['date']}: {e}")

    print(f"\n  Created: {created_count} transactions")
    if error_count:
        print(f"  Errors: {error_count}")

    return error_count == 0


def main():
    print("=" * 60)
    print("Adding Missing Transactions to YNAB")
    print("=" * 60)

    # Add 2023 D01 (Prime/subscriptions) transactions
    success3 = add_transactions(
        MISSING_2023_D01,
        "2023 D01 Transactions - Prime/Subscriptions ($222.91)"
    )

    print("\n" + "=" * 60)
    if success3:
        print("All transactions added successfully!")
        print("\nTotal added: $222.91")
        print("\nNext steps:")
        print("1. Review the flagged transactions in YNAB")
        print("2. Categorize them appropriately")
        print("3. Approve once verified")
        print("4. Rebuild the reconciliation cache: python build_reconciliation_cache.py 2023")
    else:
        print("Some transactions failed to add. Check errors above.")


if __name__ == "__main__":
    main()
