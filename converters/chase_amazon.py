"""Converter for Chase Amazon Prime Visa credit card PDF statements."""

import pdfplumber
import re
from datetime import datetime
from decimal import Decimal
from typing import List
from .base import Transaction, BaseConverter


class ChaseAmazonConverter(BaseConverter):
    """Convert Chase Amazon credit card PDF statements to YNAB CSV format."""

    def __init__(self):
        super().__init__()

    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from a PDF file using pdfplumber."""
        text = ''
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + '\n'
        return text

    def parse_file(self, file_path: str) -> List[Transaction]:
        """
        Parse a Chase Amazon credit card PDF statement.

        Args:
            file_path: Path to Amazon credit card PDF statement

        Returns:
            List of Transaction objects
        """
        # Extract the statement year and month from the filename
        # Format: YYYYMMDD-statements-XXXX-.pdf (XXXX = last 4 of card)
        filename = file_path.split('/')[-1]
        year_match = re.match(r'(\d{4})(\d{2})\d{2}', filename)
        if not year_match:
            print(f"Warning: Could not extract year from {filename}")
            return []

        statement_year = int(year_match.group(1))
        statement_month = int(year_match.group(2))

        # Extract text from PDF
        pdf_text = self._extract_text_from_pdf(file_path)

        transactions = []
        in_transactions = False

        # Split by lines
        lines = pdf_text.split('\n')

        for i, line in enumerate(lines):
            # Start capturing after "ACCOUNT ACTIVITY" section
            if 'ACCOUNT ACTIVITY' in line or 'AACCCCOOUUNNTT AACCTTIIVVIITTYY' in line:
                in_transactions = True
                continue

            # Stop at interest charges or shop with points sections
            if in_transactions and ('INTEREST CHARGES' in line or 'IINNTTEERREESSTT CCHHAARRGGEESS' in line or
                                    'SHOP WITH POINTS' in line or 'SSHHOOPP WWIITTHH PPOOIINNTTSS' in line):
                in_transactions = False
                break

            if in_transactions:
                # Pattern: MM/DD Description Amount
                # Example: 12/04 Amazon.com*ZL4WE2K90 Amzn.com/bill WA 42.47
                pattern = r'^(\d{1,2}/\d{1,2})\s+(.+?)\s+(-?\d{1,3}(?:,\d{3})*\.\d{2})$'
                match = re.match(pattern, line.strip())

                if match:
                    date_str, description, amount_str = match.groups()

                    try:
                        # Parse date
                        month, day = date_str.split('/')
                        month = int(month)
                        day = int(day)

                        # Determine year: if transaction month is greater than statement month,
                        # it's from the previous year (e.g., Dec transactions on Jan statement)
                        if month > statement_month:
                            trans_year = statement_year - 1
                        else:
                            trans_year = statement_year

                        trans_date = datetime(trans_year, month, day)

                        # Parse amount
                        amount = Decimal(amount_str.replace(',', ''))

                        # Clean up description
                        description = ' '.join(description.split())

                        # Skip section headers
                        skip_keywords = ['Date of', 'Transaction Merchant', 'PAYMENT', 'PURCHASE',
                                       'RETURNS', 'CREDITS', 'Merchant Name']
                        if any(keyword in description for keyword in skip_keywords):
                            continue

                        # Check next line for Order Number
                        order_number = ''
                        if i + 1 < len(lines):
                            next_line = lines[i + 1].strip()
                            if 'Order Number' in next_line:
                                # Extract order number: "Order Number 123-4567890-1234567"
                                order_match = re.search(r'Order Number\s+([\d-]+)', next_line)
                                if order_match:
                                    order_number = f"Order: {order_match.group(1)}"

                        # For credit cards: positive amounts are charges (negative for YNAB)
                        # negative amounts are payments/credits (positive for YNAB)
                        # Invert the sign for credit card transactions
                        ynab_amount = -amount

                        transactions.append(Transaction(
                            date=trans_date,
                            payee=description,
                            memo=order_number,
                            amount=ynab_amount
                        ))
                    except Exception as e:
                        # Skip lines that don't parse correctly
                        pass

        return transactions
