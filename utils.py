"""Shared utilities for YNAB Amazon Itemizer."""

import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

# Category to category group mapping
CATEGORY_TO_GROUP = {
    # Grocery categories
    "Produce": "Groceries",
    "Dairy": "Groceries",
    "Meat": "Groceries",
    "Seafood": "Groceries",
    "Bakery": "Groceries",
    "Frozen": "Groceries",
    "Beverages": "Groceries",
    "Snacks": "Groceries",
    "Pantry": "Groceries",
    "Canned Items": "Groceries",
    "Household": "Home & Lifestyle",
    "Personal Care": "Health & Personal Care",
    # Regular categories
    "Shopping": "Shopping",
    "Electronics": "Shopping",
    "Home & Garden": "Home & Lifestyle",
    "Clothing": "Shopping",
    "Health & Personal Care": "Health & Personal Care",
    "Kids": "Kids",
    "Pets": "Home & Lifestyle",
    "Entertainment": "Entertainment",
    "Office": "Shopping",
    "Sports & Outdoors": "Shopping",
    "Automotive": "Transportation",
    "Arts & Crafts": "Shopping",
}

# Regex pattern for Amazon order IDs
ORDER_ID_PATTERN = re.compile(r'Order:\s*(\d{3}-\d{7}-\d{7})')


def get_cache_dir() -> Path:
    """Get cache directory based on account name."""
    account_name = os.getenv("ACCOUNT_NAME", "default")
    clean_name = "".join(c if c.isalnum() or c in " -_" else "" for c in account_name).strip()
    clean_name = clean_name.replace(" ", "-").lower()
    cache_dir = Path("data/processed") / clean_name
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def log(msg: str):
    """Print a log message with immediate flush."""
    print(msg, flush=True)


def extract_order_id(memo: str) -> Optional[str]:
    """Extract Amazon order ID from memo field."""
    if not memo:
        return None
    match = ORDER_ID_PATTERN.search(memo)
    return match.group(1) if match else None


def is_amazon_transaction(payee: str) -> bool:
    """Check if a transaction is from Amazon."""
    if not payee:
        return False
    payee_lower = payee.lower()
    return any(x in payee_lower for x in ["amazon", "amzn"])


def is_grocery_transaction(payee: str) -> bool:
    """Check if a transaction is from Amazon grocery services."""
    if not payee:
        return False
    payee_lower = payee.lower()
    return any(g in payee_lower for g in ["amazon fresh", "whole foods", "amazon groce"])


# Item category cache - maps normalized item names to categories
_category_cache: Dict[str, str] = {}
_cache_file: Optional[Path] = None
_cache_dirty: bool = False


def _normalize_item_name(name: str) -> str:
    """Normalize item name for cache lookup (lowercase, first 60 chars)."""
    return name.strip().lower()[:60]


def load_category_cache(cache_dir: Optional[Path] = None) -> Dict[str, str]:
    """Load category cache from disk.

    Args:
        cache_dir: Directory to store cache file. Defaults to get_cache_dir().

    Returns:
        Dictionary mapping normalized item names to categories.
    """
    global _category_cache, _cache_file

    if cache_dir is None:
        cache_dir = get_cache_dir()

    _cache_file = cache_dir / "category_cache.json"

    if _cache_file.exists():
        try:
            with open(_cache_file, "r") as f:
                _category_cache = json.load(f)
            log(f"Loaded {len(_category_cache)} cached item categories")
        except (json.JSONDecodeError, IOError):
            _category_cache = {}

    return _category_cache


def get_cached_category(item_name: str) -> Optional[str]:
    """Get cached category for an item name.

    Args:
        item_name: The item name to look up.

    Returns:
        Category name if cached, None otherwise.
    """
    key = _normalize_item_name(item_name)
    return _category_cache.get(key)


def cache_category(item_name: str, category: str) -> None:
    """Cache a category for an item name.

    Args:
        item_name: The item name.
        category: The category to cache.
    """
    global _cache_dirty
    key = _normalize_item_name(item_name)
    if key and category:
        _category_cache[key] = category
        _cache_dirty = True


def save_category_cache() -> None:
    """Save category cache to disk if modified.

    NOTE: This is a write operation. The actual write is delegated to file_writer.
    """
    global _cache_dirty

    if not _cache_dirty or not _cache_file:
        return

    from file_writer import save_category_cache as _save_cache
    if _save_cache(_cache_file, _category_cache, _cache_dirty):
        _cache_dirty = False
