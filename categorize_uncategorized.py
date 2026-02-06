"""Categorize uncategorized Amazon transactions using Claude."""

import os
import json
import re
from dotenv import load_dotenv
import anthropic
from ynab_client import YNABClient

load_dotenv()

# Common category mappings for speed
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
}


def quick_categorize(item_name):
    """Try to categorize based on keywords."""
    lower = item_name.lower()
    for keyword, category in QUICK_CATEGORIES.items():
        if keyword in lower:
            return category
    return None


def categorize_with_claude(items, categories, client):
    """Use Claude to categorize items."""
    items_str = "\n".join([f"- {item}" for item in items])
    cat_str = ", ".join(categories[:50])  # Limit categories for prompt

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""Categorize these Amazon purchase items into budget categories. Return JSON only.

Items:
{items_str}

Categories: {cat_str}

Return format: {{"items": [{{"item": "item text", "category": "category name"}}]}}

Be concise. Match items to the most appropriate category."""
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
    to_categorize = []
    for t in transactions:
        if not t.subtransactions:
            continue

        # Check if any subtransaction is uncategorized
        has_uncategorized = False
        for sub in t.subtransactions:
            if sub.get('category_name') == 'Uncategorized' or sub.get('category_id') is None:
                has_uncategorized = True
                break

        if has_uncategorized and t.memo and 'Order' in t.memo:
            to_categorize.append(t)

    print(f"Found {len(to_categorize)} transactions to categorize")

    # Collect all unique items to categorize
    all_items = set()
    for t in to_categorize:
        for sub in t.subtransactions:
            memo = sub.get('memo', '')
            if memo and memo != 'Groceries':
                all_items.add(memo[:80])

    print(f"Found {len(all_items)} unique items")

    # Quick categorize what we can
    item_categories = {}
    items_for_claude = []

    for item in all_items:
        quick_cat = quick_categorize(item)
        if quick_cat:
            item_categories[item] = quick_cat
        else:
            items_for_claude.append(item)

    print(f"Quick categorized: {len(item_categories)}")
    print(f"Need Claude: {len(items_for_claude)}")

    # Categorize remaining with Claude in batches
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
                    # Find matching item in batch
                    for orig_item in batch:
                        if orig_item.startswith(item) or item.startswith(orig_item[:30]):
                            item_categories[orig_item] = cat
                            break
            except Exception as e:
                print(f"  Error: {e}")

    print(f"\nTotal categorized: {len(item_categories)}")

    # Update transactions
    print("\nUpdating transactions...")
    updated = 0

    for t in to_categorize:
        new_subs = []
        changed = False

        for sub in t.subtransactions:
            memo = sub.get('memo', '')[:80]
            current_cat = sub.get('category_name')

            if current_cat == 'Uncategorized' or sub.get('category_id') is None:
                # Find category for this item
                new_cat = item_categories.get(memo)
                if not new_cat and memo == 'Groceries':
                    new_cat = '🍌Groceries'

                if new_cat:
                    cat_id = cat_lookup.get(new_cat) or cat_lookup_lower.get(new_cat.lower())
                    if cat_id:
                        new_subs.append({
                            'amount': sub.get('amount'),
                            'category_id': cat_id,
                            'memo': sub.get('memo', '')
                        })
                        changed = True
                        continue

            # Keep as-is
            new_subs.append({
                'amount': sub.get('amount'),
                'category_id': sub.get('category_id'),
                'memo': sub.get('memo', '')
            })

        if changed:
            try:
                ynab.update_transaction(budget_id, t.transaction_id, subtransactions=new_subs)
                print(f"  Updated {t.date.strftime('%Y-%m-%d')} {t.memo[:40]}")
                updated += 1
            except Exception as e:
                print(f"  Error updating {t.transaction_id}: {e}")

    print(f"\nDone! Updated {updated} transactions")


if __name__ == '__main__':
    main()
