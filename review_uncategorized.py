"""Review and itemize uncategorized Amazon transactions."""

import os
import csv
import re
from collections import defaultdict
from decimal import Decimal
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()


def load_order_data():
    """Load order items and identify grocery orders."""
    orders = defaultdict(list)
    grocery_orders = set()

    retail_files = [
        'data/amazon/order history crs/Retail.OrderHistory.1/Retail.OrderHistory.1.csv',
        'data/amazon/order history crs/Retail.OrderHistory.2/Retail.OrderHistory.2.csv',
        'data/amazon/order history jss/Retail.OrderHistory.1/Retail.OrderHistory.1.csv',
    ]
    for filepath in retail_files:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    order_id = row.get('Order ID', '').strip()
                    product = row.get('Product Name', '').strip()
                    shipping = row.get('Shipping Option', '').lower()
                    if 'houdini' in shipping or 'fresh' in shipping:
                        grocery_orders.add(order_id)
                    price_str = row.get('Total Owed', '0').replace("'", '').strip()
                    try:
                        price = Decimal(price_str) if price_str else Decimal('0')
                    except:
                        price = Decimal('0')
                    if order_id and product and product != 'Not Available' and price > 0:
                        orders[order_id].append((product, price))

    digital_files = [
        'data/amazon/order history crs/Digital-Ordering.1/Digital Items.csv',
        'data/amazon/order history jss/Digital-Ordering.1/Digital Items.csv',
    ]
    for filepath in digital_files:
        if os.path.exists(filepath):
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
                        existing = [p for p, _ in orders[order_id]]
                        if product not in existing:
                            orders[order_id].append((product, price))

    return orders, grocery_orders


def extract_order(memo):
    if not memo:
        return None
    match = re.search(r'(11[1-4]-\d{7}-\d{7}|D01-\d{7}-\d{7})', memo)
    return match.group(1) if match else None


def main():
    client = YNABClient(os.getenv('YNAB_TOKEN'))
    budget_id = 'b35a5d8d-39ae-463c-9d76-fdf88182c6f7'
    account_id = '60e777c8-1a41-48af-8a35-b6dbb1807946'

    print("Loading order data...")
    orders, grocery_orders = load_order_data()
    print(f"  {len(orders)} orders, {len(grocery_orders)} grocery orders")

    print("\nFetching transactions...")
    transactions = client.get_transactions(budget_id, account_id, since_date='2020-01-01')

    print('\nUncategorized transactions:')
    print('=' * 80)

    uncategorized = []
    for t in transactions:
        is_uncategorized = False
        if t.category_name == 'Uncategorized' or t.category_id is None:
            is_uncategorized = True
        elif t.subtransactions:
            for sub in t.subtransactions:
                if sub.get('category_name') == 'Uncategorized' or sub.get('category_id') is None:
                    is_uncategorized = True
                    break

        if not is_uncategorized:
            continue

        order_num = extract_order(t.memo)
        has_splits = t.subtransactions and len(t.subtransactions) > 0

        if order_num in grocery_orders:
            txn_type = 'GROCERY'
        elif order_num and order_num.startswith('D01'):
            txn_type = 'DIGITAL'
        elif order_num:
            txn_type = 'AMAZON'
        else:
            txn_type = 'UNKNOWN'

        items = orders.get(order_num, []) if order_num else []

        uncategorized.append({
            't': t,
            'order': order_num,
            'type': txn_type,
            'items': items,
            'has_splits': has_splits
        })

    uncategorized.sort(key=lambda x: x['t'].date)

    for item in uncategorized:
        t = item['t']
        print(f"{t.date.strftime('%Y-%m-%d')} | ${abs(t.amount):>8.2f} | {item['type']:8} | {item['order'] or 'No order#'}")
        if item['has_splits']:
            print(f"  Has {len(t.subtransactions)} splits already")
        if item['items']:
            for prod, price in item['items'][:3]:
                print(f"    - {prod[:60]}")
            if len(item['items']) > 3:
                print(f"    ... and {len(item['items'])-3} more items")
        elif item['order']:
            print(f"    (No item data found)")
        print()

    print(f'Total: {len(uncategorized)} uncategorized transactions')
    return uncategorized


if __name__ == '__main__':
    main()
