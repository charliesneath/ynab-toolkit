"""Generate monthly CSV files from yearly Chase Amazon transaction data.

This script reorganizes transactions by calendar month (Jan 1-31, Feb 1-28, etc.)
instead of statement period (5th to 4th), making it easier to compare with YNAB.
"""

import csv
import os
from datetime import datetime
from collections import defaultdict

INPUT_DIR = 'data/processed/chase-amazon'
OUTPUT_DIR = 'data/processed/chase-amazon/monthly'

MONTH_NAMES = {
    1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
    7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
}


def main():
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Collect all transactions by calendar month
    monthly_transactions = defaultdict(list)

    # Process yearly files
    for year in range(2021, 2026):
        filename = f'{year}-all.csv'
        filepath = os.path.join(INPUT_DIR, filename)

        if not os.path.exists(filepath):
            print(f"Skipping {filename} - not found")
            continue

        print(f"Processing {filename}...")

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames

            for row in reader:
                date_str = row.get('Date', '')
                if not date_str:
                    continue

                try:
                    date = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    print(f"  Skipping invalid date: {date_str}")
                    continue

                # Skip transactions before Feb 2021 (YNAB cutoff)
                if date < datetime(2021, 2, 1):
                    continue

                month_key = (date.year, date.month)
                monthly_transactions[month_key].append(row)

    # Write monthly files
    print(f"\nWriting monthly files to {OUTPUT_DIR}/...")

    total_files = 0
    total_transactions = 0

    for (year, month), transactions in sorted(monthly_transactions.items()):
        month_name = MONTH_NAMES[month]
        output_file = os.path.join(OUTPUT_DIR, f'{year}-{month:02d}-{month_name}.csv')

        # Sort transactions by date
        transactions.sort(key=lambda x: x.get('Date', ''))

        # Calculate totals
        month_total = 0
        for t in transactions:
            amount_str = t.get('Amount', '$0').replace('$', '').replace(',', '')
            try:
                amount = float(amount_str)
                if t.get('Type') == 'Refund':
                    month_total -= amount
                else:
                    month_total += amount
            except ValueError:
                pass

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(transactions)

        print(f"  {year}-{month:02d}: {len(transactions):3d} transactions, ${month_total:>8.2f}")
        total_files += 1
        total_transactions += len(transactions)

    print(f"\nCreated {total_files} monthly files with {total_transactions} total transactions")


if __name__ == '__main__':
    main()
