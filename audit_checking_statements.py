"""
Chase Checking Statement Auditor: Parse Chase checking statements and create authoritative monthly CSVs.

This script reads all Chase checking statement PDFs and creates month-by-month CSV files
that serve as the source of truth for all checking account transactions.
"""

import os
import csv
import re
import pdfplumber
from datetime import datetime
from collections import defaultdict

STATEMENTS_DIR = 'data/chase checking/statements'
OUTPUT_DIR = 'data/processed/chase-checking/audit'

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
    """Parse all transactions from a Chase checking statement PDF."""
    transactions = []
    statement_summary = {}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ''
            for page in pdf.pages:
                full_text += (page.extract_text() or '') + '\n'

        # Extract statement period
        period_match = re.search(r'(\w+ \d+, \d{4})through(\w+ \d+, \d{4})', full_text)
        if period_match:
            statement_summary['period_start'] = period_match.group(1)
            statement_summary['period_end'] = period_match.group(2)

        # Extract beginning and ending balance
        begin_match = re.search(r'Beginning Balance\s*\$?([\d,]+\.\d{2})', full_text)
        if begin_match:
            statement_summary['beginning_balance'] = float(begin_match.group(1).replace(',', ''))

        end_match = re.search(r'Ending Balance\s*\$?([\d,]+\.\d{2})', full_text)
        if end_match:
            statement_summary['ending_balance'] = float(end_match.group(1).replace(',', ''))

        # Parse transactions from TRANSACTION DETAIL section
        lines = full_text.split('\n')
        in_transaction_section = False

        for i, line in enumerate(lines):
            line = line.strip()

            # Detect start/end of transaction section
            if 'TRANSACTION DETAIL' in line:
                in_transaction_section = True
                continue
            if 'Ending Balance' in line and in_transaction_section:
                in_transaction_section = False
                continue

            if not in_transaction_section:
                continue

            # Skip header lines
            if line.startswith('DATE') or line.startswith('Beginning Balance') or '(continued)' in line:
                continue
            if 'Account Number' in line or line.startswith('Page '):
                continue

            # Transaction pattern: MM/DD Description Amount Balance
            # Amount can be negative (with -) or positive
            # Examples:
            #   03/25 Capital One N.A. Capitalone PPD ID: 1234567890 123.45 10,000.00
            #   03/25 03/25 Online Transfer To Chk ...1828 Transaction#: 11446066576 -1,000.00 34,244.29

            tx_match = re.match(r'^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,]+\.\d{2})\s+([\d,]+\.\d{2})$', line)
            if tx_match:
                date_str = tx_match.group(1)
                description = tx_match.group(2).strip()
                amount_str = tx_match.group(3).replace(',', '')
                balance_str = tx_match.group(4).replace(',', '')

                amount = float(amount_str)
                balance = float(balance_str)

                # Determine year from statement date
                tx_month = int(date_str.split('/')[0])
                tx_day = int(date_str.split('/')[1])
                stmt_month = statement_date.month
                stmt_year = statement_date.year

                # If transaction month > statement month, it's from previous year
                if tx_month > stmt_month:
                    tx_year = stmt_year - 1
                else:
                    tx_year = stmt_year

                full_date = f"{tx_year}-{tx_month:02d}-{tx_day:02d}"

                # Determine transaction type
                desc_upper = description.upper()
                if 'PAYMENT TO CHASE CARD' in desc_upper:
                    tx_type = 'Card Payment'
                elif 'ONLINE TRANSFER TO' in desc_upper:
                    tx_type = 'Transfer Out'
                elif 'ONLINE TRANSFER FROM' in desc_upper:
                    tx_type = 'Transfer In'
                elif 'DIRECT DEP' in desc_upper or 'PAYROLL' in desc_upper:
                    tx_type = 'Direct Deposit'
                elif 'CHECK #' in desc_upper or re.match(r'Check # \d+', description):
                    tx_type = 'Check'
                elif 'ATM' in desc_upper:
                    tx_type = 'ATM'
                elif 'CARD PURCHASE' in desc_upper:
                    tx_type = 'Debit Card'
                elif 'WIRE' in desc_upper or 'FEDWIRE' in desc_upper:
                    tx_type = 'Wire'
                elif 'FEE' in desc_upper:
                    tx_type = 'Fee'
                elif amount > 0:
                    tx_type = 'Deposit'
                else:
                    tx_type = 'Withdrawal'

                transactions.append({
                    'date': full_date,
                    'type': tx_type,
                    'amount': amount,
                    'balance': balance,
                    'description': description[:100],
                    'statement_source': statement_filename
                })
            else:
                # Try to match multi-line transactions (description continues on next line)
                # This handles cases where amount/balance are on same line but description wraps
                simple_match = re.match(r'^(\d{2}/\d{2})\s+(.+)', line)
                if simple_match and i + 1 < len(lines):
                    # Check if next line has the amount/balance
                    next_line = lines[i + 1].strip()
                    amount_balance_match = re.match(r'^(-?[\d,]+\.\d{2})\s+([\d,]+\.\d{2})$', next_line)
                    if amount_balance_match:
                        # This is handled by the main pattern on the combined line
                        pass

    except Exception as e:
        print(f"  Error parsing {pdf_path}: {e}")
        import traceback
        traceback.print_exc()

    return transactions, statement_summary


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Collect all transactions by statement
    transactions_by_month = defaultdict(list)
    all_statements = {}

    # Get all statement files sorted by date
    statement_files = sorted([f for f in os.listdir(STATEMENTS_DIR) if f.endswith('.pdf')])

    print(f"Processing {len(statement_files)} Chase checking statement PDFs...")
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
        deposits = sum(t['amount'] for t in transactions if t['amount'] > 0)
        withdrawals = sum(t['amount'] for t in transactions if t['amount'] < 0)
        print(f"{filename}:")
        print(f"  Period: {summary.get('period_start', 'N/A')} - {summary.get('period_end', 'N/A')}")
        print(f"  Transactions: {len(transactions)}")
        print(f"  Deposits: ${deposits:,.2f}, Withdrawals: ${withdrawals:,.2f}")
        if summary.get('beginning_balance') and summary.get('ending_balance'):
            expected_change = summary['ending_balance'] - summary['beginning_balance']
            actual_change = deposits + withdrawals
            if abs(expected_change - actual_change) > 0.01:
                print(f"  ⚠️  MISMATCH: Expected change ${expected_change:,.2f}, parsed ${actual_change:,.2f}")
            else:
                print(f"  ✓ Totals match")
        print()

    # Write monthly CSV files
    print("=" * 70)
    print("Creating monthly CSV files...")
    print()

    fieldnames = ['Date', 'Type', 'Amount', 'Balance', 'Description', 'Statement Source']

    for (year, month), transactions in sorted(transactions_by_month.items()):
        month_name = MONTH_NAMES[month]
        output_file = os.path.join(OUTPUT_DIR, f'{year}-{month:02d}-{month_name}.csv')

        # Remove duplicates (same date, amount, description)
        seen = set()
        unique_transactions = []
        for t in transactions:
            key = (t['date'], t['amount'], t['description'][:50])
            if key not in seen:
                seen.add(key)
                unique_transactions.append(t)

        # Sort by date
        unique_transactions.sort(key=lambda x: x['date'])

        # Calculate totals
        deposits = sum(t['amount'] for t in unique_transactions if t['amount'] > 0)
        withdrawals = sum(t['amount'] for t in unique_transactions if t['amount'] < 0)

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for t in unique_transactions:
                writer.writerow({
                    'Date': t['date'],
                    'Type': t['type'],
                    'Amount': f"${t['amount']:,.2f}" if t['amount'] >= 0 else f"-${abs(t['amount']):,.2f}",
                    'Balance': f"${t['balance']:,.2f}",
                    'Description': t['description'],
                    'Statement Source': t.get('statement_source', '')
                })

        print(f"{year}-{month:02d}: {len(unique_transactions)} transactions")
        print(f"    Deposits: ${deposits:,.2f}, Withdrawals: ${withdrawals:,.2f}")

    print()
    print("=" * 70)
    print(f"Created {len(transactions_by_month)} monthly CSV files in {OUTPUT_DIR}/")


if __name__ == '__main__':
    main()
