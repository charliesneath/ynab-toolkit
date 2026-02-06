"""YNAB API write operations (create, update, delete transactions).

This module contains all destructive YNAB operations that modify data.
For read-only operations, use ynab_client.py directly.

IMPORTANT: Importing from this module indicates destructive intent and
will trigger permission prompts via the auto_approve_reads hook.
"""

import requests
import time
from decimal import Decimal
from typing import Dict, List, Optional

# Import the base client for API access
from ynab_client import YNABClient


class YNABWriter:
    """Write operations for the YNAB API.

    Wraps a YNABClient to provide create/update/delete operations.
    All methods in this class modify YNAB data.
    """

    BASE_URL = "https://api.ynab.com/v1"

    def __init__(self, client: YNABClient):
        """Initialize with an existing YNABClient for API access.

        Args:
            client: An authenticated YNABClient instance
        """
        self.client = client

    def _write(self, endpoint: str, method: str, json_data: Optional[Dict] = None) -> Dict:
        """Make a write request (POST/PUT/DELETE) to the YNAB API.

        This is the ONLY place where YNAB write operations happen.
        Separated from YNABClient._get() to make read/write distinction clear.
        """
        url = f"{self.BASE_URL}{endpoint}"
        headers = self.client.headers
        response = None

        for attempt in range(5):
            if method == "POST":
                response = requests.post(url, headers=headers, json=json_data)
            elif method == "PUT":
                response = requests.put(url, headers=headers, json=json_data)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported write method: {method}")

            if response.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"  [RATE LIMIT] Waiting {wait}s (attempt {attempt+1}/5)...", flush=True)
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        if response:
            response.raise_for_status()
        raise Exception("Max retries exceeded")

    def delete_transaction(self, budget_id: str, transaction_id: str) -> Dict:
        """Delete a transaction.

        Args:
            budget_id: The budget ID
            transaction_id: The transaction to delete

        Returns:
            API response data
        """
        return self._write(
            f"/budgets/{budget_id}/transactions/{transaction_id}",
            method="DELETE"
        )

    def update_transaction(
        self,
        budget_id: str,
        transaction_id: str,
        category_id: Optional[str] = None,
        memo: Optional[str] = None,
        flag_color: Optional[str] = None,
        approved: Optional[bool] = None,
        subtransactions: Optional[List[Dict]] = None
    ) -> Dict:
        """Update an existing transaction.

        Args:
            budget_id: The budget ID
            transaction_id: The transaction to update
            category_id: New category ID (optional)
            memo: New memo (optional)
            flag_color: New flag color (optional)
            approved: New approval status (optional)
            subtransactions: New subtransactions/splits (optional)

        Returns:
            Updated transaction data
        """
        transaction_data = {"transaction": {}}

        if category_id is not None:
            transaction_data["transaction"]["category_id"] = category_id
        if memo is not None:
            transaction_data["transaction"]["memo"] = memo
        if flag_color is not None:
            transaction_data["transaction"]["flag_color"] = flag_color
        if approved is not None:
            transaction_data["transaction"]["approved"] = approved
        if subtransactions is not None:
            transaction_data["transaction"]["subtransactions"] = subtransactions
            print(f"YNAB PUT subtransactions: {subtransactions}")

        return self._write(
            f"/budgets/{budget_id}/transactions/{transaction_id}",
            method="PUT",
            json_data=transaction_data
        )

    def delete_transaction(self, budget_id: str, transaction_id: str) -> Dict:
        """Delete a transaction.

        Args:
            budget_id: The budget ID
            transaction_id: The transaction to delete

        Returns:
            Deleted transaction data
        """
        return self._write(
            f"/budgets/{budget_id}/transactions/{transaction_id}",
            method="DELETE"
        )

    def create_transaction(
        self,
        budget_id: str,
        account_id: str,
        date: str,
        amount: Decimal,
        payee_name: str,
        memo: Optional[str] = None,
        category_id: Optional[str] = None,
        flag_color: Optional[str] = None,
        approved: bool = False,
        subtransactions: Optional[List[Dict]] = None,
        import_id: Optional[str] = None
    ) -> Dict:
        """Create a new transaction in YNAB.

        Args:
            budget_id: The budget ID
            account_id: The account ID to create the transaction in
            date: Transaction date (YYYY-MM-DD)
            amount: Transaction amount (negative for outflow)
            payee_name: Name of the payee
            memo: Optional memo
            category_id: Optional category ID
            flag_color: Optional flag color
            approved: Whether to mark as approved
            subtransactions: Optional list of splits
            import_id: Optional unique ID to prevent duplicates

        Returns:
            Created transaction data
        """
        amount_milliunits = int(amount * 1000)

        transaction_data = {
            "transaction": {
                "account_id": account_id,
                "date": date,
                "amount": amount_milliunits,
                "payee_name": payee_name,
                "approved": approved,
            }
        }

        if memo:
            transaction_data["transaction"]["memo"] = memo
        if category_id:
            transaction_data["transaction"]["category_id"] = category_id
        if flag_color:
            transaction_data["transaction"]["flag_color"] = flag_color
        if subtransactions:
            transaction_data["transaction"]["subtransactions"] = subtransactions
        if import_id:
            transaction_data["transaction"]["import_id"] = import_id

        result = self._write(
            f"/budgets/{budget_id}/transactions",
            method="POST",
            json_data=transaction_data
        )
        return result.get("data", {}).get("transaction", {})

    def create_transactions_batch(
        self,
        budget_id: str,
        transactions: List[Dict],
    ) -> Dict:
        """Create multiple transactions in a single API call.

        Args:
            budget_id: The budget ID
            transactions: List of transaction dicts, each with:
                - account_id, date, amount (milliunits), payee_name
                - Optional: memo, category_id, flag_color, approved, subtransactions, import_id

        Returns:
            Response with created transactions and any duplicates
        """
        result = self._write(
            f"/budgets/{budget_id}/transactions",
            method="POST",
            json_data={"transactions": transactions}
        )
        return result.get("data", {})

    def create_split_transaction(
        self,
        budget_id: str,
        transaction_id: str,
        splits: List[Dict],
        memo: Optional[str] = None,
        flag_color: Optional[str] = None,
        approved: bool = True
    ) -> Dict:
        """Convert a transaction to a split transaction.

        Args:
            budget_id: The budget ID
            transaction_id: The transaction to split
            splits: List of dicts with 'amount' (Decimal), 'category_id', and optional 'memo'
            memo: Overall transaction memo
            flag_color: Flag color (red, orange, yellow, green, blue, purple)
            approved: Whether to mark as approved

        Returns:
            Updated transaction data
        """
        subtransactions = []
        for split in splits:
            amount_milliunits = int(split["amount"] * 1000)
            sub = {
                "amount": amount_milliunits,
                "category_id": split["category_id"]
            }
            if split.get("memo"):
                sub["memo"] = split["memo"]
            subtransactions.append(sub)

        return self.update_transaction(
            budget_id=budget_id,
            transaction_id=transaction_id,
            memo=memo,
            flag_color=flag_color,
            approved=approved,
            subtransactions=subtransactions
        )
