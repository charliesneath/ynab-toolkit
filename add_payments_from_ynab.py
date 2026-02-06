"""Extract payment data from YNAB and add to monthly Chase CSVs."""

import os
import csv
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()

MONTHLY_DIR = 'data/processed/chase-amazon/monthly'
BUDGET_ID = 'b35a5d8d-39ae-463c-9d76-fdf88182c6f7'
ACCOUNT_ID = '60e777c8-1a41-48af-8a35-b6dbb1807946'

MONTH_NAMES = {
    1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
    7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
}


def main():
    ynab = YNABClient(os.getenv('YNAB_TOKEN'))

    print("Fetching YNAB transactions...")
    all_transactions = ynab.get_transactions(BUDGET_ID, ACCOUNT_ID, since_date='2021-02-01')

    # Find payment transactions (inflows to credit card = payments)
    # In YNAB, payments to a credit card are positive amounts (reducing debt)
    payments_by_month = defaultdict(list)

    for t in all_transactions:
        # Payments are positive amounts (inflows) that reduce credit card balance
        # They come from transfer accounts (checking) and have payment-related memos
        payee = t.payee_name or ''
        memo = t.memo or ''

        # Check if this is a payment (transfer from checking) vs a refund (from Amazon)
        is_transfer = 'Transfer' in payee
        is_payment_memo = 'payment' in memo.lower() or 'Payment Thank You' in memo

        # Payments: positive amounts that are transfers with payment memos
        if t.amount > 0 and is_transfer and is_payment_memo:
            month_key = (t.date.year, t.date.month)
            payments_by_month[month_key].append({
                'date': t.date.strftime('%Y-%m-%d'),
                'amount': float(t.amount),
                'memo': memo or 'Credit card payment'
            })

    total_payments = sum(len(v) for v in payments_by_month.values())
    print(f"Found {total_payments} payment transactions")

    # Update monthly CSV files
    print("\nUpdating monthly CSV files...")
    updated_count = 0

    for (year, month), payments in sorted(payments_by_month.items()):
        month_name = MONTH_NAMES[month]
        csv_path = os.path.join(MONTHLY_DIR, f'{year}-{month:02d}-{month_name}.csv')

        if not os.path.exists(csv_path):
            print(f"  Skipping {year}-{month:02d} - no CSV file")
            continue

        # Read existing data
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            existing = list(reader)

        # Check if payments already added
        has_payments = any(row.get('Type') == 'Payment' for row in existing)
        if has_payments:
            print(f"  {year}-{month:02d}: Already has payments")
            continue

        # Add payment rows
        payment_total = 0
        for payment in payments:
            payment_row = {field: '' for field in fieldnames}
            payment_row['Date'] = payment['date']
            payment_row['Amount'] = f"${payment['amount']:.2f}"
            payment_row['Type'] = 'Payment'
            payment_row['Status'] = 'OK'
            payment_row['Payee'] = 'Chase Payment'
            payment_row['Notes'] = payment['memo'][:50] if payment['memo'] else ''
            existing.append(payment_row)
            payment_total += payment['amount']

        # Sort by date
        existing.sort(key=lambda x: x.get('Date', ''))

        # Write back
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing)

        print(f"  {year}-{month:02d}: Added {len(payments)} payments (${payment_total:.2f})")
        updated_count += 1

    print(f"\nUpdated {updated_count} monthly files")


if __name__ == '__main__':
    main()
