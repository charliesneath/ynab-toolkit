"""
Rebuild YNAB transactions from verified audit CSVs.

This script uses the audit CSVs as the source of truth for dates and amounts,
cross-referencing order history to get item details for categorization.
"""

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
import anthropic

load_dotenv()

from config import CLAUDE_MODEL
from ynab_client import YNABClient, YNABCategory
from ynab_writer import YNABWriter
from utils import (
    load_category_cache,
    get_cached_category,
    cache_category,
    save_category_cache,
    log,
)

# Paths
AUDIT_DIR = Path("data/processed/chase-amazon/audit")
ORDER_HISTORY_CRS = Path("data/amazon/order history crs")
ORDER_HISTORY_JSS = Path("data/amazon/order history jss")

# Shipping options that indicate grocery orders
GROCERY_SHIPPING_OPTIONS = {"scheduled-houdini", "scheduled-one-houdini"}

# Payee patterns that indicate grocery orders (fallback)
GROCERY_PAYEE_PATTERNS = ["whole foods", "amazon fresh", "amazon groce"]


@dataclass
class OrderItem:
    """An item from an Amazon order."""
    name: str
    unit_price: Decimal
    quantity: int
    total_owed: Decimal
    shipping_option: str = ""
    is_grocery: bool = False


@dataclass
class AuditTransaction:
    """A transaction from the audit CSV."""
    date: str
    tx_type: str
    amount: Decimal
    order_number: str
    tx_code: str  # Transaction code from statement (e.g., "YT1Z521A3")
    description: str
    merchant: str
    statement_source: str


@dataclass
class YNABTransactionData:
    """Data for creating a YNAB transaction."""
    date: str
    amount: Decimal  # Negative for outflows, positive for inflows
    payee_name: str
    memo: str
    category_id: Optional[str] = None
    flag_color: Optional[str] = "blue"
    import_id: Optional[str] = None
    subtransactions: List[Dict] = field(default_factory=list)


class OrderHistoryLoader:
    """Loads and manages order history from multiple CSV files."""

    def __init__(self):
        self.orders: Dict[str, List[OrderItem]] = {}
        self._load_all()

    def _load_all(self):
        """Load all order history CSV files."""
        # Retail order history files
        retail_files = [
            ORDER_HISTORY_CRS / "Retail.OrderHistory.1" / "Retail.OrderHistory.1.csv",
            ORDER_HISTORY_CRS / "Retail.OrderHistory.2" / "Retail.OrderHistory.2.csv",
            ORDER_HISTORY_JSS / "Retail.OrderHistory.1" / "Retail.OrderHistory.1.csv",
        ]

        # Digital items files
        digital_files = [
            ORDER_HISTORY_CRS / "Digital-Ordering.1" / "Digital Items.csv",
            ORDER_HISTORY_JSS / "Digital-Ordering.1" / "Digital Items.csv",
        ]

        for filepath in retail_files:
            if filepath.exists():
                self._load_retail_csv(filepath)
            else:
                log(f"Warning: Retail order history not found: {filepath}")

        for filepath in digital_files:
            if filepath.exists():
                self._load_digital_csv(filepath)
            else:
                log(f"Warning: Digital items file not found: {filepath}")

        log(f"Loaded {len(self.orders)} orders from order history")

    def _load_retail_csv(self, filepath: Path):
        """Load a retail order history CSV."""
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = row.get("Order ID", "").strip()
                if not order_id:
                    continue

                try:
                    unit_price = Decimal(row.get("Unit Price", "0").replace(",", "") or "0")
                    quantity = int(row.get("Quantity", "1") or "1")
                    total_owed_str = row.get("Total Owed", "0").replace(",", "").replace("'", "")
                    total_owed = Decimal(total_owed_str or "0")
                except (ValueError, TypeError):
                    continue

                shipping_option = row.get("Shipping Option", "").lower()
                is_grocery = shipping_option in GROCERY_SHIPPING_OPTIONS

                item = OrderItem(
                    name=row.get("Product Name", "Unknown Item"),
                    unit_price=unit_price,
                    quantity=quantity,
                    total_owed=total_owed,
                    shipping_option=shipping_option,
                    is_grocery=is_grocery,
                )

                if order_id not in self.orders:
                    self.orders[order_id] = []
                self.orders[order_id].append(item)

    def _load_digital_csv(self, filepath: Path):
        """Load a digital items CSV."""
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = row.get("OrderId", "").strip()
                if not order_id:
                    continue

                try:
                    price_str = row.get("OurPrice", "0").replace(",", "")
                    price = Decimal(price_str or "0")
                except (ValueError, TypeError):
                    continue

                item = OrderItem(
                    name=row.get("ProductName", "Digital Item"),
                    unit_price=price,
                    quantity=1,
                    total_owed=price,
                    shipping_option="digital",
                    is_grocery=False,
                )

                if order_id not in self.orders:
                    self.orders[order_id] = []
                self.orders[order_id].append(item)

    def get_items(self, order_id: str) -> List[OrderItem]:
        """Get items for an order ID."""
        return self.orders.get(order_id, [])

    def is_grocery_order(self, order_id: str) -> bool:
        """Check if an order is a grocery order based on shipping option."""
        items = self.get_items(order_id)
        return any(item.is_grocery for item in items)


class Categorizer:
    """Handles categorization of items using Claude and cache."""

    def __init__(self, categories: List[YNABCategory], rules_file: str = "category_rules.json"):
        self.categories = categories
        self.cat_lookup = {cat.name: cat.category_id for cat in categories}
        self.cat_names = [cat.name for cat in categories]
        self.client = anthropic.Anthropic()
        self.rules = self._load_rules(rules_file)

        # Load category cache
        load_category_cache(Path("data/processed/chase-amazon"))

    def _load_rules(self, rules_file: str) -> Dict:
        """Load category rules from JSON file."""
        try:
            with open(rules_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"categories": {}, "excluded_groups": []}

    def get_category_id(self, category_name: str) -> Optional[str]:
        """Get category ID by name with fuzzy matching."""
        # Exact match
        if category_name in self.cat_lookup:
            return self.cat_lookup[category_name]

        # Fuzzy match
        name_lower = category_name.lower()
        for cat in self.categories:
            if name_lower in cat.name.lower() or cat.name.lower() in name_lower:
                return cat.category_id

        return None

    def categorize_items(self, items: List[str]) -> Dict[str, str]:
        """Categorize a list of item names. Returns dict of item -> category_name."""
        result = {}
        uncached_items = []

        # Check cache first
        for item in items:
            cached = get_cached_category(item)
            if cached:
                result[item] = cached
            else:
                uncached_items.append(item)

        if not uncached_items:
            return result

        # Categorize uncached items via Claude
        items_list = "\n".join([f"- {item[:80]}" for item in uncached_items])

        # Filter categories based on rules (exclude certain groups)
        excluded = self.rules.get("excluded_groups", [])
        available_cats = [c.name for c in self.categories if c.group_name not in excluded]
        categories_str = ", ".join(available_cats)

        prompt = f"""Categorize these Amazon items into budget categories. Return JSON only.

Items:
{items_list}

Categories: {categories_str}

Return: {{"items": [{{"item": "item name", "category": "category name"}}]}}

Important: If you're uncertain about an item, use "Uncategorized" as the category."""

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )

            if response.content:
                response_text = response.content[0].text
                if "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]

                data = json.loads(response_text.strip())
                for item_data in data.get("items", []):
                    item_name = item_data.get("item", "")
                    cat_name = item_data.get("category", "Uncategorized")

                    # Find matching original item
                    for orig_item in uncached_items:
                        if orig_item[:80] == item_name or item_name in orig_item:
                            result[orig_item] = cat_name
                            cache_category(orig_item, cat_name)
                            break
        except Exception as e:
            log(f"  Warning: Categorization failed: {e}")
            for item in uncached_items:
                result[item] = "Uncategorized"

        save_category_cache()
        return result


class YNABRebuilder:
    """Main class for rebuilding YNAB transactions from audit data."""

    def __init__(self, ynab_client: YNABClient, budget_id: str, account_id: str, checking_account_id: str, dry_run: bool = False):
        self.ynab = ynab_client
        self.writer = YNABWriter(ynab_client)
        self.budget_id = budget_id
        self.account_id = account_id
        self.checking_account_id = checking_account_id
        self.dry_run = dry_run

        # Load order history
        log("Loading order history...")
        self.order_history = OrderHistoryLoader()

        # Get categories and setup categorizer
        log("Loading YNAB categories...")
        self.categories = self.ynab.get_categories(budget_id)
        self.categorizer = Categorizer(self.categories)

        # Find specific category IDs
        # Try multiple names for Groceries category
        self.groceries_cat_id = (
            self.ynab.get_category_id(budget_id, "Groceries") or
            self.ynab.get_category_id(budget_id, "🍌Groceries") or
            self._find_category_containing("groceries")
        )
        self.delivery_fee_cat_id = self.ynab.get_category_id(budget_id, "Delivery Fee")
        self.donations_cat_id = self.ynab.get_category_id(budget_id, "Donations")

        log(f"  Groceries category: {self.groceries_cat_id}")
        log(f"  Delivery Fee category: {self.delivery_fee_cat_id}")
        log(f"  Donations category: {self.donations_cat_id}")

    def _find_category_containing(self, name: str) -> Optional[str]:
        """Find a category ID where the name contains the given string."""
        name_lower = name.lower()
        for cat in self.categories:
            if name_lower in cat.name.lower():
                return cat.category_id
        return None

    def load_audit_month(self, year: int, month: int) -> List[AuditTransaction]:
        """Load transactions from an audit CSV for a specific month."""
        month_names = {
            1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun",
            7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec"
        }

        filename = f"{year}-{month:02d}-{month_names[month]}.csv"
        filepath = AUDIT_DIR / filename

        if not filepath.exists():
            log(f"Warning: Audit file not found: {filepath}")
            return []

        # Calculate 5-year cutoff date
        from datetime import date, timedelta
        cutoff_date = (date.today() - timedelta(days=5*365)).isoformat()

        transactions = []
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip transactions from earliest statement (before our starting balance)
                # The first statement is configured per-account
                statement_source = row.get("Statement Source", "")
                try:
                    from config_private import CARD_IDENTIFIERS
                    card_id = CARD_IDENTIFIERS.get("amazon_card", "")
                    skip_statement = f"20210104-statements-{card_id}-.pdf"
                except ImportError:
                    skip_statement = ""

                if skip_statement and statement_source == skip_statement:
                    continue

                # Skip transactions older than 5 years (YNAB limit)
                tx_date = row.get("Date", "")
                if tx_date < cutoff_date:
                    log(f"  Skipping (>5 years old): {tx_date}")
                    continue

                # Parse amount
                amount_str = row.get("Amount", "$0.00")
                if amount_str.startswith("-"):
                    amount = -Decimal(amount_str[2:])  # Remove -$ prefix
                else:
                    amount = Decimal(amount_str[1:])  # Remove $ prefix

                transactions.append(AuditTransaction(
                    date=row["Date"],
                    tx_type=row["Type"],
                    amount=amount,
                    order_number=row.get("Order Number", ""),
                    tx_code=row.get("Transaction Code", ""),  # Unique code per charge
                    description=row.get("Description", ""),
                    merchant=row.get("Merchant", ""),
                    statement_source=statement_source,
                ))

        return transactions

    def is_grocery_by_payee(self, description: str, merchant: str) -> bool:
        """Check if transaction is grocery based on payee/description."""
        text = f"{description} {merchant}".lower()
        return any(pattern in text for pattern in GROCERY_PAYEE_PATTERNS)

    def create_import_id(self, tx_code: str, amount_cents: int, is_refund: bool = False, date: str = "") -> str:
        """Create a unique import_id for a transaction (max 36 chars).

        Uses transaction code (e.g., 'YT1Z521A3') for uniqueness instead of order number,
        since one order can have multiple charges (split shipments).
        """
        suffix = "R" if is_refund else "P"
        # Use tx_code for uniqueness - this is unique per charge on the statement
        # Fallback to date if no tx_code (for payments, etc.)
        unique_part = tx_code[:12] if tx_code else f"TX{date.replace('-', '')}"
        # Format: RB5:{tx_code}:{amount}:{P|R}
        return f"RB5:{unique_part}:{amount_cents}:{suffix}"

    def build_transaction(self, tx: AuditTransaction) -> Optional[YNABTransactionData]:
        """Build a YNAB transaction from an audit transaction."""
        # Skip Points Redemption
        if tx.tx_type == "Points Redemption":
            log(f"  Skipping Points Redemption: {tx.date} ${tx.amount}")
            return None

        amount_cents = int(tx.amount * 100)
        import_id = self.create_import_id(
            tx.tx_code,  # Use transaction code for uniqueness
            amount_cents,
            is_refund=(tx.tx_type == "Refund"),
            date=tx.date
        )

        # Payment - credit card payment (shows as positive inflow to card)
        if tx.tx_type == "Payment":
            return YNABTransactionData(
                date=tx.date,
                amount=abs(tx.amount),  # Positive inflow (payment received)
                payee_name="Chase Payment",
                memo="Payment Thank You",
                category_id=None,  # Payments don't need categories
                flag_color="blue",
                import_id=import_id,
            )

        # Tip - Delivery Fee category
        if tx.tx_type == "Tip":
            return YNABTransactionData(
                date=tx.date,
                amount=-abs(tx.amount),  # Outflow (negative)
                payee_name="Amazon.com",
                memo=f"Tip: {tx.description[:100]}",
                category_id=self.delivery_fee_cat_id,
                flag_color="blue",
                import_id=import_id,
            )

        # Donation - Donations category
        if tx.tx_type == "Donation":
            return YNABTransactionData(
                date=tx.date,
                amount=-abs(tx.amount),  # Outflow (negative)
                payee_name="Amazon.com",
                memo=f"Donation: {tx.description[:100]}",
                category_id=self.donations_cat_id,
                flag_color="blue",
                import_id=import_id,
            )

        # Fee - bank fees
        if tx.tx_type == "Fee":
            return YNABTransactionData(
                date=tx.date,
                amount=-abs(tx.amount),  # Outflow (negative)
                payee_name="Chase",
                memo=f"Fee: {tx.description[:100]}",
                category_id=None,  # Leave uncategorized for manual review
                flag_color=None,
                import_id=import_id,
            )

        # Interest - interest charges
        if tx.tx_type == "Interest":
            return YNABTransactionData(
                date=tx.date,
                amount=-abs(tx.amount),  # Outflow (negative)
                payee_name="Chase",
                memo=f"Interest: {tx.description[:100]}",
                category_id=None,  # Leave uncategorized for manual review
                flag_color=None,
                import_id=import_id,
            )

        # Refund - positive inflow
        if tx.tx_type == "Refund":
            return self._build_refund_transaction(tx, import_id)

        # Purchase/Digital - may need itemization
        return self._build_purchase_transaction(tx, import_id)

    def _build_refund_transaction(self, tx: AuditTransaction, import_id: str) -> YNABTransactionData:
        """Build a refund transaction (positive inflow)."""
        items = self.order_history.get_items(tx.order_number) if tx.order_number else []

        category_id = None
        memo = f"Refund: {tx.description[:100]}"

        if items:
            # Try to get category from original item
            item_names = [item.name for item in items]
            categories = self.categorizer.categorize_items(item_names)
            if categories:
                first_cat = list(categories.values())[0]
                category_id = self.categorizer.get_category_id(first_cat)
            memo = f"Refund: {items[0].name[:100]}"

        return YNABTransactionData(
            date=tx.date,
            amount=abs(tx.amount),  # Positive inflow
            payee_name="Amazon.com",
            memo=memo,
            category_id=category_id,
            flag_color="blue",
            import_id=import_id,
        )

    def _build_purchase_transaction(self, tx: AuditTransaction, import_id: str) -> YNABTransactionData:
        """Build a purchase transaction with potential splits."""
        items = self.order_history.get_items(tx.order_number) if tx.order_number else []

        # Check if it's a grocery order
        is_grocery = False
        if tx.order_number:
            is_grocery = self.order_history.is_grocery_order(tx.order_number)
        if not is_grocery:
            is_grocery = self.is_grocery_by_payee(tx.description, tx.merchant)

        # Grocery orders - single Groceries category, no itemization
        if is_grocery:
            return YNABTransactionData(
                date=tx.date,
                amount=-abs(tx.amount),  # Outflow (negative)
                payee_name="Amazon Fresh" if "fresh" in tx.description.lower() else "Whole Foods",
                memo=f"Order: {tx.order_number}" if tx.order_number else tx.description[:100],
                category_id=self.groceries_cat_id,
                flag_color="blue",
                import_id=import_id,
            )

        # No items found - create single split with description so user can see what it was
        if not items:
            total_milliunits = int(abs(tx.amount) * 1000)
            return YNABTransactionData(
                date=tx.date,
                amount=-abs(tx.amount),  # Outflow (negative)
                payee_name="Amazon.com",
                memo=f"Order: {tx.order_number}" if tx.order_number else tx.description[:100],
                category_id=None,  # Leave uncategorized
                flag_color=None,  # No flag for uncategorized
                import_id=import_id,
                subtransactions=[{
                    "amount": -total_milliunits,
                    "memo": tx.description[:200],  # Use description as item name
                }],
            )

        # Items found - create split transaction
        return self._build_split_transaction(tx, items, import_id)

    def _build_split_transaction(
        self, tx: AuditTransaction, items: List[OrderItem], import_id: str
    ) -> YNABTransactionData:
        """Build a split transaction with categorized items."""
        # Categorize all items
        item_names = [item.name for item in items]
        categories = self.categorizer.categorize_items(item_names)

        # Calculate total from items
        items_total = sum(item.total_owed for item in items)

        # Work in milliunits to avoid rounding issues
        total_milliunits = int(abs(tx.amount) * 1000)
        remaining_milliunits = total_milliunits

        # Build subtransactions
        subtransactions = []

        for i, item in enumerate(items):
            cat_name = categories.get(item.name, "Uncategorized")
            cat_id = self.categorizer.get_category_id(cat_name)

            # For last item, use remaining to ensure exact sum
            if i == len(items) - 1:
                item_milliunits = remaining_milliunits
            else:
                # Calculate proportional amount
                if items_total > 0:
                    proportion = float(item.total_owed / items_total)
                    item_milliunits = int(total_milliunits * proportion)
                else:
                    item_milliunits = int(float(item.total_owed) * 1000)

                # Don't exceed remaining
                item_milliunits = min(item_milliunits, remaining_milliunits)
                remaining_milliunits -= item_milliunits

            sub = {
                "amount": -item_milliunits,  # Negative for outflow
                "memo": item.name[:200],
            }
            # Only include category_id if we have one (leave uncategorized otherwise)
            if cat_id:
                sub["category_id"] = cat_id
            subtransactions.append(sub)

        # Check if any subtransactions are uncategorized
        has_uncategorized = any(sub["category_id"] is None for sub in subtransactions)

        return YNABTransactionData(
            date=tx.date,
            amount=-abs(tx.amount),  # Outflow (negative)
            payee_name="Amazon.com",
            memo=f"Order: {tx.order_number}" if tx.order_number else tx.description[:100],
            category_id=None,  # Split transactions don't have a parent category
            flag_color="blue" if not has_uncategorized else None,
            import_id=import_id,
            subtransactions=subtransactions,
        )

    def process_month(self, year: int, month: int) -> Tuple[int, int, int]:
        """Process all transactions for a month. Returns (created, skipped, errors)."""
        log(f"\n{'='*60}")
        log(f"Processing {year}-{month:02d}")
        log(f"{'='*60}")

        transactions = self.load_audit_month(year, month)
        log(f"Loaded {len(transactions)} transactions from audit CSV")

        created = 0
        skipped = 0
        errors = 0
        batch = []

        for tx in transactions:
            try:
                ynab_tx = self.build_transaction(tx)
                if ynab_tx is None:
                    skipped += 1
                    continue

                # Build YNAB API transaction format
                tx_data = {
                    "account_id": self.account_id,
                    "date": ynab_tx.date,
                    "amount": int(ynab_tx.amount * 1000),  # Milliunits
                    "payee_name": ynab_tx.payee_name,
                    "approved": False,  # Don't auto-approve
                }

                if ynab_tx.memo:
                    tx_data["memo"] = ynab_tx.memo[:200]
                if ynab_tx.category_id:
                    tx_data["category_id"] = ynab_tx.category_id
                if ynab_tx.flag_color:
                    tx_data["flag_color"] = ynab_tx.flag_color
                if ynab_tx.import_id:
                    tx_data["import_id"] = ynab_tx.import_id
                if ynab_tx.subtransactions:
                    tx_data["subtransactions"] = ynab_tx.subtransactions

                batch.append(tx_data)
                log(f"  + {tx.date} {tx.tx_type}: ${tx.amount} -> {ynab_tx.payee_name}")

            except Exception as e:
                log(f"  ERROR processing {tx.date} {tx.tx_type}: {e}")
                errors += 1

        # Send batch to YNAB
        if batch and not self.dry_run:
            try:
                result = self.writer.create_transactions_batch(self.budget_id, batch)
                created = len(result.get("transactions", []))
                duplicates = len(result.get("duplicate_import_ids", []))
                log(f"\nCreated {created} transactions, {duplicates} duplicates skipped")
            except Exception as e:
                log(f"\nERROR sending batch to YNAB: {e}")
                # Try to get more details from requests exception
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        log(f"Response body: {e.response.text}")
                    except:
                        pass
                # Debug: print first transaction in batch
                if batch:
                    import json
                    log(f"First transaction in batch: {json.dumps(batch[0], indent=2)}")
                errors += len(batch)
        elif batch:
            log(f"\n[DRY RUN] Would create {len(batch)} transactions")
            created = len(batch)

        return created, skipped, errors


def main():
    parser = argparse.ArgumentParser(description="Rebuild YNAB transactions from audit CSVs")
    parser.add_argument("--year", type=int, required=True, help="Year to process")
    parser.add_argument("--month", type=int, required=True, help="Month to process (1-12)")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually create transactions")
    args = parser.parse_args()

    # Get YNAB configuration from environment
    ynab_token = os.getenv("YNAB_TOKEN")
    if not ynab_token:
        log("ERROR: YNAB_TOKEN not found in environment or .env file")
        return 1

    budget_name = os.getenv("BUDGET_NAME", "Primary Budget")
    account_name = os.getenv("ACCOUNT_NAME", "Chase Amazon")
    checking_account_name = os.getenv("CHECKING_ACCOUNT_NAME", "Checking")

    # Initialize YNAB client to get IDs
    ynab = YNABClient(ynab_token)
    budget_id = ynab.get_budget_id(budget_name)
    if not budget_id:
        log(f"ERROR: Budget '{budget_name}' not found")
        return 1

    account_id = ynab.get_account_id(budget_id, account_name)
    if not account_id:
        log(f"ERROR: Account '{account_name}' not found")
        return 1

    checking_account_id = ynab.get_account_id(budget_id, checking_account_name)
    if not checking_account_id:
        log(f"Warning: Checking account '{checking_account_name}' not found")
        checking_account_id = None

    log(f"Budget: {budget_name} ({budget_id})")
    log(f"Account: {account_name} ({account_id})")
    if args.dry_run:
        log("DRY RUN MODE - no transactions will be created")

    # Process the month
    rebuilder = YNABRebuilder(ynab, budget_id, account_id, checking_account_id, dry_run=args.dry_run)
    created, skipped, errors = rebuilder.process_month(args.year, args.month)

    log(f"\n{'='*60}")
    log(f"Summary: {created} created, {skipped} skipped, {errors} errors")
    log(f"{'='*60}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    exit(main())
