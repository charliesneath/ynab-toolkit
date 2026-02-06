"""Claude-based categorization of Amazon items into YNAB categories."""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

import anthropic

from amazon_parser import AmazonItem, AmazonOrder
from config import CLAUDE_MODEL
from ynab_client import YNABCategory
from utils import get_cached_category, cache_category, save_category_cache


@dataclass
class CategoryAssignment:
    """Result of categorizing an item or group of items."""
    category_id: str
    category_name: str
    amount: Decimal
    items: List[str]
    confidence: float
    reasoning: str


@dataclass
class CategorizationResult:
    """Result of categorizing an entire order."""
    order_id: str
    assignments: List[CategoryAssignment]
    total: Decimal


def categorize_order(
    order: AmazonOrder,
    categories: List[YNABCategory],
    client: anthropic.Anthropic,
    model: str = CLAUDE_MODEL
) -> CategorizationResult:
    """Categorize items in an Amazon order using Claude."""

    # Check cache for all items - store full AmazonItem objects
    items_to_categorize = []
    cached_assignments = {}  # category -> list of AmazonItem

    for item in order.items:
        cached_cat = get_cached_category(item.title)
        if cached_cat:
            if cached_cat not in cached_assignments:
                cached_assignments[cached_cat] = []
            cached_assignments[cached_cat].append(item)
        else:
            items_to_categorize.append(item)

    # Build category name->id lookup
    cat_lookup = {cat.name: cat.category_id for cat in categories}
    cat_names = [cat.name for cat in categories]

    new_assignments = {}  # category -> list of AmazonItem

    # Only call API if there are uncached items
    if items_to_categorize:
        items_list = "\n".join([f"- {item.title[:80]}" for item in items_to_categorize])
        categories_str = ", ".join(cat_names)

        prompt = f"""Categorize items into budget categories. Return JSON only.

Items:
{items_list}

Categories: {categories_str}

Return: {{"items": [{{"item": "item name", "category": "category name"}}]}}"""

        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        # Handle empty response - fallback to first category
        if not response.content:
            first_cat = cat_names[0] if cat_names else "Uncategorized"
            for item in items_to_categorize:
                if first_cat not in new_assignments:
                    new_assignments[first_cat] = []
                new_assignments[first_cat].append(item)
        else:
            response_text = response.content[0].text
            if "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            try:
                data = json.loads(response_text.strip())
                # Build a lookup for items being categorized by truncated title
                uncategorized_items = {item.title[:80]: item for item in items_to_categorize}

                for item_data in data.get("items", []):
                    item_name = item_data.get("item", "")
                    cat_name = item_data.get("category", "")

                    # Cache the result (uses persistent cache from utils.py)
                    cache_category(item_name, cat_name)

                    # Find the matching AmazonItem
                    matched_item = uncategorized_items.get(item_name)
                    if not matched_item:
                        # Try to find by prefix match
                        for title, item in uncategorized_items.items():
                            if title.startswith(item_name) or item_name.startswith(title):
                                matched_item = item
                                break

                    if matched_item:
                        if cat_name not in new_assignments:
                            new_assignments[cat_name] = []
                        new_assignments[cat_name].append(matched_item)
                        # Remove from uncategorized to avoid duplicates
                        uncategorized_items = {k: v for k, v in uncategorized_items.items() if v != matched_item}

                # Handle any items that weren't matched in the response
                if uncategorized_items:
                    first_cat = cat_names[0] if cat_names else "Uncategorized"
                    if first_cat not in new_assignments:
                        new_assignments[first_cat] = []
                    new_assignments[first_cat].extend(uncategorized_items.values())

                # Save cache after processing
                save_category_cache()
            except json.JSONDecodeError:
                # Fallback: put all in first category
                first_cat = cat_names[0] if cat_names else "Uncategorized"
                for item in items_to_categorize:
                    if first_cat not in new_assignments:
                        new_assignments[first_cat] = []
                    new_assignments[first_cat].append(item)

    # Merge cached and new assignments into a flat list of (item, category) pairs
    item_categories = []  # list of (AmazonItem, category_name)
    for cat_name, items in cached_assignments.items():
        for item in items:
            item_categories.append((item, cat_name))
    for cat_name, items in new_assignments.items():
        for item in items:
            item_categories.append((item, cat_name))

    # Calculate proportional amounts
    # If any item has 0/missing price, distribute evenly; otherwise use proportions
    sum_item_totals = sum(item.item_total for item, _ in item_categories)
    has_zero_prices = any(item.item_total <= 0 for item, _ in item_categories)
    num_items = len(item_categories)

    # Build result with one assignment per item (not grouped by category)
    assignments = []
    running_total = Decimal("0")
    for i, (item, cat_name) in enumerate(item_categories):
        cat_id = cat_lookup.get(cat_name)
        if not cat_id:
            # Fuzzy match
            for c in categories:
                if cat_name.lower() in c.name.lower() or c.name.lower() in cat_name.lower():
                    cat_id = c.category_id
                    cat_name = c.name
                    break

        # Calculate proportional amount
        if i == num_items - 1:
            # Last item gets remainder to avoid rounding errors
            proportional_amount = order.total - running_total
        elif has_zero_prices or sum_item_totals <= 0:
            # Distribute evenly if any prices are missing
            proportional_amount = (order.total / num_items).quantize(Decimal("0.01"))
            running_total += proportional_amount
        else:
            # Proportional based on item prices
            proportional_amount = (item.item_total * order.total / sum_item_totals).quantize(Decimal("0.01"))
            running_total += proportional_amount

        assignments.append(CategoryAssignment(
            category_id=cat_id or "",
            category_name=cat_name,
            amount=proportional_amount,
            items=[item.title],
            confidence=0.9,
            reasoning="Auto-categorized"
        ))

    return CategorizationResult(
        order_id=order.order_id,
        assignments=assignments,
        total=order.total
    )


def categorize_simple(
    order: AmazonOrder,
    category_id: str,
    category_name: str
) -> CategorizationResult:
    """Simple categorization - put entire order in one category."""
    return CategorizationResult(
        order_id=order.order_id,
        assignments=[
            CategoryAssignment(
                category_id=category_id,
                category_name=category_name,
                amount=order.total,
                items=[item.title for item in order.items],
                confidence=1.0,
                reasoning="Entire order categorized as groceries"
            )
        ],
        total=order.total
    )
