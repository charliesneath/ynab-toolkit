"""Create split transactions for reconciliation charges with itemized line items."""

import csv
import os
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()


def load_order_items():
    """Load order items with prices. Returns order_id -> list of (product, price).

    Also returns grocery_orders set for orders that shouldn't be itemized.
    """
    orders = defaultdict(list)
    grocery_orders = set()

    # Retail order history files
    retail_files = [
        "data/amazon/order history crs/Retail.OrderHistory.1/Retail.OrderHistory.1.csv",
        "data/amazon/order history crs/Retail.OrderHistory.2/Retail.OrderHistory.2.csv",
        "data/amazon/order history jss/Retail.OrderHistory.1/Retail.OrderHistory.1.csv",
    ]

    for filepath in retail_files:
        if not os.path.exists(filepath):
            continue

        print(f"  Loading {filepath}")
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = row.get('Order ID', '').strip()
                product = row.get('Product Name', '').strip()
                shipping = row.get('Shipping Option', '').lower()

                # Mark grocery orders (Whole Foods, Amazon Fresh)
                if 'houdini' in shipping or 'fresh' in shipping:
                    grocery_orders.add(order_id)

                # Get price: Total Owed includes tax
                price_str = row.get('Total Owed', '0').replace("'", "").strip()
                try:
                    price = Decimal(price_str) if price_str else Decimal('0')
                except:
                    price = Decimal('0')

                if order_id and product and product != 'Not Available' and price > 0:
                    orders[order_id].append((product, price))

    # Digital order files
    digital_files = [
        "data/amazon/order history crs/Digital-Ordering.1/Digital Items.csv",
        "data/amazon/order history jss/Digital-Ordering.1/Digital Items.csv",
    ]

    for filepath in digital_files:
        if not os.path.exists(filepath):
            continue

        print(f"  Loading {filepath}")
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = row.get('OrderId', '').strip()
                product = row.get('ProductName', '').strip()
                price_str = row.get('OurPrice', '0').strip()

                try:
                    price = Decimal(price_str) if price_str else Decimal('0')
                except:
                    price = Decimal('0')

                if order_id and product and product != 'Not Available' and price > 0:
                    # Avoid duplicates
                    existing = [p for p, _ in orders[order_id]]
                    if product not in existing:
                        orders[order_id].append((product, price))

    print(f"  Loaded {len(orders)} unique orders with item details")
    print(f"  Identified {len(grocery_orders)} grocery orders (Whole Foods/Fresh)")
    return orders, grocery_orders


def extract_order_number(memo):
    """Extract order number from memo."""
    if not memo:
        return None
    match = re.search(r'(11[1-4]-\d{7}-\d{7}|D01-\d{7}-\d{7})', memo)
    return match.group(1) if match else None


def main():
    token = os.getenv("YNAB_TOKEN")
    if not token:
        print("Error: YNAB_TOKEN not found")
        return

    client = YNABClient(token)
    budget_id = "b35a5d8d-39ae-463c-9d76-fdf88182c6f7"
    account_id = "60e777c8-1a41-48af-8a35-b6dbb1807946"

    print("Loading order items with prices...")
    orders, grocery_orders = load_order_items()

    print("\nFetching YNAB transactions...")
    transactions = client.get_transactions(budget_id, account_id, since_date="2020-01-01")

    # Find uncategorized transactions that have order numbers but no subtransactions
    # These are reconciliation charges that need itemization
    recon_txns = []
    for t in transactions:
        memo = t.memo or ""
        order_num = extract_order_number(memo)

        if not order_num:
            continue

        # Only process uncategorized transactions
        if t.category_id is not None and t.category_name != "Uncategorized":
            continue

        # Skip if already has subtransactions (already itemized)
        if t.subtransactions and len(t.subtransactions) > 0:
            continue

        # Only include orders we have item data for
        if order_num not in orders:
            continue

        recon_txns.append(t)

    print(f"Found {len(recon_txns)} reconciliation transactions to itemize")

    updates = []
    for t in recon_txns:
        order_num = extract_order_number(t.memo)
        if not order_num:
            print(f"  SKIP: No order number: {t.memo}")
            continue

        items = orders.get(order_num, [])
        if not items:
            print(f"  SKIP: No items found for {order_num}")
            continue

        # Transaction amount (negative for outflows)
        txn_amount = t.amount  # Decimal, negative for outflows
        txn_abs = abs(txn_amount)

        # Check if likely a tip (round amounts)
        is_tip = txn_abs in [Decimal('5.00'), Decimal('10.00'), Decimal('15.00'), Decimal('20.00')]

        # Skip grocery orders (Whole Foods, Amazon Fresh) - not itemized per PRD
        # But allow tips through (they still need the order number format)
        if order_num in grocery_orders and not is_tip:
            print(f"  SKIP (grocery): ${txn_abs} for {order_num}")
            continue

        # Check if items total approximately matches transaction
        items_total = sum(price for _, price in items)
        diff = abs(items_total - txn_abs)
        if diff > Decimal('5.00') and diff / txn_abs > Decimal('0.1'):
            # Amount mismatch - still create split with single line using transaction amount
            print(f"  INFO: Amount mismatch ${txn_abs} vs items ${items_total} for {order_num} - using single split")

        print(f"\n  {t.date.strftime('%Y-%m-%d')} ${txn_abs:.2f} - Order {order_num}")

        # Build splits
        splits = []

        if is_tip:
            # Tip - single split with "Delivery Tip" memo
            splits.append({
                "amount": txn_amount,
                "category_id": None,
                "memo": "Delivery Tip"
            })
            print(f"    Tip: Delivery Tip")
        elif len(items) == 1 or diff > Decimal('5.00'):
            # Single item or amount mismatch - single split with product name
            product = items[0][0] if items else "Amazon purchase"
            splits.append({
                "amount": txn_amount,
                "category_id": None,
                "memo": product[:200]
            })
            print(f"    Single split: {product[:60]}...")
        else:
            # Multiple items - proportionally distribute
            print(f"    {len(items)} items:")
            running_total = Decimal('0')

            for i, (product, price) in enumerate(items):
                if i == len(items) - 1:
                    # Last item gets remainder to ensure exact total
                    item_amount = txn_amount - running_total
                else:
                    # Proportional allocation
                    if items_total > 0:
                        ratio = price / items_total
                        item_amount = (txn_amount * ratio).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    else:
                        item_amount = Decimal('0')
                    running_total += item_amount

                splits.append({
                    "amount": item_amount,
                    "category_id": None,
                    "memo": product[:200]
                })
                print(f"      ${abs(item_amount):.2f} - {product[:60]}...")

        updates.append({
            'transaction': t,
            'splits': splits,
            'order_num': order_num
        })

    if not updates:
        print("\nNo transactions to update.")
        return

    print(f"\n{len(updates)} transactions to split into itemized line items...")
    print("\nUpdating transactions...")

    for u in updates:
        t = u['transaction']
        splits = u['splits']

        try:
            # create_split_transaction expects splits with 'amount' as Decimal
            client.create_split_transaction(
                budget_id=budget_id,
                transaction_id=t.transaction_id,
                splits=splits,
                memo=f"Order {u['order_num']}",
                approved=False
            )
            print(f"  Split {t.transaction_id[:8]}... into {len(splits)} items")
        except Exception as e:
            print(f"  ERROR splitting {t.transaction_id[:8]}: {e}")

    print("\nDone!")


if __name__ == '__main__':
    main()
