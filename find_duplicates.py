"""Find and remove duplicate transactions."""

import os
import re
from collections import defaultdict
from dotenv import load_dotenv
from ynab_client import YNABClient

load_dotenv()


def extract_order(memo):
    if not memo:
        return None
    match = re.search(r'(11[1-4]-\d{7}-\d{7}|D01-\d{7}-\d{7})', memo)
    return match.group(1) if match else None


def main():
    client = YNABClient(os.getenv('YNAB_TOKEN'))
    budget_id = 'b35a5d8d-39ae-463c-9d76-fdf88182c6f7'
    account_id = '60e777c8-1a41-48af-8a35-b6dbb1807946'

    print("Fetching transactions...")
    transactions = client.get_transactions(budget_id, account_id, since_date='2020-01-01')
    print(f"Total transactions: {len(transactions)}")

    # Group by date+amount
    by_date_amount = defaultdict(list)
    for t in transactions:
        key = (t.date.strftime('%Y-%m-%d'), t.amount)
        by_date_amount[key].append(t)

    print("\nPOTENTIAL DUPLICATES (same date + amount):")
    print("=" * 80)

    duplicates_to_delete = []

    for key, txns in sorted(by_date_amount.items()):
        if len(txns) > 1:
            date, amount = key
            print(f"\n{date} ${abs(amount):.2f} - {len(txns)} transactions:")

            # Check if these are true duplicates (same order number or similar memo)
            orders = [extract_order(t.memo) for t in txns]

            for i, t in enumerate(txns):
                order = orders[i]
                cat = t.category_name or 'Uncategorized'
                approved = "✓" if t.approved else " "
                print(f"  [{approved}] {t.transaction_id[:8]}... | {order or 'No order':<20} | {cat[:15]:<15} | {t.memo[:30] if t.memo else 'No memo'}")

            # If same order number appears multiple times with same amount, likely duplicates
            order_counts = defaultdict(list)
            for i, o in enumerate(orders):
                if o:
                    order_counts[o].append(txns[i])

            for order, order_txns in order_counts.items():
                if len(order_txns) > 1:
                    # Keep the approved one, or the first one
                    approved_txns = [t for t in order_txns if t.approved]
                    if approved_txns:
                        keep = approved_txns[0]
                    else:
                        keep = order_txns[0]

                    for t in order_txns:
                        if t.transaction_id != keep.transaction_id:
                            duplicates_to_delete.append({
                                'txn': t,
                                'reason': f'Duplicate of {order}'
                            })
                            print(f"      ^ DUPLICATE - will delete {t.transaction_id[:8]}")

    print(f"\n\nFound {len(duplicates_to_delete)} duplicates to delete")

    if duplicates_to_delete:
        print("\nDuplicates to remove:")
        for d in duplicates_to_delete:
            t = d['txn']
            print(f"  {t.date.strftime('%Y-%m-%d')} ${abs(t.amount):.2f} - {d['reason']}")

        confirm = input("\nDelete these duplicates? (yes/no): ")
        if confirm.lower() == 'yes':
            for d in duplicates_to_delete:
                t = d['txn']
                print(f"  Deleting {t.transaction_id[:8]}...")
                client.delete_transaction(budget_id, t.transaction_id)
            print("Done!")
        else:
            print("Cancelled.")


if __name__ == '__main__':
    main()
