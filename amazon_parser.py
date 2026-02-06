"""Parser for Amazon order history CSV exports."""

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Optional


@dataclass
class AmazonItem:
    """Represents a single item from an Amazon order."""
    order_id: str
    order_date: datetime
    title: str
    category: str  # Amazon's category
    quantity: int
    item_total: Decimal

    def __repr__(self):
        return f"AmazonItem(title='{self.title[:40]}...', total={self.item_total})"


@dataclass
class AmazonOrder:
    """Represents an Amazon order with all its items."""
    order_id: str
    order_date: datetime
    total: Decimal
    items: List[AmazonItem]

    def __repr__(self):
        return f"AmazonOrder(id={self.order_id}, date={self.order_date.strftime('%Y-%m-%d')}, total={self.total}, items={len(self.items)})"


def parse_amazon_csv(csv_path: str) -> List[AmazonOrder]:
    """
    Parse an Amazon order history CSV export.

    Amazon's order history CSV typically has columns like:
    - Order ID
    - Order Date
    - Title
    - Category
    - Quantity
    - Item Total
    - etc.

    Returns:
        List of AmazonOrder objects grouped by order ID
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    items_by_order: Dict[str, List[AmazonItem]] = {}
    order_dates: Dict[str, datetime] = {}

    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        # Normalize column names (handle various CSV formats)
        fieldnames = [name.strip().lower().replace(' ', '_') for name in reader.fieldnames or []]

        for row in reader:
            # Create normalized row
            normalized_row = {
                fieldnames[i]: v.strip()
                for i, v in enumerate(row.values())
            }

            # Extract fields (handle different column name variations)
            order_id = (
                normalized_row.get('order_id') or
                normalized_row.get('order_number') or
                normalized_row.get('orderid') or
                ''
            )

            date_str = (
                normalized_row.get('order_date') or
                normalized_row.get('date') or
                normalized_row.get('orderdate') or
                ''
            )

            title = (
                normalized_row.get('title') or
                normalized_row.get('product_name') or
                normalized_row.get('item_name') or
                normalized_row.get('product') or
                ''
            )

            category = (
                normalized_row.get('category') or
                normalized_row.get('product_category') or
                ''
            )

            quantity_str = (
                normalized_row.get('quantity') or
                normalized_row.get('qty') or
                '1'
            )

            total_str = (
                normalized_row.get('item_total') or
                normalized_row.get('total') or
                normalized_row.get('price') or
                normalized_row.get('item_subtotal') or
                '0'
            )

            if not order_id or not title:
                continue

            # Parse date
            order_date = None
            for fmt in ['%m/%d/%Y', '%Y-%m-%d', '%m/%d/%y', '%d/%m/%Y']:
                try:
                    order_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue

            if not order_date:
                continue

            # Parse amount (remove currency symbols)
            total_clean = total_str.replace('$', '').replace(',', '').strip()
            try:
                item_total = Decimal(total_clean)
            except:
                item_total = Decimal('0')

            # Parse quantity
            try:
                quantity = int(quantity_str)
            except:
                quantity = 1

            item = AmazonItem(
                order_id=order_id,
                order_date=order_date,
                title=title,
                category=category,
                quantity=quantity,
                item_total=item_total
            )

            if order_id not in items_by_order:
                items_by_order[order_id] = []
                order_dates[order_id] = order_date

            items_by_order[order_id].append(item)

    # Create order objects
    orders = []
    for order_id, items in items_by_order.items():
        order_total = sum((item.item_total for item in items), Decimal('0'))
        orders.append(AmazonOrder(
            order_id=order_id,
            order_date=order_dates[order_id],
            total=order_total,
            items=items
        ))

    # Sort by date descending
    orders.sort(key=lambda o: o.order_date, reverse=True)

    return orders


def find_matching_order(
    orders: List[AmazonOrder],
    amount: Decimal,
    date: datetime,
    tolerance_days: int = 5
) -> Optional[AmazonOrder]:
    """
    Find an Amazon order matching a YNAB transaction amount and date.

    Args:
        orders: List of Amazon orders to search
        amount: Transaction amount (absolute value)
        date: Transaction date
        tolerance_days: Number of days to allow for date differences

    Returns:
        Matching AmazonOrder or None
    """
    amount = abs(amount)

    for order in orders:
        # Check date within tolerance
        date_diff = abs((order.order_date - date).days)
        if date_diff > tolerance_days:
            continue

        # Check amount matches
        if abs(order.total - amount) < Decimal('0.01'):
            return order

    return None
