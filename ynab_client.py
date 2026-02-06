"""Read-only client for interacting with the YNAB API.

This module contains only read operations (GET requests).
For write operations (create, update, delete), use ynab_writer.py.
"""

import requests
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional


class YNABTransaction:
    """Represents a YNAB transaction."""

    def __init__(
        self,
        date: datetime,
        payee_name: str,
        amount: Decimal,
        memo: str,
        cleared: str,
        transaction_id: str,
        account_id: Optional[str] = None,
        category_id: Optional[str] = None,
        category_name: Optional[str] = None,
        approved: bool = False,
        flag_color: Optional[str] = None,
        subtransactions: Optional[List[Dict]] = None,
        import_id: Optional[str] = None
    ):
        self.date = date
        self.payee_name = payee_name
        self.amount = amount
        self.memo = memo
        self.cleared = cleared
        self.transaction_id = transaction_id
        self.account_id = account_id
        self.category_id = category_id
        self.category_name = category_name
        self.approved = approved
        self.flag_color = flag_color
        self.subtransactions = subtransactions or []
        self.import_id = import_id

    def __repr__(self):
        return f"YNABTransaction(date={self.date.strftime('%Y-%m-%d')}, payee='{self.payee_name}', amount={self.amount})"


class YNABCategory:
    """Represents a YNAB category."""

    def __init__(self, category_id: str, name: str, group_name: str, group_id: str):
        self.category_id = category_id
        self.name = name
        self.group_name = group_name
        self.group_id = group_id

    def __repr__(self):
        return f"YNABCategory(name='{self.name}', group='{self.group_name}')"


class YNABClient:
    """Read-only client for the YNAB API.

    For write operations, use YNABWriter from ynab_writer.py:

        from ynab_client import YNABClient
        from ynab_writer import YNABWriter

        client = YNABClient(token)
        writer = YNABWriter(client)

        # Read operations
        budgets = client.get_budgets()
        transactions = client.get_transactions(budget_id)

        # Write operations
        writer.create_transaction(budget_id, ...)
        writer.update_transaction(budget_id, ...)
    """

    BASE_URL = "https://api.ynab.com/v1"

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    def _get(self, endpoint: str) -> Dict:
        """Make a GET request to the YNAB API with retry on rate limit.

        This is the ONLY request method in YNABClient - all reads use GET.
        For write operations (POST/PUT/DELETE), use YNABWriter.
        """
        import time
        url = f"{self.BASE_URL}{endpoint}"
        response = None

        for attempt in range(5):
            response = requests.get(url, headers=self.headers)

            if response.status_code == 429:
                wait = 30 * (attempt + 1)  # 30, 60, 90, 120, 150 seconds
                print(f"  [RATE LIMIT] Waiting {wait}s (attempt {attempt+1}/5)...", flush=True)
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        if response:
            response.raise_for_status()
        raise Exception("Max retries exceeded")

    # =========================================================================
    # Read Operations - Budgets
    # =========================================================================

    def get_budgets(self) -> List[Dict]:
        """Get all budgets."""
        data = self._get("/budgets")
        return data.get("data", {}).get("budgets", [])

    def get_budget_id(self, budget_name: str) -> Optional[str]:
        """Get budget ID by name."""
        budgets = self.get_budgets()
        for budget in budgets:
            if budget["name"].lower() == budget_name.lower():
                return budget["id"]
        return None

    # =========================================================================
    # Read Operations - Accounts
    # =========================================================================

    def get_accounts(self, budget_id: str) -> List[Dict]:
        """Get all accounts for a budget."""
        data = self._get(f"/budgets/{budget_id}/accounts")
        return data.get("data", {}).get("accounts", [])

    def get_account_id(self, budget_id: str, account_name: str) -> Optional[str]:
        """Get account ID by name."""
        accounts = self.get_accounts(budget_id)
        for account in accounts:
            if account["name"].lower() == account_name.lower():
                return account["id"]
        return None

    # =========================================================================
    # Read Operations - Categories
    # =========================================================================

    def get_categories(self, budget_id: str) -> List[YNABCategory]:
        """Get all categories for a budget."""
        data = self._get(f"/budgets/{budget_id}/categories")
        categories = []
        for group in data.get("data", {}).get("category_groups", []):
            group_name = group["name"]
            group_id = group["id"]
            # Skip internal groups
            if group.get("hidden") or group_name in ["Internal Master Category", "Credit Card Payments"]:
                continue
            for cat in group.get("categories", []):
                if not cat.get("hidden") and not cat.get("deleted"):
                    categories.append(YNABCategory(
                        category_id=cat["id"],
                        name=cat["name"],
                        group_name=group_name,
                        group_id=group_id
                    ))
        return categories

    def get_categories_by_group(self, budget_id: str, group_name: str) -> List[YNABCategory]:
        """Get all categories in a specific category group."""
        all_categories = self.get_categories(budget_id)
        return [c for c in all_categories if c.group_name.lower() == group_name.lower()]

    def has_category_group(self, budget_id: str, group_name: str) -> bool:
        """Check if a category group exists."""
        data = self._get(f"/budgets/{budget_id}/categories")
        for group in data.get("data", {}).get("category_groups", []):
            if group["name"].lower() == group_name.lower() and not group.get("hidden"):
                return True
        return False

    def get_category_id(self, budget_id: str, category_name: str) -> Optional[str]:
        """Get category ID by name."""
        categories = self.get_categories(budget_id)
        for cat in categories:
            if cat.name.lower() == category_name.lower():
                return cat.category_id
        return None

    # =========================================================================
    # Read Operations - Transactions
    # =========================================================================

    def get_transactions(
        self,
        budget_id: str,
        account_id: Optional[str] = None,
        since_date: Optional[str] = None,
        unapproved_only: bool = False
    ) -> List[YNABTransaction]:
        """Get transactions for a budget or specific account."""
        if account_id:
            endpoint = f"/budgets/{budget_id}/accounts/{account_id}/transactions"
        else:
            endpoint = f"/budgets/{budget_id}/transactions"

        if since_date:
            endpoint += f"?since_date={since_date}"

        data = self._get(endpoint)
        transactions = []

        for trans in data.get("data", {}).get("transactions", []):
            # Filter unapproved if requested
            if unapproved_only and trans.get("approved", False):
                continue

            amount = Decimal(trans["amount"]) / 1000

            transaction = YNABTransaction(
                date=datetime.strptime(trans["date"], "%Y-%m-%d"),
                payee_name=trans.get("payee_name", ""),
                amount=amount,
                memo=trans.get("memo", ""),
                cleared=trans.get("cleared", ""),
                transaction_id=trans["id"],
                account_id=trans.get("account_id"),
                category_id=trans.get("category_id"),
                category_name=trans.get("category_name"),
                approved=trans.get("approved", False),
                flag_color=trans.get("flag_color"),
                subtransactions=trans.get("subtransactions", []),
                import_id=trans.get("import_id")
            )
            transactions.append(transaction)

        return transactions

    def find_transaction_by_memo(
        self,
        budget_id: str,
        memo_contains: str,
        since_date: Optional[str] = None,
    ) -> Optional[YNABTransaction]:
        """Find a transaction where the memo contains the given text (e.g., order ID)."""
        transactions = self.get_transactions(budget_id, since_date=since_date)
        for trans in transactions:
            if trans.memo and memo_contains in trans.memo:
                return trans
        return None

    def get_transactions_by_payee(
        self,
        budget_id: str,
        payee_names: List[str],
        since_date: Optional[str] = None,
        unapproved_only: bool = False
    ) -> List[YNABTransaction]:
        """Get transactions filtered by payee names."""
        all_transactions = self.get_transactions(
            budget_id,
            since_date=since_date,
            unapproved_only=unapproved_only
        )
        payee_names_lower = [p.lower() for p in payee_names]
        return [
            t for t in all_transactions
            if t.payee_name and t.payee_name.lower() in payee_names_lower
        ]

    def transaction_exists(self, budget_id: str, transaction_id: str) -> bool:
        """Check if a transaction exists by ID."""
        try:
            self._get(f"/budgets/{budget_id}/transactions/{transaction_id}")
            return True
        except Exception:
            return False

    def get_transaction_by_id(self, budget_id: str, transaction_id: str) -> Optional[YNABTransaction]:
        """Get a single transaction by ID with full details including subtransactions."""
        try:
            data = self._get(f"/budgets/{budget_id}/transactions/{transaction_id}")
            trans = data.get("data", {}).get("transaction", {})
            if not trans:
                return None

            amount = Decimal(trans["amount"]) / 1000

            return YNABTransaction(
                date=datetime.strptime(trans["date"], "%Y-%m-%d"),
                payee_name=trans.get("payee_name", ""),
                amount=amount,
                memo=trans.get("memo", ""),
                cleared=trans.get("cleared", ""),
                transaction_id=trans["id"],
                account_id=trans.get("account_id"),
                category_id=trans.get("category_id"),
                category_name=trans.get("category_name"),
                approved=trans.get("approved", False),
                flag_color=trans.get("flag_color"),
                subtransactions=trans.get("subtransactions", []),
                import_id=trans.get("import_id")
            )
        except Exception:
            return None

    def find_transaction_by_order_id(
        self,
        budget_id: str,
        order_id: str,
        since_date: Optional[str] = None,
    ) -> Optional[YNABTransaction]:
        """Find a transaction by Amazon order ID in memo.

        This method searches for transactions where the memo contains the order ID
        and returns the full transaction with subtransactions.

        Args:
            budget_id: The budget ID
            order_id: Amazon order ID (e.g., "123-4567890-1234567")
            since_date: Optional date to start search from (YYYY-MM-DD)

        Returns:
            YNABTransaction with full subtransactions data, or None if not found
        """
        # First find the transaction ID
        trans = self.find_transaction_by_memo(budget_id, order_id, since_date=since_date)
        if not trans:
            return None

        # Then fetch full details to ensure we have subtransactions
        return self.get_transaction_by_id(budget_id, trans.transaction_id)
