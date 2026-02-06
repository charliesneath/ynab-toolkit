"""Itemize reconciliation charges with product names from order history."""

import csv
import os
import re
from collections import defaultdict
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()


def load_order_history():
    """Load all order history CSVs and build order_id -> product names mapping."""
    orders = defaultdict(list)

    # Retail order history files
    retail_files = [
        "data/amazon/order history crs/Retail.OrderHistory.1/Retail.OrderHistory.1.csv",
        "data/amazon/order history crs/Retail.OrderHistory.2/Retail.OrderHistory.2.csv",
        "data/amazon/order history jss/Retail.OrderHistory.1/Retail.OrderHistory.1.csv",
    ]

    for filepath in retail_files:
        if not os.path.exists(filepath):
            print(f"  Skipping {filepath} (not found)")
            continue

        print(f"  Loading {filepath}")
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = row.get('Order ID', '').strip()
                product = row.get('Product Name', '').strip()
                if order_id and product and product != 'Not Available':
                    # Shorten product name for memo
                    short_product = product[:50] + '...' if len(product) > 50 else product
                    orders[order_id].append(short_product)

    # Digital order files (D01 orders)
    digital_files = [
        "data/amazon/order history crs/Digital-Ordering.1/Digital Items.csv",
        "data/amazon/order history jss/Digital-Ordering.1/Digital Items.csv",
    ]

    for filepath in digital_files:
        if not os.path.exists(filepath):
            print(f"  Skipping {filepath} (not found)")
            continue

        print(f"  Loading {filepath}")
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_id = row.get('OrderId', '').strip()
                product = row.get('ProductName', '').strip()
                if order_id and product and product != 'Not Available':
                    short_product = product[:50] + '...' if len(product) > 50 else product
                    if short_product not in orders[order_id]:
                        orders[order_id].append(short_product)

    print(f"  Loaded {len(orders)} unique orders")
    return orders


def extract_order_number(memo):
    """Extract order number from memo."""
    if not memo:
        return None
    # Match order patterns
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

    print("Loading order history...")
    orders = load_order_history()

    print("\nFetching YNAB transactions...")
    transactions = client.get_transactions(budget_id, account_id, since_date="2020-01-01")

    # Find reconciliation transactions
    recon_txns = []
    for t in transactions:
        memo = t.memo or ""
        if "reconciliation" in memo.lower() or "missing from sync" in memo.lower():
            recon_txns.append(t)

    print(f"Found {len(recon_txns)} reconciliation transactions")

    # Process each
    updates = []
    for t in recon_txns:
        order_num = extract_order_number(t.memo)
        if not order_num:
            print(f"  SKIP: No order number in memo: {t.memo}")
            continue

        products = orders.get(order_num, [])
        if not products:
            print(f"  SKIP: No products found for {order_num}")
            continue

        # Build new memo with items
        items_str = ", ".join(products[:3])  # Max 3 items
        if len(products) > 3:
            items_str += f" +{len(products)-3} more"

        new_memo = f"Order {order_num}: {items_str}"
        if len(new_memo) > 200:
            new_memo = new_memo[:197] + "..."

        print(f"  {t.date.strftime('%Y-%m-%d')} ${abs(t.amount):.2f}")
        print(f"    OLD: {t.memo}")
        print(f"    NEW: {new_memo}")

        updates.append({
            'id': t.transaction_id,
            'memo': new_memo
        })

    if not updates:
        print("\nNo updates to make.")
        return

    print(f"\n{len(updates)} transactions to update...")
    print("\nUpdating transactions...")
    for u in updates:
        client.update_transaction(budget_id, u['id'], memo=u['memo'])
        print(f"  Updated {u['id'][:8]}...")

    print("Done!")


if __name__ == '__main__':
    main()
