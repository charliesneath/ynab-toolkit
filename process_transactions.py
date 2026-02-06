"""
Process Amazon transactions and cache results locally.

SHIPMENT MATCHING & PROPORTIONAL ALLOCATION
============================================

Problem:
    Amazon bank charges often don't match item totals exactly because:
    1. Orders ship in multiple shipments (one order = multiple charges)
    2. Gift cards and rewards points reduce the charged amount
    3. Tax is included in charges but may not match item-level tax exactly

    Example: An order with $280 of items might show as a $145 charge because
    $100 gift card + $35 rewards were applied.

Solution - Date-Based Shipment Matching:
    1. Group items by Ship Date from Amazon order history
       - Items with the same Ship Date are in the same shipment
       - Each shipment has a total (sum of item Total Owed including tax)

    2. Match bank charges to shipments by date proximity
       - Bank charge date is typically 0-3 days after ship date
       - Find the shipment whose ship date is closest to (and before) charge date

    3. Apply proportional allocation when charge ≠ shipment total
       - ratio = bank_charge / shipment_total
       - Each item's allocated amount = item_total_owed × ratio
       - This distributes gift card/rewards discounts proportionally

    Example:
        Shipment total: $200 (Item A: $120, Item B: $80)
        Bank charge: $140 (due to $60 gift card)
        Ratio: 140/200 = 0.70
        Item A allocated: $120 × 0.70 = $84
        Item B allocated: $80 × 0.70 = $56
        Sum: $140 ✓

Data Sources:
    - Amazon Order History CSV: Contains Ship Date, Total Owed per item
    - Bank Statement (YNAB export): Contains charge date and amount
    - No reliable source for exact gift card amounts, hence proportional allocation

This approach ensures:
    - Items are correctly categorized (each item goes to its own budget category)
    - Amounts sum to actual bank charges (for accurate YNAB tracking)
    - Gift cards/rewards are distributed fairly across items

GROCERY ORDER HANDLING
======================

Grocery orders (Whole Foods, Amazon Fresh) are handled differently:
    - Detected via Shipping Option field: "scheduled-houdini" or "scheduled-one-houdini"
    - Categorized as single "Groceries" category (no per-item splits)
    - Item details stored in "grocery_items" field for separate analysis
    - Not sent through AI categorization (reduces API costs)

This keeps YNAB transactions clean while preserving item data for analysis.
"""

import argparse
import csv
import json
import os
import time
from datetime import datetime
import decimal
from decimal import Decimal
from collections import defaultdict
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from config import CLAUDE_MODEL
from utils import (
    get_cache_dir,
    log,
    extract_order_id,
    is_amazon_transaction,
    is_grocery_transaction,
    load_category_cache,
    get_cached_category,
    cache_category,
    save_category_cache,
)
from ynab_client import YNABClient

load_dotenv()

# Shipping options that indicate grocery/Amazon Fresh/Whole Foods orders
GROCERY_SHIPPING_OPTIONS = {"scheduled-houdini", "scheduled-one-houdini"}


# =============================================================================
# GENERIC PROMPT TEMPLATE (committed to repo)
# This is the well-tuned prompt structure for Amazon product categorization.
# Personal category data is loaded from category_rules.json (not committed).
# =============================================================================
CATEGORIZATION_PROMPT_TEMPLATE = """
You are categorizing Amazon purchases into budget categories.

TASK:
- Read the product name carefully
- Choose the single BEST category from the list below
- Return ONLY the exact category name, nothing else

CRITICAL RULES:
1. NEVER return the product name or description - only a category name
2. Choose the MOST SPECIFIC category available (e.g., "Berries" not "Fruit" for strawberries)
3. The fallback category "{fallback_category}" should be used ONLY when nothing else fits
4. When in doubt between two categories, prefer the more specific one
5. Brand names often indicate category (see brand hints below)
6. PRODUCE RULE: Fresh fruits and vegetables should ALWAYS use specific categories (Fruit, Vegetables, Berries, Bananas, Apples) - NEVER use generic grocery categories for produce

CATEGORY-SPECIFIC GUIDANCE:
{category_rules}

FALLBACK CATEGORY - "{fallback_category}":
Use "{fallback_category}" when:
- You're not confident which category fits best
- The item could reasonably go in 2+ categories
- The product name is ambiguous or unclear
- You don't recognize the product type

Do NOT guess. When uncertain, use "{fallback_category}".

IMPORTANT: Return ONLY the exact category name from the valid categories list. Do not return product names or descriptions.
""".strip()


# =============================================================================
# PERSONAL CATEGORY RULES (loaded from category_rules.json, NOT committed)
# =============================================================================
CATEGORY_RULES_FILE = Path(__file__).parent / "category_rules.json"
CATEGORY_RULES_EXAMPLE = Path(__file__).parent / "category_rules.example.json"

# Cache for loaded rules
_category_rules_cache = None


def load_category_rules() -> dict:
    """Load customer-specific category rules from JSON file."""
    global _category_rules_cache
    if _category_rules_cache is not None:
        return _category_rules_cache

    rules_file = CATEGORY_RULES_FILE
    if not rules_file.exists():
        rules_file = CATEGORY_RULES_EXAMPLE
        log(f"Warning: {CATEGORY_RULES_FILE} not found, using example file")

    with open(rules_file, "r") as f:
        _category_rules_cache = json.load(f)
    return _category_rules_cache


def get_fallback_category() -> str:
    """Get the fallback category from rules."""
    rules = load_category_rules()
    return rules.get("fallback_category", "Uncategorized")


def get_excluded_groups() -> set[str]:
    """Get category groups to exclude from prompts."""
    rules = load_category_rules()
    return set(rules.get("excluded_groups", []))


def format_category_rules() -> str:
    """
    Format the personal category rules from JSON into prompt text.

    This generates ONLY the category-specific data (examples, brands, exclusions).
    The generic prompt template is defined separately above.
    """
    rules = load_category_rules()
    categories = rules.get("categories", {})
    fallback = rules.get("fallback_category", "Uncategorized")

    lines = []

    for cat_name, cat_data in categories.items():
        if cat_name == fallback:
            continue  # Fallback handled in generic template

        description = cat_data.get("description", "")
        examples = cat_data.get("examples", [])
        brands = cat_data.get("brands", [])
        not_this = cat_data.get("not_this", {})
        notes = cat_data.get("notes", "")

        # Category header
        lines.append(f"{cat_name}:")

        # Description
        if description:
            lines.append(f"  {description}")

        # Examples (limit to keep prompt manageable)
        if examples:
            examples_str = ", ".join(examples[:12])
            if len(examples) > 12:
                examples_str += "..."
            lines.append(f"  Examples: {examples_str}")

        # Brands
        if brands:
            lines.append(f"  Brands: {', '.join(brands)}")

        # Exclusions (what should NOT go here)
        if not_this:
            exclusions = [f"{item}→{cat}" for item, cat in not_this.items()]
            lines.append(f"  NOT here: {', '.join(exclusions)}")

        # Notes
        if notes:
            lines.append(f"  Note: {notes}")

        lines.append("")

    return "\n".join(lines)


def generate_categorization_rules() -> str:
    """
    Assemble the complete categorization prompt.

    Combines:
    - Generic prompt template (committed, well-tuned for this project)
    - Personal category rules (from JSON, not committed)
    """
    fallback = get_fallback_category()
    category_rules = format_category_rules()

    return CATEGORIZATION_PROMPT_TEMPLATE.format(
        fallback_category=fallback,
        category_rules=category_rules
    )


def generate_suspicious_rules() -> dict[str, list[str]]:
    """
    Generate suspicious categorization rules from the JSON config.

    These are items that should NEVER appear in certain categories,
    derived from the 'not_this' mappings in the rules.
    """
    rules = load_category_rules()
    categories = rules.get("categories", {})
    suspicious = {}

    for cat_name, cat_data in categories.items():
        not_this = cat_data.get("not_this", {})
        if not_this:
            # Items that should NOT be in this category
            keywords = list(not_this.keys())
            if keywords:
                suspicious[cat_name] = keywords

    return suspicious


# Generate rules at module load time
CATEGORIZATION_RULES = generate_categorization_rules()
SUSPICIOUS_RULES = generate_suspicious_rules()

import re

def strip_leading_emoji(text: str) -> str:
    """Strip leading emoji and whitespace from a string."""
    # Match emoji at start (common emoji ranges) followed by optional whitespace
    return re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF]+\s*', '', text)


def match_category(cat: str, ynab_categories: list[str]) -> tuple[str, bool]:
    """
    Match a category name to a YNAB category with fuzzy emoji matching.
    Returns (matched_category, was_matched).
    """
    # Exact match
    if cat in ynab_categories:
        return cat, True

    # Case-insensitive match
    cat_lower = cat.lower()
    for ynab_cat in ynab_categories:
        if ynab_cat.lower() == cat_lower:
            return ynab_cat, True

    # Emoji-stripped match (Claude might return "Gear" instead of "🎒 Gear")
    cat_stripped = strip_leading_emoji(cat).lower()
    for ynab_cat in ynab_categories:
        stripped = strip_leading_emoji(ynab_cat)
        if stripped.lower() == cat_lower or stripped.lower() == cat_stripped:
            return ynab_cat, True

    # Fuzzy match: if first word matches and they share key words
    # Handles cases like "Pasta & Rices" → "Pasta & Grains"
    cat_words = set(re.split(r'\W+', cat_lower))
    for ynab_cat in ynab_categories:
        ynab_stripped = strip_leading_emoji(ynab_cat).lower()
        ynab_words = set(re.split(r'\W+', ynab_stripped))
        # If first word matches and at least half the words overlap
        cat_first = cat_lower.split()[0] if cat_lower.split() else ""
        ynab_first = ynab_stripped.split()[0] if ynab_stripped.split() else ""
        if cat_first and cat_first == ynab_first:
            overlap = len(cat_words & ynab_words)
            if overlap >= len(cat_words) / 2:
                return ynab_cat, True

    # No match found
    return cat, False


def retry_categorize_item(item: str, ynab_categories: list[str], client, cat_to_group: dict[str, str] | None = None) -> str | None:
    """Retry categorization for a single item when initial category didn't match."""
    # Use filtered categories with descriptions (same as main prompt)
    if cat_to_group:
        categories_list = format_categories_for_prompt(ynab_categories, cat_to_group)
    else:
        categories_list = "\n".join(sorted(ynab_categories))

    prompt = f"""Categorize this Amazon product into a budget category.

Product: {item}

{CATEGORIZATION_RULES}
IMPORTANT: Return ONLY the category name from the list below. Do not return the product name.

Valid categories:
{categories_list}

Category:"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        if response.content:
            cat = response.content[0].text.strip()
            # Clean up - strip descriptions/explanations
            if "(" in cat:
                cat = cat.split("(")[0].strip()
            matched_cat, was_matched = match_category(cat, ynab_categories)
            if was_matched:
                return matched_cat
    except Exception:
        pass
    return None


# =============================================================================
# SUSPICIOUS CATEGORIZATION RULES
# Items matching these patterns should NEVER be in these categories
# If detected, the item will be resubmitted for recategorization
# =============================================================================
SUSPICIOUS_RULES = {
    # Minimal rules - only catch the most egregious cross-category errors
    # Most categorization should be handled by prompt guidance
    "Meats": ["banana", "tofu", "avocado"],
    "Bananas": ["chicken", "beef", "bacon"],
    "Frozen": ["broccoli", "spinach", "peas", "mango", "blueberries"],  # Use actual category
    "🎒 Gear": ["diaper", "wipes"],  # → Diapers & Wipes
    "Household Supplies": ["diaper", "wipes"],  # → Diapers & Wipes
}


def is_suspicious_categorization(item: str, category: str) -> bool:
    """Check if an item's categorization seems wrong based on suspicious rules."""
    item_lower = item.lower()

    # Strip emoji from category for matching
    cat_stripped = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF]+\s*', '', category)

    # Check both original and stripped category
    for cat_key in [category, cat_stripped]:
        if cat_key in SUSPICIOUS_RULES:
            for keyword in SUSPICIOUS_RULES[cat_key]:
                if keyword in item_lower:
                    return True
    return False


def log_miscategorization(item: str, original_category: str, new_category: str, cache_dir: Path | None = None):
    """Log miscategorizations for pattern analysis."""
    if cache_dir is None:
        cache_dir = Path("data/processed/chase-amazon")

    log_file = cache_dir / "miscategorization_log.json"

    # Load existing log
    if log_file.exists():
        with open(log_file, "r") as f:
            log_data = json.load(f)
    else:
        log_data = {"runs": [], "items": []}

    # Add this miscategorization
    entry = {
        "timestamp": datetime.now().isoformat(),
        "item": item[:100],  # Truncate long names
        "original_category": original_category,
        "corrected_category": new_category,
    }
    log_data["items"].append(entry)

    # Save
    with open(log_file, "w") as f:
        json.dump(log_data, f, indent=2)


def resubmit_suspicious_item(item: str, original_category: str, ynab_categories: list[str], client) -> str:
    """Resubmit a suspicious item for recategorization with focused attention."""
    categories_list = "\n".join(sorted(ynab_categories))

    prompt = f"""This grocery item was categorized as "{original_category}" but that seems incorrect.

Item: {item}

Please recategorize this item. Choose the BEST category from this list.
Return ONLY the exact category name, nothing else.

{CATEGORIZATION_RULES}

Valid categories:
{categories_list}"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,  # Use Haiku for cost efficiency
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        if response.content:
            cat = response.content[0].text.strip()
            matched_cat, was_matched = match_category(cat, ynab_categories)
            if was_matched:
                log(f"  Resubmit fix: '{item[:50]}' from '{original_category}' → '{matched_cat}'")
                # Log the miscategorization for pattern analysis
                log_miscategorization(item, original_category, matched_cat)
                return matched_cat
    except Exception as e:
        log(f"  Resubmit error for '{item[:30]}': {e}")

    return original_category  # Keep original if resubmit fails


def get_ynab_categories() -> tuple[list[str], dict[str, str]]:
    """
    Fetch categories from YNAB budget.

    Returns:
        Tuple of (category_names_list, category_to_group_mapping)
    """
    ynab_token = os.getenv("YNAB_TOKEN")
    budget_name = os.getenv("BUDGET_NAME")

    if not ynab_token or not budget_name:
        log("Warning: YNAB_TOKEN or BUDGET_NAME not set - using fallback categories")
        return [], {}

    try:
        ynab = YNABClient(ynab_token)
        budget_id = ynab.get_budget_id(budget_name)
        if not budget_id:
            log(f"Warning: Budget '{budget_name}' not found")
            return [], {}

        all_categories = ynab.get_categories(budget_id)

        # Filter out excluded category groups
        excluded_groups = ['library renovation']
        categories = [c for c in all_categories
                      if c.group_name.lower() not in excluded_groups]

        # Build category list and mapping (dedupe by name)
        cat_names = []
        cat_to_group = {}
        seen = set()
        for cat in categories:
            if cat.name not in seen:
                cat_names.append(cat.name)
                seen.add(cat.name)
            cat_to_group[cat.name] = cat.group_name

        log(f"Loaded {len(cat_names)} categories from YNAB (excluded {len(all_categories) - len(categories)} from restricted groups)")
        return cat_names, cat_to_group

    except Exception as e:
        log(f"Warning: Could not fetch YNAB categories: {e}")
        return [], {}


def load_category_descriptions() -> tuple[dict[str, str], set[str]]:
    """Load category descriptions and excluded categories from CSV file.

    Returns:
        Tuple of (descriptions dict, excluded categories set)
    """
    descriptions = {}
    excluded = set()
    desc_file = Path("data/category_descriptions.csv")
    if desc_file.exists():
        with open(desc_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cat = row.get("category", "")
                desc = (row.get("description") or "").strip()
                exclude = (row.get("exclude") or "").strip().lower()
                if cat:
                    if desc:
                        descriptions[cat] = desc
                    if exclude == "yes":
                        excluded.add(cat)
    return descriptions, excluded


def format_categories_for_prompt(cat_names: list[str], cat_to_group: dict[str, str]) -> str:
    """Format categories with descriptions and group context.

    Excludes categories marked as 'exclude=yes' in category_descriptions.csv.
    Also excludes entire category groups that aren't relevant to Amazon purchases
    (loaded from category_rules.json).
    """
    # Load excluded groups from rules file
    excluded_groups = get_excluded_groups()

    descriptions, excluded = load_category_descriptions()
    lines = []
    excluded_count = 0
    for cat in sorted(cat_names):
        group = cat_to_group.get(cat, "")

        # Skip excluded categories (services, subscriptions, bills, etc.)
        if cat in excluded:
            excluded_count += 1
            continue

        # Skip categories in excluded groups
        if group in excluded_groups:
            excluded_count += 1
            continue
        desc = descriptions.get(cat, "")

        if desc:
            # Has description - use parentheses to avoid model copying format
            lines.append(f"{cat} ({desc})")
        elif group:
            # No description - fall back to group context
            lines.append(f"{cat} ({group} group)")
        else:
            lines.append(cat)

    if excluded_count > 0:
        log(f"  (Excluded {excluded_count} non-purchasable categories from prompt)")

    return "\n".join(lines)


def load_order_history(history_dirs: list[str]) -> dict:
    """Load Amazon order history CSVs into a lookup by order ID.

    This extracts key fields for shipment matching:
    - Order ID: Links bank charges to order history
    - Ship Date: Used for date-based shipment matching (items with same ship date = same shipment)
    - Total Owed: Price + tax per item, used for proportional allocation
    - Quantity: For multi-quantity items

    Items are grouped by Ship Date to form shipments. Each shipment contains:
    - ship_date: When items shipped
    - total: Sum of Total Owed for all items in shipment
    - items: List of {name, total, qty} for each item

    Args:
        history_dirs: List of paths to directories containing Amazon order history CSVs

    Returns:
        Dict mapping order_id to:
            - shipments: List of shipments (grouped by Ship Date)
            - items: Flat list of all items in order
    """
    # Handle single string for backwards compatibility
    if isinstance(history_dirs, str):
        history_dirs = [history_dirs]

    valid_dirs = []
    for history_dir in history_dirs:
        if os.path.exists(history_dir):
            valid_dirs.append(history_dir)
        else:
            log(f"Warning: Order history directory not found: {history_dir}")

    if not valid_dirs:
        log("  Download from: Amazon > Account > Download Your Data > Your Orders")
        return {}

    all_items = []

    for history_dir in valid_dirs:
        for root, _, files in os.walk(history_dir):
            for f in files:
                if "OrderHistory" in f and f.endswith(".csv"):
                    filepath = os.path.join(root, f)
                    log(f"Loading {filepath}...")

                    with open(filepath, "r", encoding="utf-8-sig") as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            order_id = row.get("Order ID", "")
                            if not order_id:
                                continue

                            product_name = row.get("Product Name", "Unknown Item")
                            total_owed = row.get("Total Owed", "0")
                            tracking = row.get("Carrier Name & Tracking Number", "")

                            try:
                                total = Decimal(total_owed.replace("'", "").replace("$", "").replace(",", "")) if total_owed else Decimal("0")
                            except (ValueError, decimal.InvalidOperation):
                                total = Decimal("0")

                            # Get shipment date
                            ship_date_str = row.get("Ship Date", "")
                            ship_date = None
                            if ship_date_str:
                                try:
                                    # Parse ISO format: 2025-01-04T14:02:10Z
                                    ship_date = datetime.fromisoformat(ship_date_str.replace("Z", "+00:00")).date()
                                except ValueError:
                                    pass

                            # Get quantity
                            qty_str = row.get("Quantity", "1")
                            try:
                                qty = int(qty_str) if qty_str else 1
                            except ValueError:
                                qty = 1

                            # Get shipping option to detect grocery orders
                            shipping_option = row.get("Shipping Option", "")

                            all_items.append({
                                "order_id": order_id,
                                "name": product_name,
                                "total": total,
                                "tracking": tracking,
                                "ship_date": ship_date,
                                "quantity": qty,
                                "shipping_option": shipping_option,
                            })

    orders = {}
    order_items = defaultdict(list)
    for item in all_items:
        order_items[item["order_id"]].append(item)

    for order_id, items in order_items.items():
        # Group by ship_date for shipment matching
        shipment_groups = defaultdict(list)
        for item in items:
            # Use ship_date as key (None for items without ship date)
            ship_key = item["ship_date"].isoformat() if item["ship_date"] else "unknown"
            shipment_groups[ship_key].append(item)

        shipments = []
        for ship_key, group_items in shipment_groups.items():
            shipment_total = sum(item["total"] for item in group_items)
            ship_date = group_items[0]["ship_date"] if group_items else None
            # A shipment is grocery if all items have a grocery shipping option
            is_grocery = all(
                item.get("shipping_option", "") in GROCERY_SHIPPING_OPTIONS
                for item in group_items
            )
            shipments.append({
                "ship_date": ship_date,
                "total": shipment_total,
                "items": [{"name": item["name"], "total": item["total"], "qty": item["quantity"]} for item in group_items],
                "is_grocery": is_grocery,
            })

        # Sort shipments by date
        shipments.sort(key=lambda s: s["ship_date"] or datetime.max.date())

        # Order is grocery if all shipments are grocery
        order_is_grocery = all(s["is_grocery"] for s in shipments) if shipments else False

        orders[order_id] = {
            "shipments": shipments,
            "items": [{"name": item["name"], "total": item["total"]} for item in items],
            "is_grocery": order_is_grocery,
        }

    log(f"Loaded {len(orders)} unique orders")
    return orders




def distribute_amounts(total: Decimal, num_splits: int) -> list:
    if num_splits == 0:
        return []
    if num_splits == 1:
        return [total]
    base_amount = (total / num_splits).quantize(Decimal("0.01"))
    amounts = [base_amount] * (num_splits - 1)
    amounts.append(total - sum(amounts))
    return amounts


def batch_categorize_items(all_items: dict, client, ynab_categories: list[str], cat_to_group: dict[str, str]) -> dict:
    """
    Batch categorize items in chunks of 20 for reliability.
    Uses cache to avoid re-categorizing known items.

    Args:
        all_items: dict of {import_id: {"items": [...], "is_grocery": bool}}
        client: Anthropic client
        ynab_categories: List of valid YNAB category names
        cat_to_group: Mapping of category name to group name

    Returns:
        dict of {import_id: {category: [items]}}
    """
    if not all_items:
        return {}

    results = {}
    unmatched_categories = set()  # Track categories returned that don't match YNAB

    # First pass: check cache for all items
    items_needing_categorization = {}  # import_id -> list of (idx, item)
    cached_count = 0

    for import_id, data in all_items.items():
        results[import_id] = defaultdict(list)
        uncached_items = []

        for item in data["items"]:  # Process all items
            cached_cat = get_cached_category(item)
            if cached_cat:
                results[import_id][cached_cat].append(item)
                cached_count += 1
            else:
                uncached_items.append(item)

        if uncached_items:
            items_needing_categorization[import_id] = uncached_items

    if cached_count > 0:
        log(f"  {cached_count} items found in cache")

    if not items_needing_categorization:
        # All items were cached
        for import_id in results:
            results[import_id] = dict(results[import_id])
        return results

    # Build category prompt
    categories_prompt = format_categories_for_prompt(ynab_categories, cat_to_group)


    # Flatten all items for per-item categorization
    all_item_list = []  # [(import_id, item_name), ...]
    for import_id, data in all_items.items():
        for item in data["items"]:
            # Check cache first
            cached = get_cached_category(item)
            if cached:
                results[import_id][cached].append(item)
            else:
                all_item_list.append((import_id, item))

    if not all_item_list:
        return results

    # Process items in chunks
    item_chunk_size = 30  # items per API call

    for chunk_start in range(0, len(all_item_list), item_chunk_size):
        chunk = all_item_list[chunk_start:chunk_start + item_chunk_size]

        # Build item list for prompt - each item gets its own category
        item_descriptions = []
        item_refs = []  # [(import_id, item_name), ...]

        for import_id, item_name in chunk:
            item_descriptions.append(item_name[:80])
            item_refs.append((import_id, item_name))

        if not item_descriptions:
            continue

        items_numbered = "\n".join([f"{i+1}. {desc}" for i, desc in enumerate(item_descriptions)])

        prompt = f"""Categorize each Amazon product into a budget category.

Products:
{items_numbered}
{CATEGORIZATION_RULES}
FORMAT RULES:
1. Return ONLY the category name (text BEFORE the parentheses)
2. DO NOT include descriptions or explanations - just the category name
3. Copy the category name exactly, including any emoji
4. One category per line, numbered to match products

Example correct responses:
1. Snacks
2. Dairy
3. 🍌Groceries

Example WRONG responses (never do this):
1. Snacks - chips and crackers
2. Dairy (cheese products)

Valid categories (return ONLY the category name, not the description in parentheses):
{categories_prompt}

Reply:"""

        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            # Handle empty response
            if not response.content:
                log(f"  Warning: Empty API response for chunk")
                continue

            response_text = response.content[0].text

            # Parse numbered response - one category per item
            for line in response_text.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(".", 1)
                if len(parts) == 2:
                    try:
                        idx = int(parts[0].strip()) - 1
                        cat = parts[1].strip()

                        # Clean up category - strip descriptions/explanations after parentheses
                        if "(" in cat:
                            cat = cat.split("(")[0].strip()
                        # Strip common explanation markers
                        for marker in [" - ", " since ", " because "]:
                            if marker in cat.lower():
                                cat = cat.split(marker)[0].strip()

                        # Detect if response looks like a product name instead of a category
                        # Product names are typically long, contain commas/sizes, or match the input
                        looks_like_product = (
                            len(cat) > 40 or  # Categories are short
                            "," in cat or  # Products have commas
                            "ounce" in cat.lower() or "oz" in cat.lower() or  # Size indicators
                            "pack" in cat.lower() or "count" in cat.lower() or
                            cat.lower().startswith("organic ") or  # Product descriptors
                            "365 " in cat or "by whole foods" in cat.lower()  # Brand names
                        )
                        if looks_like_product:
                            matched = False  # Force retry
                            cat = cat  # Keep for error logging
                        else:
                            # Match category with fuzzy emoji support
                            cat, matched = match_category(cat, ynab_categories)

                        if 0 <= idx < len(item_refs):
                            import_id, item_name = item_refs[idx]

                            # Retry if category didn't match
                            if not matched:
                                retry_cat = retry_categorize_item(item_name, ynab_categories, client, cat_to_group)
                                if retry_cat:
                                    log(f"  Retry: '{cat}' -> '{retry_cat}'")
                                    cat = retry_cat
                                else:
                                    unmatched_categories.add(cat)

                            # Check for suspicious categorization and resubmit if needed
                            if is_suspicious_categorization(item_name, cat):
                                new_cat = resubmit_suspicious_item(item_name, cat, ynab_categories, client)
                                if new_cat != cat:
                                    cat = new_cat

                            # Store category for this item
                            results[import_id][cat].append(item_name)
                            # Cache item with this category
                            cache_category(item_name, cat)
                    except ValueError:
                        pass

        except Exception as e:
            log(f"  Chunk error: {e}")

    # Save cache after batch processing
    save_category_cache()

    # Report unmatched categories
    if unmatched_categories:
        log(f"\n  WARNING: {len(unmatched_categories)} categories returned don't match YNAB:")
        for cat in sorted(unmatched_categories):
            log(f"    - '{cat}'")

    # Ensure all transactions have results
    for import_id, data in all_items.items():
        if not results.get(import_id):
            results[import_id] = {}
        else:
            results[import_id] = dict(results[import_id])

    return results


# =============================================================================
# Async Batch API Functions (50% cheaper, up to 24 hour processing)
# =============================================================================

def get_batch_file(cache_dir: Path) -> Path:
    """Get the batch tracking file path."""
    return cache_dir / "pending_batches.json"


def load_pending_batches(cache_dir: Path) -> dict:
    """Load pending batch jobs."""
    batch_file = get_batch_file(cache_dir)
    if batch_file.exists():
        try:
            with open(batch_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"batches": []}


def save_pending_batches(cache_dir: Path, data: dict):
    """Save pending batch jobs."""
    batch_file = get_batch_file(cache_dir)
    with open(batch_file, "w") as f:
        json.dump(data, f, indent=2)


def import_id_to_custom_id(import_id: str) -> str:
    """Convert import_id to valid batch API custom_id (replace colons with underscores)."""
    return import_id.replace(":", "_")


def custom_id_to_import_id(custom_id: str) -> str:
    """Convert batch API custom_id back to import_id (replace underscores with colons).

    Note: Only converts the structural underscores (AMZ2_order_amount_direction).
    The order ID itself may contain hyphens which are preserved.
    """
    # Pattern: AMZ2_XXX-XXXXXXX-XXXXXXX_AMOUNT_DIRECTION
    # We need to convert: AMZ2_ -> AMZ2:, _AMOUNT_ -> :AMOUNT:, _DIRECTION -> :DIRECTION
    parts = custom_id.split("_")
    if len(parts) >= 4 and parts[0] == "AMZ2":
        # Reconstruct: AMZ2:order_id:amount:direction
        # Order ID is parts[1] (may contain hyphens, that's fine)
        # Amount is parts[2]
        # Direction is parts[3]
        return f"AMZ2:{parts[1]}:{parts[2]}:{parts[3]}"
    # Fallback: simple replacement (may not work for all cases)
    return custom_id.replace("_", ":")


def submit_batch_categorization(all_items: dict, client, cache_dir: Path, cache_file: Path,
                                 ynab_categories: list[str], cat_to_group: dict[str, str]) -> str:
    """
    Submit items for categorization using the Batches API (50% cheaper).

    Args:
        all_items: dict of {import_id: {"items": [...], "is_grocery": bool}}
        client: Anthropic client
        cache_dir: Directory for batch tracking
        cache_file: The cache file these results will be applied to
        ynab_categories: List of valid YNAB category names
        cat_to_group: Mapping of category name to group name

    Returns:
        Batch ID for tracking
    """
    if not all_items:
        log("No items to categorize")
        return ""

    if not ynab_categories:
        log("Error: No YNAB categories available. Check YNAB_TOKEN and BUDGET_NAME.")
        return ""

    # Check cache first
    items_needing_categorization = {}
    cached_count = 0

    for import_id, data in all_items.items():
        uncached_items = []
        for item in data["items"][:5]:
            cached_cat = get_cached_category(item)
            if cached_cat:
                cached_count += 1
            else:
                uncached_items.append(item)
        if uncached_items:
            items_needing_categorization[import_id] = uncached_items

    if cached_count > 0:
        log(f"  {cached_count} items already in cache (will be applied when results retrieved)")

    if not items_needing_categorization:
        log("All items already cached - no batch submission needed")
        return ""

    # Build category prompt with groups
    categories_prompt = format_categories_for_prompt(ynab_categories, cat_to_group)


    # Build batch requests - one request per transaction, categorize each item
    requests = []

    for import_id, items in items_needing_categorization.items():
        items_numbered = "\n".join([f"{i+1}. {item[:80]}" for i, item in enumerate(items)])

        prompt = f"""Categorize each Amazon product into a budget category based on what the product is.

Products:
{items_numbered}
{CATEGORIZATION_RULES}
FORMAT RULES:
1. Return ONLY the category name (text BEFORE the parentheses)
2. DO NOT include descriptions or explanations - just the category name
3. Copy the category name exactly, including any emoji
4. One category per line, numbered to match products

Example correct responses:
1. Snacks
2. Dairy
3. 🍌Groceries

Example WRONG responses (never do this):
1. Snacks - chips and crackers
2. Dairy (cheese products)

Valid categories (return ONLY the category name, not the description in parentheses):
{categories_prompt}

Reply:"""

        # Convert import_id to valid custom_id (no colons allowed)
        custom_id = import_id_to_custom_id(import_id)

        requests.append({
            "custom_id": custom_id,
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}]
            }
        })

    log(f"Submitting {len(requests)} categorization requests to Batches API...")
    log("  (50% cheaper than synchronous API, results in up to 24 hours)")

    try:
        batch = client.messages.batches.create(requests=requests)
        batch_id = batch.id

        log(f"\nBatch submitted successfully!")
        log(f"  Batch ID: {batch_id}")
        log(f"  Status: {batch.processing_status}")
        log(f"  Requests: {len(requests)}")

        # Save batch info for tracking (include categories for validation on retrieval)
        pending = load_pending_batches(cache_dir)
        pending["batches"].append({
            "batch_id": batch_id,
            "cache_file": str(cache_file),
            "submitted_at": datetime.now().isoformat(),
            "request_count": len(requests),
            "items": {import_id: items for import_id, items in items_needing_categorization.items()},
            "ynab_categories": ynab_categories,
            "cat_to_group": cat_to_group,
        })
        save_pending_batches(cache_dir, pending)

        log(f"\nTo check status: python process_transactions.py --batch-status {batch_id}")
        log(f"To get results:  python process_transactions.py --batch-results {batch_id}")

        return batch_id

    except Exception as e:
        log(f"Error submitting batch: {e}")
        return ""


def check_batch_status(batch_id: str, client) -> dict:
    """Check the status of a batch job."""
    try:
        batch = client.messages.batches.retrieve(batch_id)
        return {
            "id": batch.id,
            "status": batch.processing_status,
            "created_at": str(batch.created_at) if batch.created_at else None,
            "ended_at": str(batch.ended_at) if batch.ended_at else None,
            "request_counts": {
                "processing": batch.request_counts.processing,
                "succeeded": batch.request_counts.succeeded,
                "errored": batch.request_counts.errored,
                "canceled": batch.request_counts.canceled,
                "expired": batch.request_counts.expired,
            }
        }
    except Exception as e:
        return {"error": str(e)}


def wait_for_batch(batch_id: str, client, timeout_minutes: int = 10, poll_interval: int = 30) -> dict:
    """
    Wait for a batch to complete with timeout.

    Args:
        batch_id: The batch ID to wait for
        client: Anthropic client
        timeout_minutes: Maximum time to wait before cancelling (default 10 minutes)
        poll_interval: Seconds between status checks (default 30)

    Returns:
        dict with final status or error
    """
    import time
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60

    log(f"Waiting for batch {batch_id} (timeout: {timeout_minutes} min)...")

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            log(f"  Batch timed out after {timeout_minutes} minutes. Cancelling...")
            try:
                client.messages.batches.cancel(batch_id)
                return {"error": f"Batch cancelled after {timeout_minutes} minute timeout", "cancelled": True}
            except Exception as e:
                return {"error": f"Timeout and cancel failed: {e}"}

        status = check_batch_status(batch_id, client)
        if "error" in status:
            return status

        if status["status"] == "ended":
            log(f"  Batch completed in {int(elapsed)} seconds")
            return status

        if status["status"] == "canceled":
            return {"error": "Batch was cancelled", "status": status}

        succeeded = status["request_counts"]["succeeded"]
        processing = status["request_counts"]["processing"]
        log(f"  Status: {status['status']} ({succeeded} done, {processing} processing) - {int(elapsed)}s elapsed")

        time.sleep(poll_interval)


def retrieve_batch_results(batch_id: str, client, cache_dir: Path) -> dict:
    """
    Retrieve results from a completed batch and apply categorizations.

    Returns:
        dict with results summary
    """
    # Check batch status first
    status = check_batch_status(batch_id, client)
    if "error" in status:
        return status

    if status["status"] != "ended":
        return {
            "error": f"Batch not complete yet. Status: {status['status']}",
            "status": status
        }

    # Find the batch in our tracking file
    pending = load_pending_batches(cache_dir)
    batch_info = None
    for b in pending["batches"]:
        if b["batch_id"] == batch_id:
            batch_info = b
            break

    if not batch_info:
        return {"error": f"Batch {batch_id} not found in tracking file. Was it submitted from this directory?"}

    cache_file = Path(batch_info["cache_file"])
    items_map = batch_info.get("items", {})

    # Get YNAB categories from stored batch info (or fetch fresh if not stored)
    ynab_categories = batch_info.get("ynab_categories", [])
    cat_to_group = batch_info.get("cat_to_group", {})

    if not ynab_categories:
        log("Warning: No YNAB categories stored with batch - fetching from YNAB...")
        ynab_categories, cat_to_group = get_ynab_categories()

    log(f"Retrieving results for batch {batch_id}...")

    # Get results from API
    results = {}
    unmatched_categories = {}  # cat -> list of items assigned to it
    try:
        for result in client.messages.batches.results(batch_id):
            # Convert custom_id back to import_id
            import_id = custom_id_to_import_id(result.custom_id)

            if result.result.type == "succeeded":
                response = result.result.message
                if response.content:
                    response_text = response.content[0].text

                    # Parse numbered response
                    categories = defaultdict(list)
                    items = items_map.get(import_id, [])

                    for line in response_text.strip().split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split(".", 1)
                        if len(parts) == 2:
                            try:
                                idx = int(parts[0].strip()) - 1
                                cat = parts[1].strip()

                                # Clean up category - strip descriptions/explanations
                                if "(" in cat:
                                    cat = cat.split("(")[0].strip()
                                for marker in [" - ", " since ", " because "]:
                                    if marker in cat.lower():
                                        cat = cat.split(marker)[0].strip()

                                if 0 <= idx < len(items):
                                    item_name = items[idx]

                                    # Detect product names (too long, contains size/brand indicators)
                                    looks_like_product = (
                                        len(cat) > 40 or "," in cat or
                                        "ounce" in cat.lower() or "oz" in cat.lower() or
                                        "pack" in cat.lower() or "count" in cat.lower() or
                                        cat.lower().startswith("organic ") or
                                        "365 " in cat or "by whole foods" in cat.lower()
                                    )

                                    if looks_like_product:
                                        was_matched = False
                                        matched_cat = cat
                                    else:
                                        # Match category with fuzzy emoji support
                                        matched_cat, was_matched = match_category(cat, ynab_categories)

                                    if was_matched:
                                        categories[matched_cat].append(item_name)
                                        cache_category(item_name, matched_cat)
                                    else:
                                        # Retry with synchronous API call
                                        retry_cat = retry_categorize_item(item_name, ynab_categories, client, cat_to_group)
                                        if retry_cat:
                                            log(f"  Retry: '{cat[:30]}...' -> '{retry_cat}'")
                                            categories[retry_cat].append(item_name)
                                            cache_category(item_name, retry_cat)
                                        else:
                                            # Track unmatched category for logging
                                            if cat not in unmatched_categories:
                                                unmatched_categories[cat] = []
                                            unmatched_categories[cat].append(item_name)
                                            # Use fallback category instead of invalid name
                                            fallback = "🍌Groceries" if "🍌Groceries" in ynab_categories else "Groceries"
                                            categories[fallback].append(item_name)
                                            cache_category(item_name, fallback)
                            except ValueError:
                                pass

                    results[import_id] = dict(categories) if categories else {}
            else:
                log(f"  Request {import_id} failed: {result.result.type}")
                results[import_id] = {}

        # Save category cache
        save_category_cache()

    except Exception as e:
        return {"error": f"Error retrieving results: {e}"}

    # Report unmatched categories
    if unmatched_categories:
        log(f"\n  WARNING: {len(unmatched_categories)} categories don't match any YNAB category:")
        for cat, items in sorted(unmatched_categories.items()):
            log(f"    '{cat}' - used for {len(items)} item(s): {items[0][:40]}...")
        log(f"  These will need manual category assignment in YNAB.")

    log(f"Retrieved {len(results)} categorization results")

    # Now apply results to the cache file
    if not cache_file.exists():
        return {"error": f"Cache file not found: {cache_file}"}

    cache = load_cache(cache_file)

    # Find transactions that need categorization applied
    applied = 0
    for txn in cache["transactions"]:
        import_id = txn.get("import_id")
        if import_id in results and not txn.get("splits"):
            categorized = results[import_id]

            # Also check local cache for any items not in batch results
            if import_id in items_map:
                for item in items_map[import_id]:
                    cached_cat = get_cached_category(item)
                    if cached_cat:
                        if cached_cat not in categorized:
                            categorized[cached_cat] = []
                        if item not in categorized[cached_cat]:
                            categorized[cached_cat].append(item)

            if not categorized:
                continue

            # Create one split per category, with proportional amounts
            total_items = sum(len(items) for items in categorized.values())
            amount = txn["amount"]

            # Build splits for each category
            splits = []
            remaining_amount = amount
            categories_list = list(categorized.items())

            for i, (cat, items) in enumerate(categories_list):
                # Last category gets remaining amount to avoid rounding issues
                if i == len(categories_list) - 1:
                    split_amount = remaining_amount
                else:
                    # Proportional allocation by item count
                    proportion = len(items) / total_items
                    split_amount = round(amount * proportion, 2)
                    remaining_amount -= split_amount

                # Format memo with quantity prefix for duplicate items
                from collections import Counter
                item_counts = Counter(items)
                memo_parts = []
                for item_name, count in item_counts.items():
                    if count > 1:
                        memo_parts.append(f"{count} x {item_name[:20]}")
                    else:
                        memo_parts.append(item_name[:25])

                items_desc = ", ".join(memo_parts[:3])
                if len(memo_parts) > 3:
                    items_desc += f" (+{len(memo_parts) - 3})"

                splits.append({
                    "category": cat,
                    "amount": split_amount,
                    "memo": items_desc,
                    "items": list(item_counts.keys()),  # Unique items
                })

            txn["splits"] = splits
            txn["last_updated"] = datetime.now().isoformat()
            applied += 1

            cat_summary = ", ".join([f"{s['category']}" for s in splits[:3]])
            if len(splits) > 3:
                cat_summary += f" (+{len(splits) - 3})"
            log(f"  {txn['order_id']}: {cat_summary}")

    # Save updated cache
    save_cache(cache_file, cache)

    # Save CSV report
    csv_file = cache_file.with_suffix(".csv")
    save_csv_report(cache["transactions"], csv_file, cat_to_group)

    # Remove batch from pending list
    pending["batches"] = [b for b in pending["batches"] if b["batch_id"] != batch_id]
    save_pending_batches(cache_dir, pending)

    log(f"\nApplied categorization to {applied} transactions")
    log(f"Updated: {cache_file}")
    log(f"CSV report: {csv_file}")

    return {
        "batch_id": batch_id,
        "results_count": len(results),
        "applied_count": applied,
        "cache_file": str(cache_file),
    }


def list_pending_batches(cache_dir: Path, client) -> None:
    """List all pending batch jobs with their current status."""
    pending = load_pending_batches(cache_dir)

    if not pending["batches"]:
        log("No pending batches.")
        return

    log(f"Pending batches ({len(pending['batches'])}):\n")

    for batch_info in pending["batches"]:
        batch_id = batch_info["batch_id"]
        status = check_batch_status(batch_id, client)

        log(f"  Batch: {batch_id}")
        log(f"    Submitted: {batch_info['submitted_at']}")
        log(f"    Requests: {batch_info['request_count']}")
        log(f"    Cache file: {batch_info['cache_file']}")

        if "error" in status:
            log(f"    Status: ERROR - {status['error']}")
        else:
            log(f"    Status: {status['status']}")
            counts = status["request_counts"]
            log(f"    Progress: {counts['succeeded']} succeeded, {counts['processing']} processing, {counts['errored']} errored")

            if status["status"] == "ended":
                log(f"    Ready! Run: python process_transactions.py --batch-results {batch_id}")

        log("")


def load_cache(cache_file: Path) -> dict:
    """Load cache from JSON file, returning empty cache if file is missing or corrupt."""
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
                # Validate structure
                if "transactions" not in data:
                    data["transactions"] = []
                return data
        except (json.JSONDecodeError, IOError) as e:
            log(f"Warning: Could not load cache file {cache_file}: {e}")
            log("  Starting with empty cache")
    return {"transactions": [], "synced": []}


# Write operations delegated to file_writer module
from file_writer import save_cache, save_csv_report


def main():
    parser = argparse.ArgumentParser(
        description="Process Amazon transactions (no YNAB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Batch Processing (50% cheaper, up to 24 hours):
  Submit:  python process_transactions.py data/amazon/ynab_amazon_2025.csv --batch
  Status:  python process_transactions.py --batch-status
  Results: python process_transactions.py --batch-results BATCH_ID
        """
    )
    parser.add_argument("input", nargs="?", help="Input bank statement CSV")
    parser.add_argument("--history", "-H", nargs="*", default=["data/amazon/order history crs", "data/amazon/order history jss"], help="Amazon order history directories")
    parser.add_argument("--output", "-o", help="Output cache file")
    parser.add_argument("--start-date", help="Filter transactions on or after this date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Filter transactions on or before this date (YYYY-MM-DD)")

    # Batch processing options
    parser.add_argument("--batch", "-b", action="store_true",
                        help="Use Batches API (50%% cheaper, async processing)")
    parser.add_argument("--batch-status", nargs="?", const="all", metavar="BATCH_ID",
                        help="Check status of batch jobs (specify ID or omit for all)")
    parser.add_argument("--batch-results", metavar="BATCH_ID",
                        help="Retrieve and apply results from a completed batch")

    args = parser.parse_args()

    # Validate API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log("Error: ANTHROPIC_API_KEY not set in environment or .env file")
        log("  Get your key from: https://console.anthropic.com/")
        return 1

    cache_dir = get_cache_dir()
    claude = anthropic.Anthropic(api_key=api_key)

    # Handle batch status check
    if args.batch_status:
        if args.batch_status == "all":
            list_pending_batches(cache_dir, claude)
        else:
            status = check_batch_status(args.batch_status, claude)
            if "error" in status:
                log(f"Error: {status['error']}")
            else:
                log(f"Batch: {status['id']}")
                log(f"Status: {status['status']}")
                counts = status["request_counts"]
                log(f"Succeeded: {counts['succeeded']}, Processing: {counts['processing']}, Errored: {counts['errored']}")
                if status["status"] == "ended":
                    log(f"\nRun to apply results: python process_transactions.py --batch-results {args.batch_status}")
        return 0

    # Handle batch results retrieval
    if args.batch_results:
        load_category_cache()
        result = retrieve_batch_results(args.batch_results, claude, cache_dir)
        if "error" in result:
            log(f"Error: {result['error']}")
            return 1
        return 0

    # Normal processing requires input file
    if not args.input:
        parser.print_help()
        return 1

    # Validate input file
    if not os.path.exists(args.input):
        log(f"Error: Input file not found: {args.input}")
        return 1

    log("Loading Amazon order history...")
    order_history = load_order_history(args.history)

    log("Loading category cache...")
    load_category_cache()

    log("Fetching YNAB categories...")
    ynab_categories, cat_to_group = get_ynab_categories()
    if not ynab_categories:
        log("Error: Could not load YNAB categories. Check YNAB_TOKEN and BUDGET_NAME in .env")
        return 1

    log(f"\nReading {args.input}...")
    with open(args.input, "r") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        log("Error: Input CSV file is empty or has no data rows")
        return 1

    log(f"Found {len(rows)} transactions")

    # Filter by date range if specified
    if args.start_date or args.end_date:
        start_dt = datetime.strptime(args.start_date, "%Y-%m-%d") if args.start_date else None
        end_dt = datetime.strptime(args.end_date, "%Y-%m-%d") if args.end_date else None
        filtered = []
        for row in rows:
            try:
                date_str = row.get("Date", "")
                # Try YYYY-MM-DD format first, then MM/DD/YYYY
                try:
                    row_dt = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    row_dt = datetime.strptime(date_str, "%m/%d/%Y")
                if start_dt and row_dt < start_dt:
                    continue
                if end_dt and row_dt > end_dt:
                    continue
                filtered.append(row)
            except ValueError:
                continue
        log(f"Filtered to {len(filtered)} transactions (date range: {args.start_date or 'start'} to {args.end_date or 'end'})")
        rows = filtered

    # Determine cache file name from input file or first transaction date
    cache_dir = get_cache_dir()
    if args.output:
        cache_file = Path(args.output)
    else:
        # Try to get year from input filename first (e.g., ynab_amazon_2024.csv)
        input_name = Path(args.input).stem
        import re
        year_match = re.search(r'20\d{2}', input_name)
        if year_match:
            cache_file = cache_dir / f"{year_match.group()}-all.json"
        else:
            # Fall back to first transaction date
            first_date = rows[0].get("Date", "")
            try:
                dt = datetime.strptime(first_date, "%m/%d/%Y")
                cache_file = cache_dir / f"{dt.year}-all.json"
            except ValueError:
                cache_file = cache_dir / "transactions.json"

    cache = load_cache(cache_file)
    # Guard against transactions missing import_id (legacy data)
    existing_ids = {t["import_id"] for t in cache["transactions"] if t.get("import_id")}

    stats = {"processed": 0, "not_found": 0, "cached": 0, "grocery": 0}

    # First pass: collect transactions and items to categorize
    pending_txns = []  # Transactions with items to categorize
    items_to_categorize = {}  # import_id -> {items, is_grocery}

    log("\nPass 1: Matching orders to history...")
    for row in rows:
        date = row.get("Date", "")
        payee = row.get("Payee", "")
        memo = row.get("Memo", "")
        outflow = row.get("Outflow", "").replace("$", "").replace(",", "").strip()
        inflow = row.get("Inflow", "").replace("$", "").replace(",", "").strip()

        if not is_amazon_transaction(payee):
            continue

        order_id = extract_order_id(memo)
        if not order_id:
            continue

        # Parse amount - inflow is positive (refund), outflow is negative (purchase)
        try:
            if inflow:
                amount = Decimal(inflow)
            elif outflow:
                amount = -Decimal(outflow)
            else:
                continue
        except decimal.InvalidOperation:
            log(f"  Warning: Could not parse amount for order {order_id}: inflow={inflow}, outflow={outflow}")
            continue

        amount_cents = int(abs(amount) * 100)
        direction = "R" if inflow else "P"
        import_id = f"AMZ2:{order_id}:{amount_cents}:{direction}"

        if import_id in existing_ids:
            stats["cached"] += 1
            continue

        # Parse date - try common formats
        date_str = date
        for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"]:
            try:
                date_str = datetime.strptime(date, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

        is_grocery = is_grocery_transaction(payee)

        txn = {
            "import_id": import_id,
            "date": date_str,
            "order_id": order_id,
            "amount": float(amount),
            "payee": "Whole Foods" if "whole foods" in payee.lower() else "Amazon Fresh" if is_grocery else "Amazon.com",
            "memo": f"Order {order_id}",
            "is_refund": bool(inflow),
            "is_grocery": is_grocery,
            "flag": "yellow",
            "splits": [],
            "last_updated": datetime.now().isoformat(),
        }

        # Look up order
        order_data = order_history.get(order_id)
        if not order_data:
            txn["flag"] = "blue"
            txn["memo"] = f"Order {order_id} - NEEDS ITEMIZATION"
            cache["transactions"].append(txn)
            stats["not_found"] += 1
            continue

        # =================================================================
        # TIP DETECTION
        # =================================================================
        # Amazon Fresh/Whole Foods tips have "Amazon Tips" in the payee field
        # These should not be itemized - just categorize as Delivery Fee.
        # =================================================================
        if "amazon tips" in payee.lower():
            abs_amount = abs(amount)
            is_refund = txn.get("is_refund", False)
            txn["memo"] = "Delivery Tip"
            txn["splits"] = [{
                "category": "Delivery Fee",
                "amount": float(-abs_amount) if not is_refund else float(abs_amount),
                "memo": "Delivery Tip",
                "items": [],
            }]
            txn["items"] = []
            txn["items_with_amounts"] = []
            cache["transactions"].append(txn)
            stats["processed"] += 1
            log(f"  {order_id}: Delivery Tip ${abs_amount}")
            continue

        # =================================================================
        # SHIPMENT MATCHING (see module docstring for full explanation)
        # =================================================================
        # Goal: Find which items from this order correspond to this bank charge
        #
        # Matching strategies (in order of preference):
        #   1. Date proximity: shipment.ship_date closest to bank charge date
        #   2. Amount match: shipment.total ≈ charge amount (within $1)
        #   3. Single item: individual item.total ≈ charge amount
        #   4. Best fit: closest shipment total to charge amount
        #
        # After matching, apply proportional allocation:
        #   ratio = charge_amount / shipment_total
        #   item_allocated = item_total × ratio
        # This handles gift cards/rewards that reduce the charge amount.
        # =================================================================

        # Parse bank charge date for date-based matching
        try:
            charge_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            charge_date = None

        shipments = order_data["shipments"]
        all_items = order_data["items"]
        matched_shipment = None
        matched_items_with_amounts = None

        # Strategy 1: Date proximity (preferred - most reliable)
        if charge_date:
            best_match = None
            best_days_diff = 999
            for shipment in shipments:
                if shipment["ship_date"]:
                    days_diff = (charge_date - shipment["ship_date"]).days
                    # Shipment should be on or before charge date (0-3 days typical)
                    if 0 <= days_diff <= 7 and days_diff < best_days_diff:
                        best_days_diff = days_diff
                        best_match = shipment

            if best_match:
                matched_shipment = best_match

        # Strategy 2: Fall back to amount matching if date matching fails
        if not matched_shipment:
            for shipment in shipments:
                if abs(shipment["total"] - abs(amount)) < Decimal("1.00"):
                    matched_shipment = shipment
                    break

        # Strategy 3: Try single item match
        if not matched_shipment:
            for item in all_items:
                if abs(item["total"] - abs(amount)) < Decimal("1.00"):
                    matched_items_with_amounts = [{"name": item["name"], "amount": float(amount)}]
                    break

        # Strategy 4: Best shipment within tolerance
        if not matched_shipment and not matched_items_with_amounts:
            best_diff = Decimal("999999")
            for shipment in shipments:
                diff = abs(shipment["total"] - abs(amount))
                if diff < best_diff:
                    best_diff = diff
                    matched_shipment = shipment

        # Apply proportional allocation if we matched a shipment
        if matched_shipment and not matched_items_with_amounts:
            shipment_total = matched_shipment["total"]
            charge_amount = abs(amount)

            if shipment_total > 0:
                # Calculate ratio for proportional allocation
                ratio = float(charge_amount / shipment_total)

                matched_items_with_amounts = []
                for item in matched_shipment["items"]:
                    item_amount = float(item["total"]) * ratio
                    qty = item.get("qty", 1)
                    # Include quantity in display name if > 1 (e.g., "2 x Paper Towels")
                    # Keep base_name for categorization (without qty prefix)
                    display_name = f"{qty} x {item['name']}" if qty > 1 else item["name"]
                    matched_items_with_amounts.append({
                        "name": display_name,  # For memo display
                        "base_name": item["name"],  # For categorization
                        "amount": round(item_amount, 2),
                        "original_total": float(item["total"]),
                        "qty": qty,
                    })

        if not matched_items_with_amounts:
            txn["flag"] = "blue"
            txn["memo"] = f"Order {order_id} - NO SHIPMENT MATCH"
            txn["all_items"] = [item["name"] for item in all_items]
            cache["transactions"].append(txn)
            stats["not_found"] += 1
            continue

        # Determine if this is a grocery shipment (from order history shipping option)
        shipment_is_grocery = matched_shipment.get("is_grocery", False) if matched_shipment else False
        # Also check order-level grocery flag, or fall back to payee-based detection
        order_is_grocery = order_data.get("is_grocery", False)
        is_grocery = shipment_is_grocery or order_is_grocery or is_grocery_transaction(payee)
        txn["is_grocery"] = is_grocery

        # Extract item names for categorization (use base_name without qty prefix)
        base_items = [item.get("base_name", item["name"]) for item in matched_items_with_amounts]
        txn["items"] = [item["name"] for item in matched_items_with_amounts]  # Display names with qty
        txn["items_with_amounts"] = matched_items_with_amounts

        # =================================================================
        # GROCERY ORDER HANDLING
        # =================================================================
        # Grocery orders (Whole Foods, Amazon Fresh) are categorized as a single
        # "Groceries" split without item-by-item categorization. Item details are
        # stored in grocery_items for separate analysis.
        # =================================================================
        if is_grocery:
            # Store items for analysis (not for YNAB splits)
            txn["grocery_items"] = matched_items_with_amounts
            # Create single split with "Groceries" category
            # Parent memo has order number, split memo is just "Groceries"
            if txn.get("is_refund"):
                split_amount = abs(amount)
            else:
                split_amount = -abs(amount)
            txn["splits"] = [{
                "category": "Groceries",
                "amount": float(split_amount),
                "memo": "Groceries",
                "items": [item["name"] for item in matched_items_with_amounts],
            }]
            cache["transactions"].append(txn)
            stats["processed"] += 1
            stats["grocery"] += 1
            log(f"  {order_id}: Groceries (${abs(amount):.2f}, {len(matched_items_with_amounts)} items)")
            continue

        # Non-grocery orders: add to categorization queue for itemized splits
        pending_txns.append(txn)
        items_to_categorize[import_id] = {"items": base_items, "is_grocery": False}

    log(f"  Found {len(pending_txns)} transactions to categorize, {stats['not_found']} not found, {stats['cached']} cached")

    # Second pass: categorize items
    if items_to_categorize:
        if args.batch:
            # Use async Batches API (50% cheaper)
            log(f"\nPass 2: Submitting {len(items_to_categorize)} transactions to Batches API...")

            # Save pending transactions to cache first (without splits)
            for txn in pending_txns:
                cache["transactions"].append(txn)

            save_cache(cache_file, cache)

            # Submit batch
            batch_id = submit_batch_categorization(items_to_categorize, claude, cache_dir, cache_file,
                                                   ynab_categories, cat_to_group)

            if batch_id:
                stats["processed"] = len(pending_txns)
                log(f"\nTransactions saved to cache (pending categorization)")
                log(f"Once batch completes, run:")
                log(f"  python process_transactions.py --batch-results {batch_id}")
            else:
                log("Batch submission failed or all items were cached")
        else:
            # Use synchronous API (immediate results)
            log(f"\nPass 2: Categorizing {len(items_to_categorize)} transactions...")
            categorized_results = batch_categorize_items(items_to_categorize, claude,
                                                         ynab_categories, cat_to_group)

            # Apply categorization results - ONE SPLIT PER ITEM
            for txn in pending_txns:
                import_id = txn["import_id"]
                categorized = categorized_results.get(import_id, {})

                # Build item name → category mapping
                item_to_category = {}
                for cat, items in categorized.items():
                    for item_name in items:
                        item_to_category[item_name] = cat

                # Get items with their proportional amounts
                items_with_amounts = txn.get("items_with_amounts", [])

                if items_with_amounts:
                    # Create a split for EACH item with its proportional amount
                    for item_data in items_with_amounts:
                        display_name = item_data["name"]  # With qty prefix for memo
                        base_name = item_data.get("base_name", display_name)  # Without qty for category lookup
                        item_amount = item_data["amount"]

                        # Get category for this item (fallback if not found)
                        category = item_to_category.get(base_name, "Household Supplies")

                        # For purchases, amount should be negative; for refunds, positive
                        if txn.get("is_refund"):
                            split_amount = abs(item_amount)
                        else:
                            split_amount = -abs(item_amount)

                        txn["splits"].append({
                            "category": category,
                            "amount": split_amount,
                            "memo": display_name[:50],  # Show qty prefix in memo
                            "items": [display_name],
                        })
                else:
                    # Fallback: no proportional amounts, use single split
                    all_items = txn.get("items", [])
                    best_cat = max(categorized.keys(), key=lambda c: len(categorized[c])) if categorized else "Household Supplies"
                    items_desc = ", ".join([n[:25] for n in all_items[:3]])
                    if len(all_items) > 3:
                        items_desc += f" (+{len(all_items) - 3})"

                    txn["splits"].append({
                        "category": best_cat,
                        "amount": txn["amount"],
                        "memo": items_desc,
                        "items": all_items,
                    })

                cache["transactions"].append(txn)
                stats["processed"] += 1
                # Log categories used
                cats_used = list(set(s["category"] for s in txn["splits"]))
                log(f"  {txn['order_id']}: {', '.join(cats_used[:3])}" + (f" (+{len(cats_used)-3})" if len(cats_used) > 3 else ""))

            # Save cache and CSV only for synchronous mode (batch mode saves earlier)
            save_cache(cache_file, cache)
            csv_file = cache_file.with_suffix(".csv")
            save_csv_report(cache["transactions"], csv_file, cat_to_group)

    log(f"\n{'='*50}")
    log(f"Processed: {stats['processed']} ({stats['grocery']} grocery), Not Found: {stats['not_found']}, Cached: {stats['cached']}")
    log(f"Saved to: {cache_file}")
    if not args.batch:
        csv_file = cache_file.with_suffix(".csv")
        log(f"CSV report: {csv_file}")

    # Show summary of issues
    needs_attention = [t for t in cache["transactions"] if t.get("flag") == "blue"]
    if needs_attention:
        log(f"\n{len(needs_attention)} transactions need attention:")
        for t in needs_attention:
            log(f"  {t['date']} {t['order_id']} ${abs(t['amount']):.2f} - {t.get('memo', '')[:50]}")


if __name__ == "__main__":
    main()
