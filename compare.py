#!/usr/bin/env python3
"""CLI tool to compare Chase transactions with YNAB transactions."""

import argparse
import os
import sys
from datetime import datetime
from decimal import Decimal
from typing import List, Tuple

from dotenv import load_dotenv

from chase_parser import parse_chase_csv, ChaseTransaction
from ynab_client import YNABClient, YNABTransaction

# Load environment variables from .env file
load_dotenv()


class TransactionMatcher:
    """Match transactions between Chase and YNAB."""

    def __init__(self, tolerance_days: int = 2, amount_tolerance: Decimal = Decimal("0.01")):
        """
        Initialize the matcher.

        Args:
            tolerance_days: Number of days to allow for date differences
            amount_tolerance: Amount difference to tolerate (for floating point issues)
        """
        self.tolerance_days = tolerance_days
        self.amount_tolerance = amount_tolerance

    def find_match(
        self,
        chase_trans: ChaseTransaction,
        ynab_transactions: List[YNABTransaction]
    ) -> Tuple[bool, YNABTransaction | None]:
        """
        Find a matching YNAB transaction for a Chase transaction.

        Args:
            chase_trans: The Chase transaction to match
            ynab_transactions: List of YNAB transactions to search

        Returns:
            Tuple of (found, matching_transaction)
        """
        for ynab_trans in ynab_transactions:
            # Check if dates are within tolerance
            date_diff = abs((chase_trans.date - ynab_trans.date).days)
            if date_diff > self.tolerance_days:
                continue

            # Check if amounts match (YNAB uses negative for outflows)
            # Chase might use negative for debits or positive for credits
            amount_diff = abs(abs(chase_trans.amount) - abs(ynab_trans.amount))
            if amount_diff > self.amount_tolerance:
                continue

            return True, ynab_trans

        return False, None

    def compare_transactions(
        self,
        chase_transactions: List[ChaseTransaction],
        ynab_transactions: List[YNABTransaction]
    ) -> Tuple[List[ChaseTransaction], List[YNABTransaction]]:
        """
        Compare two lists of transactions.

        Args:
            chase_transactions: List of Chase transactions
            ynab_transactions: List of YNAB transactions

        Returns:
            Tuple of (unmatched_chase, unmatched_ynab)
        """
        unmatched_chase = []
        matched_ynab_ids = set()

        # Find Chase transactions without matches in YNAB
        for chase_trans in chase_transactions:
            found, ynab_match = self.find_match(chase_trans, ynab_transactions)
            if found and ynab_match:
                matched_ynab_ids.add(ynab_match.transaction_id)
            else:
                unmatched_chase.append(chase_trans)

        # Find YNAB transactions without matches in Chase
        unmatched_ynab = [
            trans for trans in ynab_transactions
            if trans.transaction_id not in matched_ynab_ids
        ]

        return unmatched_chase, unmatched_ynab


def print_results(
    chase_balance: Decimal,
    ynab_balance: Decimal,
    unmatched_chase: List[ChaseTransaction],
    unmatched_ynab: List[YNABTransaction]
):
    """Print comparison results."""
    print("\n" + "=" * 80)
    print("BALANCE COMPARISON")
    print("=" * 80)
    print(f"Chase Balance:       ${chase_balance:,.2f}")
    print(f"YNAB Balance:        ${ynab_balance:,.2f}")
    print(f"Difference:          ${chase_balance - ynab_balance:,.2f}")

    if unmatched_chase:
        print("\n" + "=" * 80)
        print(f"TRANSACTIONS IN CHASE BUT NOT IN YNAB ({len(unmatched_chase)})")
        print("=" * 80)
        for trans in sorted(unmatched_chase, key=lambda t: t.date):
            print(f"{trans.date.strftime('%Y-%m-%d')} | ${trans.amount:>10.2f} | {trans.description}")

    if unmatched_ynab:
        print("\n" + "=" * 80)
        print(f"TRANSACTIONS IN YNAB BUT NOT IN CHASE ({len(unmatched_ynab)})")
        print("=" * 80)
        for trans in sorted(unmatched_ynab, key=lambda t: t.date):
            memo = f" ({trans.memo})" if trans.memo else ""
            print(f"{trans.date.strftime('%Y-%m-%d')} | ${trans.amount:>10.2f} | {trans.payee_name}{memo}")

    if not unmatched_chase and not unmatched_ynab:
        print("\n" + "=" * 80)
        print("All transactions matched!")
        print("=" * 80)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Compare Chase bank transactions with YNAB transactions"
    )
    parser.add_argument(
        "--chase",
        default=os.getenv("CHASE_CSV_PATH"),
        help="Path to Chase CSV export file"
    )
    parser.add_argument(
        "--ynab-token",
        default=os.getenv("YNAB_TOKEN"),
        help="YNAB Personal Access Token (or set YNAB_TOKEN in .env)"
    )
    parser.add_argument(
        "--budget-name",
        default=os.getenv("BUDGET_NAME"),
        help="Name of your YNAB budget (or set BUDGET_NAME in .env)"
    )
    parser.add_argument(
        "--account-name",
        default=os.getenv("ACCOUNT_NAME"),
        help="Name of the YNAB account to compare (or set ACCOUNT_NAME in .env)"
    )
    parser.add_argument(
        "--date-from",
        help="Start date for comparison (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--date-to",
        help="End date for comparison (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--tolerance-days",
        type=int,
        default=2,
        help="Number of days tolerance for date matching (default: 2)"
    )

    args = parser.parse_args()

    # Validate required arguments
    if not args.chase:
        print("Error: --chase argument is required (or set CHASE_CSV_PATH in .env)", file=sys.stderr)
        sys.exit(1)
    if not args.ynab_token:
        print("Error: --ynab-token argument is required (or set YNAB_TOKEN in .env)", file=sys.stderr)
        sys.exit(1)
    if not args.budget_name:
        print("Error: --budget-name argument is required (or set BUDGET_NAME in .env)", file=sys.stderr)
        sys.exit(1)
    if not args.account_name:
        print("Error: --account-name argument is required (or set ACCOUNT_NAME in .env)", file=sys.stderr)
        sys.exit(1)

    # Parse Chase CSV
    print(f"Loading Chase transactions from {args.chase}...")
    try:
        chase_transactions = parse_chase_csv(args.chase)
        print(f"Found {len(chase_transactions)} Chase transactions")
    except Exception as e:
        print(f"Error parsing Chase CSV: {e}", file=sys.stderr)
        sys.exit(1)

    # Get date range from Chase transactions
    if not chase_transactions:
        print("No transactions found in Chase CSV", file=sys.stderr)
        sys.exit(1)

    chase_dates = [t.date for t in chase_transactions]
    earliest_chase_date = min(chase_dates)
    latest_chase_date = max(chase_dates)
    print(f"Chase CSV date range: {earliest_chase_date.strftime('%Y-%m-%d')} to {latest_chase_date.strftime('%Y-%m-%d')}")

    # Connect to YNAB
    print(f"Connecting to YNAB...")
    try:
        ynab = YNABClient(args.ynab_token)

        # Get budget ID
        budget_id = ynab.get_budget_id(args.budget_name)
        if not budget_id:
            print(f"Budget '{args.budget_name}' not found", file=sys.stderr)
            sys.exit(1)

        # Get account ID
        account_id = ynab.get_account_id(budget_id, args.account_name)
        if not account_id:
            print(f"Account '{args.account_name}' not found", file=sys.stderr)
            sys.exit(1)

        # Get transactions from YNAB starting from earliest Chase date
        since_date = args.date_from if args.date_from else earliest_chase_date.strftime('%Y-%m-%d')
        ynab_transactions = ynab.get_transactions(
            budget_id,
            account_id,
            since_date=since_date
        )
        print(f"Found {len(ynab_transactions)} YNAB transactions since {since_date}")

        # Get YNAB balance
        ynab_balance = ynab.get_account_balance(budget_id, account_id)

    except Exception as e:
        print(f"Error connecting to YNAB: {e}", file=sys.stderr)
        sys.exit(1)

    # Filter by date range if specified
    if args.date_from or args.date_to:
        date_from = datetime.strptime(args.date_from, "%Y-%m-%d") if args.date_from else None
        date_to = datetime.strptime(args.date_to, "%Y-%m-%d") if args.date_to else None

        if date_from:
            chase_transactions = [t for t in chase_transactions if t.date >= date_from]
            ynab_transactions = [t for t in ynab_transactions if t.date >= date_from]

        if date_to:
            chase_transactions = [t for t in chase_transactions if t.date <= date_to]
            ynab_transactions = [t for t in ynab_transactions if t.date <= date_to]

    # Get Chase balance (from the most recent transaction)
    chase_balance = chase_transactions[0].balance if chase_transactions else Decimal("0")
    if chase_balance == Decimal("0"):
        # If balance not in CSV, calculate from transactions
        print("Warning: Balance not found in Chase CSV, cannot compare balances accurately")

    # Compare transactions
    print("Comparing transactions...")
    matcher = TransactionMatcher(tolerance_days=args.tolerance_days)
    unmatched_chase, unmatched_ynab = matcher.compare_transactions(
        chase_transactions,
        ynab_transactions
    )

    # Print results
    print_results(chase_balance, ynab_balance, unmatched_chase, unmatched_ynab)


if __name__ == "__main__":
    main()
