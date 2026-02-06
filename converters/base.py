"""Base classes and shared functionality for bank statement converters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List
import csv


@dataclass
class Transaction:
    """Represents a single transaction."""
    date: datetime
    payee: str
    memo: str
    amount: Decimal  # Positive = inflow, Negative = outflow


class BaseConverter(ABC):
    """Base class for all bank statement converters."""

    def __init__(self):
        self.transactions: List[Transaction] = []

    @abstractmethod
    def parse_file(self, file_path: str) -> List[Transaction]:
        """
        Parse a bank statement file and extract transactions.

        Args:
            file_path: Path to the bank statement file

        Returns:
            List of Transaction objects
        """
        pass

    def parse_files(self, file_paths: List[str]) -> List[Transaction]:
        """
        Parse multiple bank statement files.

        Args:
            file_paths: List of file paths to parse

        Returns:
            Combined list of all transactions
        """
        all_transactions = []
        for file_path in file_paths:
            transactions = self.parse_file(file_path)
            all_transactions.extend(transactions)
        return all_transactions

    def to_ynab_csv(self, transactions: List[Transaction], output_file: str):
        """
        Convert transactions to YNAB CSV format and write to file.

        YNAB CSV format: Date,Payee,Memo,Outflow,Inflow
        - Date: MM/DD/YYYY format
        - Payee: Transaction description/merchant
        - Memo: Additional notes (optional)
        - Outflow: Negative amounts (expenses/charges)
        - Inflow: Positive amounts (deposits/credits)

        Args:
            transactions: List of Transaction objects
            output_file: Path to output CSV file
        """
        # Sort by date
        transactions.sort(key=lambda x: x.date)

        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header (YNAB required format)
            writer.writerow(['Date', 'Payee', 'Memo', 'Outflow', 'Inflow'])

            for trans in transactions:
                # Format date as MM/DD/YYYY
                date_str = trans.date.strftime('%m/%d/%Y')

                # Determine outflow/inflow
                # Negative amounts = outflow (expenses/charges)
                # Positive amounts = inflow (deposits/credits)
                if trans.amount < 0:
                    outflow = f"{abs(trans.amount):.2f}"
                    inflow = ''
                else:
                    outflow = ''
                    inflow = f"{trans.amount:.2f}"

                writer.writerow([date_str, trans.payee, trans.memo, outflow, inflow])

    def convert(self, input_files: List[str], output_file: str, year: int = None) -> int:
        """
        Main conversion method: parse files and write YNAB CSV.

        Args:
            input_files: List of input file paths to convert
            output_file: Path to output YNAB CSV file
            year: Optional year filter (only include transactions from this year)

        Returns:
            Number of transactions converted
        """
        # Parse all files
        transactions = self.parse_files(input_files)

        # Filter by year if specified
        if year:
            transactions = [t for t in transactions if t.date.year == year]

        # Convert to YNAB CSV
        self.to_ynab_csv(transactions, output_file)

        return len(transactions)
