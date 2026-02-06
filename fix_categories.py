"""Fix categories on uncategorized Amazon transactions by recreating them."""

import os
import json
import re
import time
from dotenv import load_dotenv
import anthropic
from ynab_client import YNABClient

load_dotenv()

QUICK_CATEGORIES = {
    "groceries": "🍌Groceries",
    "grocery": "🍌Groceries",
    "delivery tip": "Delivery Fee",
    "prime membership": "Amazon Prime Annual Membership",
    "prime video": "Movies & Shows",
    "kindle": "📚 Books",
    "audible": "📚 Books",
    "book": "📚 Books",
    "novel": "📚 Books",
    "diaper": "Diapers & Wipes",
    "wipes": "Diapers & Wipes",
    "huggies": "Diapers & Wipes",
    "pampers": "Diapers & Wipes",
    "lego": "🚂 Toys",
    "toy": "🚂 Toys",
    "game": "Games",
    "noggin": "TV Subscriptions",
    "pbs kids": "TV Subscriptions",
    "nuun": "Nuun",
}


def quick_categorize(item_name):
    lower = item_name.lower()
    for keyword, category in QUICK_CATEGORIES.items():
        if keyword in lower:
            return category
    return None


def categorize_with_claude(items, categories, client):
    items_str = "\n".join([f"- {item}" for item in items])
    cat_str = ", ".join(categories[:50])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""Categorize these Amazon purchase items into budget categories. Return JSON only.

Items:
{items_str}

Categories: {cat_str}

Return: {{"items": [{{"item": "item text", "category": "category name"}}]}}"""
        }]
    )

    text = response.content[0].text
    if "```" in text:
        text = text.split("```")[1].split("```")[0]
        if text.startswith("json"):
            text = text[4:]

    return json.loads(text.strip())


def main():
    ynab = YNABClient(os.getenv('YNAB_TOKEN'))
    claude = anthropic.Anthropic()

    budget_id = 'b35a5d8d-39ae-463c-9d76-fdf88182c6f7'
    account_id = '60e777c8-1a41-48af-8a35-b6dbb1807946'

    print("Fetching categories...")
    all_categories = ynab.get_categories(budget_id)

    # Exclude categories from certain groups
    EXCLUDED_GROUPS = ['library renovation']
    categories = [c for c in all_categories
                  if c.group_name.lower() not in EXCLUDED_GROUPS]

    cat_names = [c.name for c in categories]
    cat_lookup = {c.name: c.category_id for c in categories}
    cat_lookup_lower = {c.name.lower(): c.category_id for c in categories}

    print("Fetching transactions...")
    transactions = ynab.get_transactions(budget_id, account_id, since_date='2020-01-01')

    # Find uncategorized Amazon transactions with splits
    to_fix = []
    for t in transactions:
        if not t.subtransactions:
            continue
        if not t.memo or 'Order' not in t.memo:
            continue

        has_uncategorized = False
        for sub in t.subtransactions:
            if sub.get('category_name') == 'Uncategorized' or sub.get('category_id') is None:
                has_uncategorized = True
                break

        if has_uncategorized:
            to_fix.append(t)

    print(f"Found {len(to_fix)} transactions to fix")

    # Collect all items to categorize
    all_items = set()
    for t in to_fix:
        for sub in t.subtransactions:
            memo = sub.get('memo', '')
            if memo:
                all_items.add(memo[:80])

    # Categorize items
    item_categories = {}
    items_for_claude = []

    for item in all_items:
        quick_cat = quick_categorize(item)
        if quick_cat:
            item_categories[item] = quick_cat
        else:
            items_for_claude.append(item)

    print(f"Quick categorized: {len(item_categories)}, Need Claude: {len(items_for_claude)}")

    if items_for_claude:
        batch_size = 20
        for i in range(0, len(items_for_claude), batch_size):
            batch = items_for_claude[i:i+batch_size]
            print(f"Categorizing batch {i//batch_size + 1}...")
            try:
                result = categorize_with_claude(batch, cat_names, claude)
                for item_data in result.get('items', []):
                    item = item_data.get('item', '')
                    cat = item_data.get('category', '')
                    for orig_item in batch:
                        if orig_item.startswith(item[:30]) or item.startswith(orig_item[:30]):
                            item_categories[orig_item] = cat
                            break
            except Exception as e:
                print(f"  Error: {e}")

    print(f"\nRecreating {len(to_fix)} transactions...")
    fixed = 0
    errors = 0

    for t in to_fix:
        # Build new subtransactions with categories
        new_subs = []
        for sub in t.subtransactions:
            memo = sub.get('memo', '')[:80]
            cat_name = item_categories.get(memo)

            if not cat_name and memo.lower() == 'groceries':
                cat_name = '🍌Groceries'

            cat_id = None
            if cat_name:
                cat_id = cat_lookup.get(cat_name) or cat_lookup_lower.get(cat_name.lower())

            new_subs.append({
                'amount': sub.get('amount'),
                'category_id': cat_id,
                'memo': sub.get('memo', '')
            })

        try:
            # Delete old transaction
            ynab.delete_transaction(budget_id, t.transaction_id)
            time.sleep(0.5)

            # Create new one
            new_txn = {
                'account_id': account_id,
                'date': t.date.strftime('%Y-%m-%d'),
                'amount': int(t.amount * 1000),
                'payee_name': 'Amazon.com',
                'memo': t.memo,
                'approved': False,
                'subtransactions': new_subs
            }
            ynab.create_transactions_batch(budget_id, [new_txn])
            print(f"  Fixed {t.date.strftime('%Y-%m-%d')} {t.memo[:40]}")
            fixed += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  Error {t.transaction_id}: {e}")
            errors += 1

    print(f"\nDone! Fixed: {fixed}, Errors: {errors}")


if __name__ == '__main__':
    main()
