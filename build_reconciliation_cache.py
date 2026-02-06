"""Build YNAB transaction cache for reconciliation.

Creates two files:
1. reconciliation_cache_YYYY.json - Summary with monthly totals (token-efficient)
2. reconciliation_txns_YYYY.json - Full transaction details (for drilling down)
"""

import json
import os
import re
from datetime import datetime
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()


def extract_order_number(memo: str) -> str:
    """Extract Amazon order number from memo."""
    if not memo:
        return ""
    # Match order patterns: 112-xxx, 113-xxx, 114-xxx, 111-xxx, D01-xxx
    match = re.search(r'(11[1-4]-\d{7}-\d{7}|D01-\d{7}-\d{7})', memo)
    return match.group(1) if match else ""


def get_statement_period(date: datetime, close_day: int = 4) -> str:
    """Get statement period key (MM/DD/YY format) for a transaction date.

    Args:
        date: Transaction date
        close_day: Day of month when statement closes (default: 4)

    Example with close_day=4:
    - Statement 02/04/23 covers Jan 5 - Feb 4
    - Statement 03/04/23 covers Feb 5 - Mar 4

    So transactions on days 1-close_day belong to THIS month's statement,
    and transactions on days (close_day+1)-31 belong to NEXT month's statement.
    """
    if date.day <= close_day:
        # Falls into this month's statement
        return f"{date.month:02d}/{close_day:02d}/{date.year - 2000:02d}"
    else:
        # Falls into next month's statement
        if date.month == 12:
            return f"01/{close_day:02d}/{date.year + 1 - 2000:02d}"
        else:
            return f"{date.month + 1:02d}/{close_day:02d}/{date.year - 2000:02d}"


def build_cache(year: int, account_name: str = "Chase Amazon", statement_close_day: int = 4):
    """Build a reconciliation cache for the specified year.

    Args:
        year: The year to build cache for
        account_name: Name of the account (for display)
        statement_close_day: Day of month when statement closes (default: 4)
    """

    token = os.getenv("YNAB_TOKEN")
    if not token:
        print("Error: YNAB_TOKEN not found in environment")
        return

    client = YNABClient(token)

    budget_id = "b35a5d8d-39ae-463c-9d76-fdf88182c6f7"
    account_id = "60e777c8-1a41-48af-8a35-b6dbb1807946"

    print(f"Fetching transactions for {year} (statement closes on day {statement_close_day})...")
    since_date = f"{year-1}-12-01"
    transactions = client.get_transactions(budget_id, account_id, since_date=since_date)

    # Build monthly data structure
    monthly_data = {}
    all_transactions = []

    for t in transactions:
        t_year = t.date.year
        t_month = t.date.month

        # Include Dec of prior year or any month of target year
        if not ((t_year == year - 1 and t_month == 12) or (t_year == year)):
            continue

        # Filter for Amazon transactions only (skip card payments/transfers)
        payee = (t.payee_name or "").lower()
        memo = (t.memo or "").lower()
        is_amazon = (
            "amazon" in payee or
            "amzn" in payee or
            "audible" in payee or
            "kindle" in payee or
            "whole foods" in payee or
            "amazon" in memo or
            "amzn" in memo or
            extract_order_number(t.memo)  # Has an order number
        )

        # Skip non-Amazon transactions (card payments, transfers, etc.)
        if not is_amazon:
            continue

        amount = float(t.amount)  # Keep sign: negative=outflow, positive=inflow
        date_str = t.date.strftime('%Y-%m-%d')
        stmt_period = get_statement_period(t.date, statement_close_day)
        order_num = extract_order_number(t.memo)

        # Initialize period if needed
        if stmt_period not in monthly_data:
            monthly_data[stmt_period] = {
                'outflows': 0.0,
                'inflows': 0.0,
                'out_count': 0,
                'in_count': 0,
                'txns': []  # Compact: [date, amount, order_or_memo]
            }

        if amount < 0:
            monthly_data[stmt_period]['outflows'] += abs(amount)
            monthly_data[stmt_period]['out_count'] += 1
        else:
            monthly_data[stmt_period]['inflows'] += amount
            monthly_data[stmt_period]['in_count'] += 1

        # Compact transaction format: [date, amount, identifier]
        identifier = order_num if order_num else (t.memo[:30] if t.memo else "")
        monthly_data[stmt_period]['txns'].append([date_str, amount, identifier])

        # Full transaction for detailed file
        all_transactions.append({
            'd': date_str,
            'a': amount,
            'o': order_num,
            'm': t.memo or '',
            'p': stmt_period,
            'id': t.transaction_id
        })

    # Sort transactions
    all_transactions.sort(key=lambda x: x['d'])
    for period in monthly_data.values():
        period['txns'].sort(key=lambda x: x[0])

    # Summary cache (token-efficient - for quick comparison)
    total_outflows = sum(p['outflows'] for p in monthly_data.values())
    total_inflows = sum(p['inflows'] for p in monthly_data.values())
    summary = {
        'year': year,
        'generated': datetime.now().strftime('%Y-%m-%d'),
        'outflows': round(total_outflows, 2),
        'inflows': round(total_inflows, 2),
        'net': round(total_outflows - total_inflows, 2),
        'count': sum(p['out_count'] + p['in_count'] for p in monthly_data.values()),
        'periods': {
            k: {
                'out': round(v['outflows'], 2),
                'in': round(v['inflows'], 2),
                'net': round(v['outflows'] - v['inflows'], 2),
                'n': v['out_count'] + v['in_count']
            }
            for k, v in sorted(monthly_data.items())
        }
    }

    # Detailed cache (for drilling into specific periods)
    detailed = {
        'year': year,
        'generated': datetime.now().strftime('%Y-%m-%d'),
        'periods': {
            k: {
                'outflows': round(v['outflows'], 2),
                'inflows': round(v['inflows'], 2),
                'txns': v['txns']  # [[date, amount, order/memo], ...]
            }
            for k, v in sorted(monthly_data.items())
        }
    }

    # Save files
    summary_file = f"data/reconciliation_cache_{year}.json"
    detail_file = f"data/reconciliation_txns_{year}.json"

    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)

    with open(detail_file, 'w') as f:
        json.dump(detailed, f, separators=(',', ':'))  # Compact JSON

    print(f"\nSummary saved to {summary_file}")
    print(f"Details saved to {detail_file}")
    print(f"\nTotals: Outflows ${summary['outflows']:,.2f} | Inflows ${summary['inflows']:,.2f} | Net ${summary['net']:,.2f} ({summary['count']} txns)")
    print("\nBy statement period:")
    for k, v in sorted(summary['periods'].items()):
        inflow_str = f" - ${v['in']:.2f} refunds" if v['in'] > 0 else ""
        print(f"  {k}: ${v['out']:,.2f} purchases{inflow_str} = ${v['net']:,.2f} net ({v['n']} txns)")

    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Build YNAB transaction cache for reconciliation')
    parser.add_argument('year', type=int, nargs='?', default=2024, help='Year to build cache for')
    parser.add_argument('--close-day', type=int, default=4,
                        help='Day of month when statement closes (default: 4)')
    args = parser.parse_args()
    build_cache(args.year, statement_close_day=args.close_day)
