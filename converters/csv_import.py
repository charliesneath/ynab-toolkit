"""Converter for generic CSV bank statement files."""

import csv
from datetime import datetime
from decimal import Decimal
from typing import List, Dict
from .base import Transaction, BaseConverter


class CSVConverter(BaseConverter):
    """
    Convert generic CSV bank statements to YNAB CSV format.

    Supports various CSV formats by mapping columns.
    """

    def __init__(self, column_mapping: Dict[str, str] = None, date_format: str = '%m/%d/%Y'):
        """
        Initialize CSV converter.

        Args:
            column_mapping: Dictionary mapping CSV columns to standard fields
                           Example: {'Date': 'date', 'Description': 'payee', 'Amount': 'amount'}
            date_format: Python datetime format string for parsing dates
        """
        super().__init__()
        self.column_mapping = column_mapping or self._default_mapping()
        self.date_format = date_format

    def _default_mapping(self) -> Dict[str, str]:
        """Default column mapping for common CSV formats."""
        return {
            'Date': 'date',
            'Transaction Date': 'date',
            'Posting Date': 'date',
            'Description': 'payee',
            'Payee': 'payee',
            'Merchant': 'payee',
            'Amount': 'amount',
            'Debit': 'debit',
            'Credit': 'credit',
            'Memo': 'memo',
            'Notes': 'memo',
        }

    def parse_file(self, file_path: str) -> List[Transaction]:
        """
        Parse a CSV bank statement file.

        Args:
            file_path: Path to CSV file

        Returns:
            List of Transaction objects
        """
        transactions = []

        with open(file_path, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    # Extract fields using column mapping
                    date_str = None
                    payee = ''
                    memo = ''
                    amount = None
                    debit = None
                    credit = None

                    for csv_col, standard_field in self.column_mapping.items():
                        if csv_col in row:
                            value = row[csv_col].strip()
                            if standard_field == 'date':
                                date_str = value
                            elif standard_field == 'payee':
                                payee = value
                            elif standard_field == 'memo':
                                memo = value
                            elif standard_field == 'amount':
                                amount = value
                            elif standard_field == 'debit':
                                debit = value
                            elif standard_field == 'credit':
                                credit = value

                    # Skip empty rows
                    if not date_str or not payee:
                        continue

                    # Parse date
                    trans_date = datetime.strptime(date_str, self.date_format)

                    # Parse amount
                    # Handle three formats:
                    # 1. Single "Amount" column (negative for expenses, positive for income)
                    # 2. Separate "Debit" and "Credit" columns
                    # 3. Amount with sign in the value
                    final_amount = Decimal('0')

                    if amount:
                        # Remove currency symbols and commas
                        amount_clean = amount.replace('$', '').replace(',', '').strip()
                        if amount_clean:
                            final_amount = Decimal(amount_clean)
                    elif debit and credit:
                        # Debit = negative, Credit = positive
                        debit_clean = debit.replace('$', '').replace(',', '').strip()
                        credit_clean = credit.replace('$', '').replace(',', '').strip()

                        if debit_clean:
                            final_amount = -Decimal(debit_clean)
                        elif credit_clean:
                            final_amount = Decimal(credit_clean)
                    else:
                        # Skip if no amount found
                        continue

                    transactions.append(Transaction(
                        date=trans_date,
                        payee=payee,
                        memo=memo,
                        amount=final_amount
                    ))

                except Exception as e:
                    # Skip rows that don't parse correctly
                    continue

        return transactions
