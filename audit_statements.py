"""
Financial Auditor Script: Parse Chase Amazon statements and create authoritative monthly CSVs.

This script reads all statement PDFs and creates month-by-month CSV files that serve as the
source of truth for all Amazon card transactions.
"""

import os
import csv
import re
import pdfplumber
from datetime import datetime
from collections import defaultdict

STATEMENTS_DIR = 'data/amazon/statements'
OUTPUT_DIR = 'data/processed/chase-amazon/audit'

MONTH_NAMES = {
    1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
    7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
}


def get_statement_info(filename):
    """Extract statement date from filename like YYYYMMDD-statements-XXXX-.pdf"""
    match = re.match(r'(\d{4})(\d{2})(\d{2})', filename)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return datetime(year, month, day)
    return None


def parse_statement(pdf_path, statement_date, statement_filename):
    """Parse all transactions from a statement PDF."""
    transactions = []
    statement_summary = {}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ''
            for page in pdf.pages:
                full_text += (page.extract_text() or '') + '\n'

        # Extract statement summary
        prev_balance_match = re.search(r'Previous Balance\s*\$?([\d,]+\.\d{2})', full_text)
        if prev_balance_match:
            statement_summary['previous_balance'] = float(prev_balance_match.group(1).replace(',', ''))

        payments_match = re.search(r'Payment,?\s*Credits?\s*-?\$?([\d,]+\.\d{2})', full_text)
        if payments_match:
            statement_summary['payments_credits'] = float(payments_match.group(1).replace(',', ''))

        purchases_match = re.search(r'Purchases\s*\+?\$?([\d,]+\.\d{2})', full_text)
        if purchases_match:
            statement_summary['purchases'] = float(purchases_match.group(1).replace(',', ''))

        new_balance_match = re.search(r'New Balance\s*\$?([\d,]+\.\d{2})', full_text)
        if new_balance_match:
            statement_summary['new_balance'] = float(new_balance_match.group(1).replace(',', ''))

        period_match = re.search(r'Opening/Closing Date\s*(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})', full_text)
        if period_match:
            statement_summary['period_start'] = period_match.group(1)
            statement_summary['period_end'] = period_match.group(2)

        # Parse transactions
        lines = full_text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Pattern for transaction: MM/DD followed by description and amount
            # Payment pattern: 02/25 Payment Thank You - Web -436.62
            payment_match = re.search(r'(\d{2}/\d{2})\s+Payment\s+Thank\s+You.*?-(\d[\d,]*\.\d{2})', line)
            if payment_match:
                date_str = payment_match.group(1)
                amount = float(payment_match.group(2).replace(',', ''))
                full_date = get_full_date(date_str, statement_date)

                transactions.append({
                    'date': full_date,
                    'type': 'Payment',
                    'amount': -amount,  # Payments are negative
                    'order_number': '',
                    'tx_code': f'PMT{date_str.replace("/", "")}',  # Generate unique code for payments
                    'description': 'Payment Thank You',
                    'merchant': 'Chase Payment',
                    'statement_source': statement_filename
                })
                i += 1
                continue

            # Automatic payment pattern: 07/01 AUTOMATIC PAYMENT - THANK YOU -35.00
            auto_payment_match = re.search(r'(\d{2}/\d{2})\s+AUTOMATIC\s+PAYMENT\s*-?\s*THANK\s+YOU.*?-(\d[\d,]*\.\d{2})', line)
            if auto_payment_match:
                date_str = auto_payment_match.group(1)
                amount = float(auto_payment_match.group(2).replace(',', ''))
                full_date = get_full_date(date_str, statement_date)

                transactions.append({
                    'date': full_date,
                    'type': 'Payment',
                    'amount': -amount,  # Payments are negative
                    'order_number': '',
                    'tx_code': f'APMT{date_str.replace("/", "")}',  # Generate unique code for auto payments
                    'description': 'Automatic Payment Thank You',
                    'merchant': 'Chase Payment',
                    'statement_source': statement_filename
                })
                i += 1
                continue

            # Purchase pattern: 02/07 Amazon.com*YT1Z521A3 Amzn.com/bill WA 116.95
            # Also matches refunds: 02/25 AMZN Mktp US Amzn.com/bill WA -94.55
            # Also matches small amounts like .99 (no leading zero)
            purchase_match = re.match(r'^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,]*\.\d{2})$', line)
            if purchase_match:
                date_str = purchase_match.group(1)
                description = purchase_match.group(2).strip()
                amount_str = purchase_match.group(3).replace(',', '')
                amount = float(amount_str)

                # Skip if this looks like a payment line we might have missed
                if 'Payment' in description and 'Thank You' in description:
                    i += 1
                    continue

                full_date = get_full_date(date_str, statement_date)

                # Look for order number on next line
                order_number = ''
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    order_match = re.search(r'Order\s*Number\s+(\S+)', next_line)
                    if order_match:
                        order_number = order_match.group(1)
                        i += 1  # Skip the order number line

                # Determine transaction type
                tx_type = 'Purchase'
                desc_upper = description.upper()

                # Check for fees and interest first (these are not Amazon purchases)
                if 'FEE' in desc_upper and ('RETURN' in desc_upper or 'PMT' in desc_upper or 'LATE' in desc_upper):
                    tx_type = 'Fee'
                elif 'INTEREST CHARGE' in desc_upper:
                    tx_type = 'Interest'
                elif 'Tip' in description or 'TIP' in description:
                    tx_type = 'Tip'
                elif 'Kindle' in description:
                    tx_type = 'Digital'
                elif 'Prime Video' in description:
                    tx_type = 'Digital'
                elif 'AMZN Digital' in description:
                    tx_type = 'Digital'
                elif 'DONATION' in desc_upper:
                    tx_type = 'Donation'

                # Check for refund (negative amount or description indicators)
                # AMAZON MKTPLACE PMTS = marketplace payment/refund
                # Negative amounts indicate credits/refunds
                is_refund = (
                    amount < 0 or
                    'REFUND' in description.upper() or
                    'CREDIT' in description.upper() or
                    'MKTPLACE PMTS' in description.upper()
                )
                if is_refund:
                    tx_type = 'Refund'
                    amount = -abs(amount)

                # Extract merchant name and transaction code
                merchant = description.split('*')[0] if '*' in description else description.split()[0]

                # Extract transaction code (e.g., "YT1Z521A3" from "Amazon.com*YT1Z521A3 Amzn.com/bill WA")
                tx_code = ''
                if '*' in description:
                    # Pattern: Merchant*CODE followed by space
                    tx_code_match = re.search(r'\*([A-Z0-9]+)', description)
                    if tx_code_match:
                        tx_code = tx_code_match.group(1)

                transactions.append({
                    'date': full_date,
                    'type': tx_type,
                    'amount': amount,
                    'order_number': order_number,
                    'tx_code': tx_code,
                    'description': description[:80],
                    'merchant': merchant[:30],
                    'statement_source': statement_filename
                })

            i += 1

        # Also check for Shop with Points transactions
        points_pattern = r'(\d{2}/\d{2})\s+.*?AMAZON\s+MARKETPLACE.*?([\d,]+\.\d{2})\s+([\d,]+)'
        for match in re.finditer(points_pattern, full_text, re.IGNORECASE):
            date_str = match.group(1)
            amount = float(match.group(2).replace(',', ''))
            points = match.group(3)
            full_date = get_full_date(date_str, statement_date)

            # Check if this transaction is already captured
            exists = any(t['date'] == full_date and abs(t['amount'] - amount) < 0.01 for t in transactions)
            if not exists:
                transactions.append({
                    'date': full_date,
                    'type': 'Points Redemption',
                    'amount': amount,
                    'order_number': '',
                    'tx_code': f'PTS{date_str.replace("/", "")}{points}',  # Unique code using date+points
                    'description': f'Shop with Points ({points} pts)',
                    'merchant': 'Amazon',
                    'statement_source': statement_filename
                })

    except Exception as e:
        print(f"  Error parsing {pdf_path}: {e}")

    return transactions, statement_summary


def get_full_date(date_str, statement_date):
    """Convert MM/DD to full YYYY-MM-DD based on statement date."""
    month = int(date_str.split('/')[0])
    day = int(date_str.split('/')[1])
    stmt_month = statement_date.month
    stmt_year = statement_date.year

    # If transaction month > statement month, it's from previous year
    if month > stmt_month:
        year = stmt_year - 1
    else:
        year = stmt_year

    return f"{year}-{month:02d}-{day:02d}"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Collect all transactions by statement
    all_statements = {}
    transactions_by_month = defaultdict(list)

    # Get all statement files sorted by date
    statement_files = sorted([f for f in os.listdir(STATEMENTS_DIR) if f.endswith('.pdf')])

    print(f"Processing {len(statement_files)} statement PDFs...")
    print("=" * 70)

    for filename in statement_files:
        statement_date = get_statement_info(filename)
        if not statement_date:
            continue

        # Only process statements from 2021 onwards
        if statement_date < datetime(2021, 1, 1):
            continue

        filepath = os.path.join(STATEMENTS_DIR, filename)
        transactions, summary = parse_statement(filepath, statement_date, filename)

        # Store statement data
        all_statements[filename] = {
            'date': statement_date,
            'transactions': transactions,
            'summary': summary
        }

        # Organize transactions by calendar month
        for t in transactions:
            try:
                tx_date = datetime.strptime(t['date'], '%Y-%m-%d')
                # Only include transactions from Jan 2021 onwards
                if tx_date >= datetime(2021, 1, 1):
                    month_key = (tx_date.year, tx_date.month)
                    transactions_by_month[month_key].append(t)
            except ValueError:
                pass

        # Print statement summary
        purchases_total = sum(t['amount'] for t in transactions if t['amount'] > 0)
        payments_total = sum(t['amount'] for t in transactions if t['amount'] < 0)
        print(f"{filename}:")
        print(f"  Period: {summary.get('period_start', 'N/A')} - {summary.get('period_end', 'N/A')}")
        print(f"  Transactions: {len(transactions)}")
        print(f"  Purchases: ${purchases_total:.2f}")
        print(f"  Payments/Credits: ${payments_total:.2f}")
        if summary.get('purchases'):
            diff = purchases_total - summary['purchases']
            if abs(diff) > 0.01:
                print(f"  ⚠️  MISMATCH: Statement says ${summary['purchases']:.2f}, parsed ${purchases_total:.2f}")
            else:
                print(f"  ✓ Totals match")
        print()

    # Write monthly CSV files
    print("=" * 70)
    print("Creating monthly CSV files...")
    print()

    fieldnames = ['Date', 'Type', 'Amount', 'Order Number', 'Transaction Code', 'Description', 'Merchant', 'Statement Source']

    for (year, month), transactions in sorted(transactions_by_month.items()):
        month_name = MONTH_NAMES[month]
        output_file = os.path.join(OUTPUT_DIR, f'{year}-{month:02d}-{month_name}.csv')

        # Sort by date
        transactions.sort(key=lambda x: x['date'])

        # Calculate totals
        purchases = sum(t['amount'] for t in transactions if t['amount'] > 0 and t['type'] != 'Payment')
        payments = sum(t['amount'] for t in transactions if t['type'] == 'Payment')
        refunds = sum(t['amount'] for t in transactions if t['type'] == 'Refund')

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for t in transactions:
                writer.writerow({
                    'Date': t['date'],
                    'Type': t['type'],
                    'Amount': f"${t['amount']:.2f}" if t['amount'] >= 0 else f"-${abs(t['amount']):.2f}",
                    'Order Number': t['order_number'],
                    'Transaction Code': t.get('tx_code', ''),
                    'Description': t['description'],
                    'Merchant': t['merchant'],
                    'Statement Source': t.get('statement_source', '')
                })

        print(f"{year}-{month:02d}: {len(transactions)} transactions")
        print(f"    Purchases: ${purchases:.2f}, Payments: ${payments:.2f}, Refunds: ${refunds:.2f}")

    print()
    print("=" * 70)
    print(f"Created {len(transactions_by_month)} monthly CSV files in {OUTPUT_DIR}/")


if __name__ == '__main__':
    main()
