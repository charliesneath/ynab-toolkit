"""Extract payment data from Chase statements and add to monthly CSVs."""

import os
import csv
import re
from datetime import datetime
from collections import defaultdict

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

STATEMENTS_DIR = 'data/amazon/statements'
MONTHLY_DIR = 'data/processed/chase-amazon/monthly'

MONTH_NAMES = {
    1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
    7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
}


def extract_text_from_pdf(pdf_path):
    """Extract text from PDF using PyPDF2."""
    if not HAS_PYPDF2:
        return None
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ''
            for page in reader.pages:
                text += page.extract_text() + '\n'
            return text
    except Exception as e:
        print(f"  Error reading {pdf_path}: {e}")
        return None


def parse_payments_from_text(text, statement_date):
    """Parse payment transactions from statement text."""
    payments = []

    # Pattern for payment lines like:
    # 01/22 Payment Thank You-Mobile -845.49
    # or: 02/25 Payment Thank You - Web -436.62
    pattern = r'(\d{2}/\d{2})\s+Payment[^\d-]+([\d,]+\.\d{2})'

    for match in re.finditer(pattern, text, re.IGNORECASE):
        date_str = match.group(1)
        amount = float(match.group(2).replace(',', ''))

        # Determine year from statement date
        month = int(date_str.split('/')[0])
        stmt_month = statement_date.month
        stmt_year = statement_date.year

        # If payment month > statement month, it's from previous year
        if month > stmt_month:
            year = stmt_year - 1
        else:
            year = stmt_year

        full_date = f"{year}-{date_str.replace('/', '-')}"

        payments.append({
            'date': full_date,
            'amount': amount,
            'type': 'Payment'
        })

    return payments


def get_statement_date(filename):
    """Extract statement date from filename like YYYYMMDD-statements-XXXX-.pdf"""
    match = re.match(r'(\d{4})(\d{2})(\d{2})', filename)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return datetime(year, month, day)
    return None


def main():
    if not HAS_PYPDF2:
        print("PyPDF2 not installed. Cannot extract payments from PDFs.")
        return

    # Collect all payments by month
    payments_by_month = defaultdict(list)

    # Get all statement files
    statement_files = sorted([f for f in os.listdir(STATEMENTS_DIR) if f.endswith('.pdf')])

    print(f"Processing {len(statement_files)} statements...")

    for filename in statement_files:
        statement_date = get_statement_date(filename)
        if not statement_date:
            continue

        # Only process statements from 2021 onwards
        if statement_date.year < 2021:
            continue

        filepath = os.path.join(STATEMENTS_DIR, filename)
        text = extract_text_from_pdf(filepath)

        if not text:
            continue

        payments = parse_payments_from_text(text, statement_date)

        for payment in payments:
            try:
                payment_date = datetime.strptime(payment['date'], '%Y-%m-%d')
                # Only include payments from Feb 2021 onwards
                if payment_date >= datetime(2021, 2, 1):
                    month_key = (payment_date.year, payment_date.month)
                    payments_by_month[month_key].append(payment)
            except ValueError:
                pass

    print(f"\nFound {sum(len(v) for v in payments_by_month.values())} payments")

    # Update monthly CSV files
    print("\nUpdating monthly CSV files...")

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


if __name__ == '__main__':
    main()
