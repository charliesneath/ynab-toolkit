"""File write operations for caches, reports, and logs.

This module contains all file system write operations.
For read-only operations, use the original modules directly.

IMPORTANT: Importing from this module indicates destructive intent and
will trigger permission prompts via the auto_approve_reads hook.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def save_cache(cache_file: Path, data: dict) -> None:
    """Save transaction cache to JSON file.

    Args:
        cache_file: Path to the cache file
        data: Cache data to save
    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2, default=str)


def save_pending_batches(cache_dir: Path, data: dict) -> None:
    """Save pending batch jobs to tracking file.

    Args:
        cache_dir: Directory containing batch tracking
        data: Batch tracking data
    """
    batch_file = cache_dir / "pending_batches.json"
    with open(batch_file, "w") as f:
        json.dump(data, f, indent=2)


def save_category_cache(cache_file: Path, cache_data: dict, dirty: bool = True) -> bool:
    """Save category cache to disk.

    Args:
        cache_file: Path to the cache file
        cache_data: Dictionary mapping item names to categories
        dirty: Whether the cache has been modified (skip save if False)

    Returns:
        True if saved, False if skipped
    """
    if not dirty or not cache_file:
        return False

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=2)
        return True
    except IOError as e:
        print(f"Warning: Could not save category cache: {e}")
        return False


def log_miscategorization(
    item: str,
    original_category: str,
    new_category: str,
    cache_dir: Optional[Path] = None
) -> None:
    """Log miscategorizations for pattern analysis.

    Args:
        item: The item name
        original_category: The initial (wrong) category
        new_category: The corrected category
        cache_dir: Directory to store log file
    """
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


def save_csv_report(
    transactions: list,
    csv_file: Path,
    cat_to_group: Optional[Dict[str, str]] = None
) -> None:
    """Save a CSV report of transactions for review.

    Args:
        transactions: List of transaction dicts
        csv_file: Path to output CSV file
        cat_to_group: Optional mapping of category name to group name
    """
    if cat_to_group is None:
        cat_to_group = {}

    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Date", "Order ID", "Amount", "Type", "Status", "Payee",
            "Category Groups", "Categories", "Items", "Last Updated", "Notes"
        ])

        for txn in transactions:
            is_refund = txn.get("is_refund", False)
            status = "OK" if txn.get("flag") == "yellow" else "NEEDS ATTENTION"

            # Build categories and groups strings
            cats = []
            groups = set()
            for split in txn.get("splits", []):
                cat = split.get("category", "")
                cats.append(cat)
                groups.add(cat_to_group.get(cat, "Unknown"))
            categories = "; ".join(cats) if cats else ""
            category_groups = "; ".join(sorted(groups)) if groups else ""

            # Build items string
            items = txn.get("items", txn.get("all_items", []))
            items_str = "; ".join([i[:50] for i in items[:5]])
            if len(items) > 5:
                items_str += f" (+{len(items) - 5} more)"

            # Notes about what's needed
            notes = ""
            if "NEEDS ITEMIZATION" in txn.get("memo", ""):
                notes = "Order not found - need order history export"
            elif "NO SHIPMENT MATCH" in txn.get("memo", ""):
                notes = "Items found but charge doesn't match - may need manual review"
            elif not txn.get("splits"):
                notes = "No splits created"

            # Last updated timestamp
            last_updated = txn.get("last_updated", "")
            if last_updated:
                try:
                    dt = datetime.fromisoformat(last_updated)
                    last_updated = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    pass  # Keep original string if parsing fails

            writer.writerow([
                txn.get("date", ""),
                txn.get("order_id", ""),
                f"${abs(txn.get('amount', 0)):.2f}",
                "Refund" if is_refund else "Purchase",
                status,
                txn.get("payee", ""),
                category_groups,
                categories,
                items_str,
                last_updated,
                notes,
            ])
