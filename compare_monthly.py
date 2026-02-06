"""Compare monthly Chase CSVs against YNAB transactions to find discrepancies.

This script reads monthly Chase CSV files and compares them to YNAB transactions
to identify:
- Transactions in Chase but missing from YNAB
- Transactions in YNAB but not in Chase
- Amount mismatches
"""

import os
import csv
from datetime import datetime
from collections import defaultdict
from decimal import Decimal
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()

MONTHLY_DIR = 'data/processed/chase-amazon/monthly'
BUDGET_ID = 'b35a5d8d-39ae-463c-9d76-fdf88182c6f7'
ACCOUNT_ID = '60e777c8-1a41-48af-8a35-b6dbb1807946'


def load_chase_monthly(year, month):
    """Load Chase transactions for a specific month."""
    month_names = {
        1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
        7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
    }
    filename = f'{year}-{month:02d}-{month_names[month]}.csv'
    filepath = os.path.join(MONTHLY_DIR, filename)

    if not os.path.exists(filepath):
        return None

    transactions = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            amount_str = row.get('Amount', '$0').replace('$', '').replace(',', '')
            try:
                amount = Decimal(amount_str)
            except:
                amount = Decimal('0')

            # Handle refunds as negative
            if row.get('Type') == 'Refund':
                amount = -amount

            transactions.append({
                'date': row.get('Date', ''),
                'amount': amount,
                'order_id': row.get('Order ID', ''),
                'type': row.get('Type', ''),
                'items': row.get('Items', '')[:50] if row.get('Items') else '',
                'category': row.get('Categories', '')
            })

    return transactions


def load_ynab_monthly(ynab, year, month):
    """Load YNAB transactions for a specific month."""
    start_date = f'{year}-{month:02d}-01'

    # Calculate end date (first of next month)
    if month == 12:
        end_year, end_month = year + 1, 1
    else:
        end_year, end_month = year, month + 1
    end_date = f'{end_year}-{end_month:02d}-01'

    all_transactions = ynab.get_transactions(BUDGET_ID, ACCOUNT_ID, since_date=start_date)

    # Filter to just this month
    transactions = []
    for t in all_transactions:
        if t.date.year == year and t.date.month == month:
            payee = t.payee_name or ''
            memo = t.memo or ''

            # Detect payments: positive amounts (inflows) with Transfer payee or payment memo
            # Also check for "Credit card payment" in memo
            is_payment = (
                t.amount > 0 and (
                    'Transfer' in payee or
                    'payment' in memo.lower() or
                    'Payment Thank You' in memo
                )
            )

            transactions.append({
                'date': t.date.strftime('%Y-%m-%d'),
                'amount': abs(t.amount),  # YNAB stores as negative for outflows
                'memo': memo,
                'payee': payee,
                'is_payment': is_payment
            })

    return transactions


def compare_month(chase_txns, ynab_txns, year, month):
    """Compare Chase and YNAB transactions for a month."""
    # Separate by type
    chase_purchases = [t for t in chase_txns if t['type'] not in ('Payment', 'Refund')]
    chase_refunds = [t for t in chase_txns if t['type'] == 'Refund']
    chase_payments = [t for t in chase_txns if t['type'] == 'Payment']

    ynab_purchases = [t for t in ynab_txns if not t['is_payment']]
    ynab_payments = [t for t in ynab_txns if t['is_payment']]

    # Group by date and amount for matching (use absolute value for amount)
    chase_by_key = defaultdict(list)
    for t in chase_purchases:
        key = (t['date'], round(abs(float(t['amount'])), 2))
        chase_by_key[key].append(t)

    ynab_by_key = defaultdict(list)
    for t in ynab_purchases:
        key = (t['date'], round(float(t['amount']), 2))
        ynab_by_key[key].append(t)

    # Also track refunds separately (match by absolute amount)
    chase_refund_by_key = defaultdict(list)
    for t in chase_refunds:
        key = (t['date'], round(abs(float(t['amount'])), 2))
        chase_refund_by_key[key].append(t)

    # Find mismatches
    missing_in_ynab = []
    extra_in_ynab = []
    unmatched_refunds = []

    # Check Chase purchases
    for key, chase_list in chase_by_key.items():
        ynab_list = ynab_by_key.get(key, [])
        if len(chase_list) > len(ynab_list):
            for i in range(len(chase_list) - len(ynab_list)):
                missing_in_ynab.append(chase_list[i])

    # Check YNAB transactions (exclude those that match refunds)
    for key, ynab_list in ynab_by_key.items():
        chase_list = chase_by_key.get(key, [])
        refund_list = chase_refund_by_key.get(key, [])
        # YNAB transaction matches if there's a purchase OR a refund
        expected_count = len(chase_list) + len(refund_list)
        if len(ynab_list) > expected_count:
            for i in range(len(ynab_list) - expected_count):
                extra_in_ynab.append(ynab_list[i])

    # Check for unmatched refunds
    for key, refund_list in chase_refund_by_key.items():
        ynab_list = ynab_by_key.get(key, [])
        if len(refund_list) > len(ynab_list):
            for i in range(len(refund_list) - len(ynab_list)):
                unmatched_refunds.append(refund_list[i])

    # Compare payments
    chase_payment_by_key = defaultdict(list)
    for t in chase_payments:
        key = (t['date'], round(abs(float(t['amount'])), 2))
        chase_payment_by_key[key].append(t)

    ynab_payment_by_key = defaultdict(list)
    for t in ynab_payments:
        key = (t['date'], round(float(t['amount']), 2))
        ynab_payment_by_key[key].append(t)

    missing_payments = []
    extra_payments = []

    for key, chase_list in chase_payment_by_key.items():
        ynab_list = ynab_payment_by_key.get(key, [])
        if len(chase_list) > len(ynab_list):
            for i in range(len(chase_list) - len(ynab_list)):
                missing_payments.append(chase_list[i])

    for key, ynab_list in ynab_payment_by_key.items():
        chase_list = chase_payment_by_key.get(key, [])
        if len(ynab_list) > len(chase_list):
            for i in range(len(ynab_list) - len(chase_list)):
                extra_payments.append(ynab_list[i])

    # Calculate totals
    chase_total = sum(abs(float(t['amount'])) for t in chase_purchases)
    chase_refund_total = sum(abs(float(t['amount'])) for t in chase_refunds)
    chase_payment_total = sum(abs(float(t['amount'])) for t in chase_payments)
    ynab_total = sum(float(t['amount']) for t in ynab_purchases)
    ynab_payment_total = sum(float(t['amount']) for t in ynab_payments)

    return {
        'chase_count': len(chase_purchases),
        'chase_refund_count': len(chase_refunds),
        'chase_payment_count': len(chase_payments),
        'ynab_count': len(ynab_purchases),
        'ynab_payment_count': len(ynab_payments),
        'chase_total': chase_total,
        'chase_refund_total': chase_refund_total,
        'chase_payment_total': chase_payment_total,
        'ynab_total': ynab_total,
        'ynab_payment_total': ynab_payment_total,
        'missing_in_ynab': missing_in_ynab,
        'extra_in_ynab': extra_in_ynab,
        'unmatched_refunds': unmatched_refunds,
        'missing_payments': missing_payments,
        'extra_payments': extra_payments
    }


def main():
    ynab = YNABClient(os.getenv('YNAB_TOKEN'))

    print("=" * 70)
    print("MONTHLY RECONCILIATION: Chase vs YNAB (Purchases Only)")
    print("=" * 70)

    total_chase = 0
    total_chase_refunds = 0
    total_ynab = 0
    all_missing = []
    all_extra = []
    all_unmatched_refunds = []

    # Process each month from Feb 2021 to Dec 2025
    for year in range(2021, 2026):
        start_month = 2 if year == 2021 else 1
        end_month = 12

        for month in range(start_month, end_month + 1):
            chase_txns = load_chase_monthly(year, month)
            if chase_txns is None:
                continue

            ynab_txns = load_ynab_monthly(ynab, year, month)

            result = compare_month(chase_txns, ynab_txns, year, month)

            total_chase += result['chase_total']
            total_chase_refunds += result['chase_refund_total']
            total_ynab += result['ynab_total']

            # Check for discrepancies
            has_issues = (result['missing_in_ynab'] or result['extra_in_ynab'] or
                         result['missing_payments'] or result['extra_payments'])

            if has_issues:
                print(f"\n{year}-{month:02d}: Purchases: Chase ${result['chase_total']:.2f} ({result['chase_count']}) | "
                      f"YNAB ${result['ynab_total']:.2f} ({result['ynab_count']})")

                if result['missing_in_ynab']:
                    print("  MISSING purchases in YNAB:")
                    for t in result['missing_in_ynab']:
                        print(f"    {t['date']} ${abs(float(t['amount'])):>8.2f}  {t['order_id']} {t['items'][:30]}")
                        all_missing.append({**t, 'year': year, 'month': month})

                if result['extra_in_ynab']:
                    print("  EXTRA purchases in YNAB:")
                    for t in result['extra_in_ynab']:
                        print(f"    {t['date']} ${float(t['amount']):>8.2f}  {t['memo'][:40]}")
                        all_extra.append({**t, 'year': year, 'month': month})

                if result['missing_payments']:
                    print("  MISSING payments in YNAB:")
                    for t in result['missing_payments']:
                        print(f"    {t['date']} ${abs(float(t['amount'])):>8.2f}")

                if result['extra_payments']:
                    print("  EXTRA payments in YNAB:")
                    for t in result['extra_payments']:
                        print(f"    {t['date']} ${float(t['amount']):>8.2f}  {t['memo'][:40]}")

                if result['unmatched_refunds']:
                    for t in result['unmatched_refunds']:
                        all_unmatched_refunds.append({**t, 'year': year, 'month': month})
            else:
                # Print summary for months without issues
                refund_note = f", {result['chase_refund_count']} refunds" if result['chase_refund_count'] else ""
                payment_note = f", {result['chase_payment_count']} payments" if result['chase_payment_count'] else ""
                print(f"{year}-{month:02d}: OK - ${result['chase_total']:.2f} ({result['chase_count']} purchases{refund_note}{payment_note})")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total Chase Purchases: ${total_chase:.2f}")
    print(f"Total Chase Refunds:   ${total_chase_refunds:.2f}")
    print(f"Net Chase:             ${total_chase - total_chase_refunds:.2f}")
    print(f"Total YNAB:            ${total_ynab:.2f}")
    print(f"\nMissing in YNAB: {len(all_missing)} transactions")
    print(f"Extra in YNAB:   {len(all_extra)} transactions")

    if all_missing:
        missing_total = sum(abs(float(t['amount'])) for t in all_missing)
        print(f"\nTotal missing amount: ${missing_total:.2f}")
        print("\nAll missing transactions:")
        for t in all_missing:
            print(f"  {t['year']}-{t['month']:02d} {t['date']} ${abs(float(t['amount'])):>8.2f}  {t['order_id']}")

    if all_extra:
        extra_total = sum(float(t['amount']) for t in all_extra)
        print(f"\nTotal extra amount:   ${extra_total:.2f}")


if __name__ == '__main__':
    main()
