"""Parse Chase Amazon credit card statement PDFs and cache transactions."""

import json
import re
import os
from datetime import datetime
import subprocess

def parse_pdf_text(pdf_path):
    """Extract text from PDF using pdftotext or similar."""
    # Use pdftotext if available, otherwise fall back to PyPDF2
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', pdf_path, '-'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout
    except FileNotFoundError:
        pass

    # Fallback: try PyPDF2
    try:
        import PyPDF2
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ''
            for page in reader.pages:
                text += page.extract_text() + '\n'
            return text
    except ImportError:
        pass

    return None

def parse_statement_transactions(text, statement_date):
    """Parse transactions from statement text."""
    transactions = []

    # Pattern for transaction lines like:
    # 07/04 Amazon.com*ZA1E20LW3 Amzn.com/bill WA 52.39
    # Order Number 114-6583471-1349821

    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for transaction line pattern: MM/DD followed by merchant and amount
        match = re.match(r'^(\d{2}/\d{2})\s+(.+?)\s+(\d+\.\d{2})$', line)
        if match:
            date_str = match.group(1)
            description = match.group(2).strip()
            amount = float(match.group(3))

            # Skip payments (negative amounts are credits)
            if 'Payment' in description or 'PAYMENT' in description:
                i += 1
                continue

            # Look for order number on next line
            order_number = None
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                order_match = re.search(r'Order Number\s+(\S+)', next_line)
                if order_match:
                    order_number = order_match.group(1)
                    i += 1  # Skip the order number line

            # Determine year from statement date
            month = int(date_str.split('/')[0])
            stmt_month = int(statement_date.split('/')[0])
            stmt_year = int(statement_date.split('/')[2])

            # If transaction month > statement month, it's from previous year
            if month > stmt_month:
                year = stmt_year - 1
            else:
                year = stmt_year

            full_date = f"{year}-{date_str.replace('/', '-')}"

            # Classify transaction type
            tx_type = 'purchase'
            if 'Tip' in description or 'TIP' in description:
                tx_type = 'tip'
            elif 'Prime Video' in description or 'AMZN Digital' in description:
                tx_type = 'digital'
            elif 'Prime*' in description and 'Prime Video' not in description:
                tx_type = 'prime_membership'

            transactions.append({
                'date': full_date,
                'description': description,
                'amount': amount,
                'order_number': order_number,
                'type': tx_type
            })

        i += 1

    return transactions

def main():
    statements_dir = 'data/amazon/statements'
    cache_file = 'data/statement_cache_2022.json'

    # 2022 statement files
    statement_files = [
        ('20220104-statements-8414-.pdf', '01/04/22'),
        ('20220204-statements-8414-.pdf', '02/04/22'),
        ('20220304-statements-8414-.pdf', '03/04/22'),
        ('20220404-statements-8414-.pdf', '04/04/22'),
        ('20220504-statements-8414-.pdf', '05/04/22'),
        ('20220604-statements-8414-.pdf', '06/04/22'),
        ('20220704-statements-8414-.pdf', '07/04/22'),
        ('20220804-statements-8414-.pdf', '08/04/22'),
        ('20220904-statements-8414-.pdf', '09/04/22'),
        ('20221004-statements-8414-.pdf', '10/04/22'),
        ('20221104-statements-8414-.pdf', '11/04/22'),
        ('20221204-statements-8414-.pdf', '12/04/22'),
    ]

    all_transactions = {}

    for filename, stmt_date in statement_files:
        pdf_path = os.path.join(statements_dir, filename)
        print(f"Parsing {filename}...")

        text = parse_pdf_text(pdf_path)
        if text:
            transactions = parse_statement_transactions(text, stmt_date)
            all_transactions[stmt_date] = {
                'filename': filename,
                'transactions': transactions,
                'total': sum(t['amount'] for t in transactions)
            }
            print(f"  Found {len(transactions)} transactions, total: ${sum(t['amount'] for t in transactions):.2f}")
        else:
            print(f"  Failed to extract text from {filename}")

    # Save cache
    with open(cache_file, 'w') as f:
        json.dump({
            'generated': datetime.now().isoformat(),
            'statements': all_transactions
        }, f, indent=2)

    print(f"\nCache saved to {cache_file}")

if __name__ == '__main__':
    main()
