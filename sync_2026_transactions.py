"""Sync 2026 Chase Amazon transactions to YNAB."""

import csv
import os
from datetime import datetime
from decimal import Decimal
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()


def main():
    token = os.getenv("YNAB_TOKEN")
    if not token:
        print("Error: YNAB_TOKEN not found in environment")
        return

    client = YNABClient(token)

    budget_id = "b35a5d8d-39ae-463c-9d76-fdf88182c6f7"
    account_id = "60e777c8-1a41-48af-8a35-b6dbb1807946"

    # Read CSV file
    csv_path = os.path.expanduser("~/Downloads/Chase8414_Activity20260121.CSV")
    transactions = []

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse date (MM/DD/YYYY -> YYYY-MM-DD)
            trans_date = datetime.strptime(row['Transaction Date'], '%m/%d/%Y').strftime('%Y-%m-%d')

            # Parse amount (CSV has negative amounts for purchases)
            amount = Decimal(row['Amount'])
            amount_milliunits = int(amount * 1000)

            # Clean up description for payee name
            description = row['Description']

            # Create import_id to prevent duplicates
            import_id = f"YNAB:{amount_milliunits}:{trans_date}:1"

            transaction = {
                "account_id": account_id,
                "date": trans_date,
                "amount": amount_milliunits,
                "payee_name": description,
                "memo": f"Imported from Chase CSV",
                "approved": False,  # Leave unapproved for review
                "import_id": import_id
            }
            transactions.append(transaction)
            print(f"  {trans_date}: {description} ${abs(amount):.2f}")

    print(f"\nTotal: {len(transactions)} transactions, ${sum(abs(Decimal(t['amount'])/1000) for t in transactions):.2f}")

    # Batch create transactions
    print("\nCreating transactions in YNAB...")
    result = client.create_transactions_batch(budget_id, transactions)

    created = result.get('transactions', [])
    duplicates = result.get('duplicate_import_ids', [])

    print(f"\nResults:")
    print(f"  Created: {len(created)} transactions")
    if duplicates:
        print(f"  Skipped (duplicates): {len(duplicates)}")

    print("\nDone!")


if __name__ == '__main__':
    main()
