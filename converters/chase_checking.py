"""Converter for Chase checking account PDF statements."""

import pdfplumber
import re
from datetime import datetime
from decimal import Decimal
from typing import List
from .base import Transaction, BaseConverter


class ChaseCheckingConverter(BaseConverter):
    """Convert Chase checking account PDF statements to YNAB CSV format."""

    def __init__(self):
        super().__init__()

    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from a PDF file using pdfplumber."""
        text = ''
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text()
        return text

    def parse_file(self, file_path: str) -> List[Transaction]:
        """
        Parse a Chase checking account PDF statement.

        Args:
            file_path: Path to Chase PDF statement

        Returns:
            List of Transaction objects
        """
        # Extract the statement year from the filename
        # Format: YYYYMMDD-statements-XXXX-.pdf (XXXX = last 4 of account)
        filename = file_path.split('/')[-1]
        year_match = re.match(r'(\d{4})\d{4}', filename)
        if not year_match:
            print(f"Warning: Could not extract year from {filename}")
            return []

        statement_year = int(year_match.group(1))

        # Extract text from PDF
        pdf_text = self._extract_text_from_pdf(file_path)

        # Clean up malformed lines that have page header/footer artifacts
        # Pattern: *end*transac1tion detail0/06 -> 10/06
        pdf_text = re.sub(r'\*end\*transac([01])tion detail(\d)', r'\1\2', pdf_text)

        transactions = []

        # Use findall to extract all transaction patterns from the entire text
        # Pattern: MM/DD Description AMOUNT BALANCE
        pattern = r'(\d{1,2}/\d{1,2})\s+(.+?)\s+(-?\s?\d{1,3}(?:,\d{3})*\.\d{2})\s+(\d{1,3}(?:,\d{3})*\.\d{2})'

        # Find all matches in the text
        for match in re.finditer(pattern, pdf_text):
            date_str, description, amount_str, balance_str = match.groups()

            # Skip if description contains certain keywords
            skip_keywords = ['Beginning Balance', 'Ending Balance', 'Total Checks', 'Account Number',
                            'AMOUNT', 'BALANCE', 'CHECKING SUMMARY', 'Page', 'CHECK NUMBER']
            if any(keyword in description for keyword in skip_keywords):
                continue

            # Parse date (add year)
            try:
                month, day = date_str.split('/')
                trans_date = datetime(statement_year, int(month), int(day))

                # Handle year boundary - if month is 12 and statement is from early next year
                if statement_year >= 2023 and int(month) == 12:
                    # Check if this is from a January statement
                    if filename.startswith(f'{statement_year}01'):
                        trans_date = datetime(statement_year - 1, int(month), int(day))

                # Parse amount and balance
                # Remove spaces from amount string (e.g., "- 50.00" -> "-50.00")
                amount = Decimal(amount_str.replace(',', '').replace(' ', ''))
                balance = Decimal(balance_str.replace(',', ''))

                # Clean up description
                description = ' '.join(description.split())

                # Skip if description is too short
                if len(description) < 3:
                    continue

                transactions.append(Transaction(
                    date=trans_date,
                    payee=description,
                    memo='',
                    amount=amount  # Keep original sign from statement
                ))
            except Exception as e:
                # Skip lines that don't parse correctly
                pass

        return transactions
