"""Sync processed transactions to YNAB."""

import argparse
import csv
import json
import os
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from ynab_client import YNABClient
from ynab_writer import YNABWriter
from utils import get_cache_dir, log

load_dotenv()


# Category groups to exclude from categorization
EXCLUDED_CATEGORY_GROUPS = ['library renovation']


def get_category_mapping(ynab: YNABClient, budget_id: str) -> dict:
    """Build mapping from category name -> category_id."""
    all_categories = ynab.get_categories(budget_id)

    # Filter out excluded groups
    categories = [c for c in all_categories
                  if c.group_name.lower() not in EXCLUDED_CATEGORY_GROUPS]
    mapping = {}

    for cat in categories:
        # Store by exact name and lowercase for flexible matching
        mapping[cat.name] = cat.category_id
        mapping[cat.name.lower()] = cat.category_id

    return mapping


def find_category_id(name: str, mapping: dict) -> str | None:
    """Find category ID by name with fuzzy matching."""
    if not name:
        return None

    # Exact match
    if name in mapping:
        return mapping[name]
    if name.lower() in mapping:
        return mapping[name.lower()]

    # Fuzzy match
    name_lower = name.lower()
    for cat_name, cat_id in mapping.items():
        if name_lower in cat_name.lower() or cat_name.lower() in name_lower:
            return cat_id

    return None


def get_existing_transactions(ynab: YNABClient, budget_id: str, account_id: str, since_date: str = None) -> dict:
    """Get existing transactions mapped by import_id.

    Args:
        since_date: Date string in YYYY-MM-DD format. Defaults to 2 years ago.

    Returns:
        Dict mapping import_id -> {transaction_id, subtransactions}
    """
    if not since_date:
        # Default to 2 years ago to cover most backfill scenarios
        since_date = (datetime.now().replace(year=datetime.now().year - 2)).strftime("%Y-01-01")

    transactions = ynab.get_transactions(budget_id, account_id=account_id, since_date=since_date)
    existing = {}

    for t in transactions:
        txn_info = {
            "transaction_id": t.transaction_id,
            "subtransactions": t.subtransactions,
        }
        if t.import_id:
            existing[t.import_id] = txn_info
        # Also reconstruct from memo for older transactions
        if t.memo and "Order " in t.memo:
            order_id = t.memo.split("Order ")[-1].split(":")[0].split(" ")[0].strip()
            # YNAB amounts are in milliunits (1000 per dollar)
            amount_cents = int(abs(t.amount) / 10)
            direction = "R" if t.amount > 0 else "P"
            existing[f"AMZ:{order_id}:{amount_cents}"] = txn_info
            existing[f"AMZ2:{order_id}:{amount_cents}"] = txn_info
            existing[f"AMZ2:{order_id}:{amount_cents}:{direction}"] = txn_info
            existing[f"AMZ3:{order_id}:{amount_cents}:{direction}"] = txn_info

    return existing


def sync_transactions(cache_file: Path, dry_run: bool = False):
    """Sync transactions from cache file to YNAB."""
    if not cache_file.exists():
        log(f"Cache file not found: {cache_file}")
        return

    # Load and validate cache file
    try:
        with open(cache_file, "r") as f:
            cache = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log(f"Error reading cache file: {e}")
        return

    transactions = cache.get("transactions", [])
    synced = set(cache.get("synced", []))

    log(f"Loaded {len(transactions)} transactions from cache")
    log(f"Already synced: {len(synced)}")

    # Validate environment
    ynab_token = os.getenv("YNAB_TOKEN")
    if not ynab_token:
        log("Error: YNAB_TOKEN not set in environment or .env file")
        log("  Get your token from: https://app.ynab.com/settings/developer")
        return

    budget_name = os.getenv("BUDGET_NAME")
    account_name = os.getenv("ACCOUNT_NAME")

    if not budget_name or not account_name:
        log("Error: BUDGET_NAME and ACCOUNT_NAME must be set in .env")
        return

    # Connect to YNAB
    log("\nConnecting to YNAB...")
    ynab = YNABClient(ynab_token)
    writer = YNABWriter(ynab)

    budget_id = ynab.get_budget_id(budget_name)
    if not budget_id:
        log(f"Budget '{budget_name}' not found")
        return

    account_id = ynab.get_account_id(budget_id, account_name)
    if not account_id:
        log(f"Account '{account_name}' not found")
        return

    log(f"Using account: {account_name}")

    # Get category mapping
    log("Loading categories...")
    cat_mapping = get_category_mapping(ynab, budget_id)
    log(f"Found {len(cat_mapping)} category mappings")

    # Get existing transactions for dedup and update
    log("Checking existing transactions...")
    existing_txns = get_existing_transactions(ynab, budget_id, account_id)
    log(f"Found {len(existing_txns)} existing transactions")

    stats = {"created": 0, "updated": 0, "skipped": 0, "duplicate": 0, "failed": 0}

    # First pass: collect transactions to create or update
    to_create = []  # List of (txn, ynab_data) tuples
    to_update = []  # List of (txn, transaction_id, subtransactions) tuples

    def build_subtransactions(txn, cat_mapping):
        """Build YNAB subtransactions from splits."""
        if not txn.get("splits"):
            return None

        subtransactions = []
        for split in txn["splits"]:
            cat_id = find_category_id(split["category"], cat_mapping)
            amount_milliunits = int(Decimal(str(split["amount"])) * 1000)
            subtransactions.append({
                "amount": amount_milliunits,
                "category_id": cat_id,
                "memo": split.get("memo", "")[:200],
            })

        # Fix rounding: YNAB requires subtransaction amounts to sum exactly to parent
        if subtransactions:
            parent_milliunits = int(Decimal(str(txn["amount"])) * 1000)
            subtransaction_sum = sum(s["amount"] for s in subtransactions)
            rounding_diff = parent_milliunits - subtransaction_sum
            if rounding_diff != 0:
                subtransactions[-1]["amount"] += rounding_diff

        return subtransactions

    def subtransactions_differ(local_subs, ynab_subs):
        """Check if subtransactions differ (need update)."""
        if not local_subs and not ynab_subs:
            return False
        if not local_subs or not ynab_subs:
            return True
        if len(local_subs) != len(ynab_subs):
            return True

        for local, remote in zip(local_subs, ynab_subs):
            # Compare memos (main thing that changes with qty prefix)
            if local.get("memo", "")[:50] != (remote.get("memo") or "")[:50]:
                return True
        return False

    # Calculate cutoff date (YNAB rejects transactions older than 5 years)
    now = datetime.now()
    cutoff_date = now.replace(year=now.year - 5).strftime("%Y-%m-%d")

    for txn in transactions:
        import_id = txn.get("import_id")
        if not import_id:
            log(f"Warning: Transaction missing import_id, skipping: {txn.get('order_id', 'unknown')}")
            continue

        # Skip transactions older than 5 years (YNAB limit)
        if txn.get("date", "") < cutoff_date:
            stats["skipped"] += 1
            continue

        # Skip if already synced locally (unless we need to check for updates)
        if import_id in synced and import_id not in existing_txns:
            stats["skipped"] += 1
            continue

        subtransactions = build_subtransactions(txn, cat_mapping)

        # Check if already in YNAB
        if import_id in existing_txns:
            existing = existing_txns[import_id]

            # Check if subtransactions differ - if so, queue for update
            if subtransactions and subtransactions_differ(subtransactions, existing["subtransactions"]):
                to_update.append((txn, existing["transaction_id"], subtransactions))
            else:
                if import_id not in synced:
                    log(f"[DUP] {txn.get('order_id', 'unknown')} - already in YNAB")
                    synced.add(import_id)
                    stats["duplicate"] += 1
                else:
                    stats["skipped"] += 1
            continue

        # Build YNAB transaction data for creation
        amount_milliunits = int(Decimal(str(txn["amount"])) * 1000)
        ynab_txn = {
            "account_id": account_id,
            "date": txn["date"],
            "amount": amount_milliunits,
            "payee_name": txn.get("payee", "Amazon.com"),
            "memo": txn.get("memo", "")[:200],
            "approved": False,
            "flag_color": txn.get("flag", "yellow"),
            "import_id": import_id,
        }
        if subtransactions:
            ynab_txn["subtransactions"] = subtransactions
        elif txn.get("category"):
            # Single category (e.g., grocery transactions without itemization)
            cat_id = find_category_id(txn["category"], cat_mapping)
            if cat_id:
                ynab_txn["category_id"] = cat_id

        to_create.append((txn, ynab_txn))
        log(f"{txn['date']} {txn['order_id']} ${abs(txn['amount']):.2f} {'(R)' if txn.get('is_refund') else '(P)'}")

    # Handle updates first
    if to_update:
        if dry_run:
            log(f"\n[DRY RUN] Would update {len(to_update)} transactions")
            stats["updated"] = len(to_update)
        else:
            log(f"\nUpdating {len(to_update)} transactions...")
            for txn, transaction_id, subtransactions in to_update:
                try:
                    writer.update_transaction(
                        budget_id=budget_id,
                        transaction_id=transaction_id,
                        subtransactions=subtransactions
                    )
                    stats["updated"] += 1
                    synced.add(txn["import_id"])
                    log(f"  [UPD] {txn['order_id']}")
                except Exception as e:
                    stats["failed"] += 1
                    log(f"  [FAILED] {txn['order_id']}: {e}")

    # Handle creates
    if not to_create:
        if not to_update:
            log("\nNo new transactions to sync.")
    elif dry_run:
        stats["created"] = len(to_create)
        log(f"\n[DRY RUN] Would create {len(to_create)} transactions")
    else:
        # Batch create transactions (YNAB supports up to 100 per call)
        batch_size = 50
        for i in range(0, len(to_create), batch_size):
            batch = to_create[i:i + batch_size]
            batch_data = [ynab_txn for _, ynab_txn in batch]

            log(f"\nCreating batch of {len(batch)} transactions...")

            try:
                result = writer.create_transactions_batch(budget_id, batch_data)

                # Process results - YNAB returns duplicate_import_ids for any duplicates
                duplicates = result.get("duplicate_import_ids", [])

                for txn, _ in batch:
                    import_id = txn["import_id"]
                    if import_id in duplicates:
                        stats["duplicate"] += 1
                        log(f"  [DUP] {txn['order_id']}")
                    else:
                        stats["created"] += 1
                        log(f"  [OK] {txn['order_id']}")
                    synced.add(import_id)

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    log(f"[RATE LIMIT] Waiting 60s and retrying...")
                    time.sleep(60)
                    try:
                        result = writer.create_transactions_batch(budget_id, batch_data)
                        for txn, _ in batch:
                            synced.add(txn["import_id"])
                            stats["created"] += 1
                    except Exception as e2:
                        log(f"[FAILED] Batch failed: {e2}")
                        stats["failed"] += len(batch)
                else:
                    log(f"[FAILED] Batch failed: {e}")
                    stats["failed"] += len(batch)

    # Save updated sync status
    from file_writer import save_cache
    cache["synced"] = list(synced)
    save_cache(cache_file, cache)

    log(f"\n{'='*50}")
    log(f"Created: {stats['created']}, Updated: {stats['updated']}, Duplicate: {stats['duplicate']}, Skipped: {stats['skipped']}, Failed: {stats['failed']}")
    if dry_run:
        log("(Dry run - no changes made)")


def sync_payments(year: int = None, dry_run: bool = False, checking_account: str = None):
    """Sync credit card payment transfers to YNAB.

    Reads from checking_amazon_transfers.csv and creates transfer transactions
    in the Amazon card account (inflows from checking).
    """
    payments_file = Path("data/checking_amazon_transfers.csv")
    if not payments_file.exists():
        log(f"Payments file not found: {payments_file}")
        log("Run: python extract_checking_payments.py to generate it")
        return

    # Validate environment
    ynab_token = os.getenv("YNAB_TOKEN")
    if not ynab_token:
        log("Error: YNAB_TOKEN not set")
        return

    budget_name = os.getenv("BUDGET_NAME")
    account_name = os.getenv("ACCOUNT_NAME")  # Amazon card

    if not budget_name or not account_name:
        log("Error: BUDGET_NAME and ACCOUNT_NAME must be set in .env")
        return

    # Connect to YNAB
    log("Connecting to YNAB...")
    ynab = YNABClient(ynab_token)
    writer = YNABWriter(ynab)

    budget_id = ynab.get_budget_id(budget_name)
    if not budget_id:
        log(f"Budget '{budget_name}' not found")
        return

    account_id = ynab.get_account_id(budget_id, account_name)
    if not account_id:
        log(f"Account '{account_name}' not found")
        return

    # Find checking account for transfer payee
    if not checking_account:
        checking_account = os.getenv("CHECKING_ACCOUNT_NAME")

    if not checking_account:
        # Try to find checking account by name pattern
        accounts = ynab.get_accounts(budget_id)
        for acc in accounts:
            name_lower = acc["name"].lower()
            if "checking" in name_lower and not acc.get("closed"):
                checking_account = acc["name"]
                break

    if not checking_account:
        log("Error: Could not find checking account. Set CHECKING_ACCOUNT_NAME in .env")
        log("Available accounts:")
        for acc in ynab.get_accounts(budget_id):
            if not acc.get("closed"):
                log(f"  - {acc['name']}")
        return

    log(f"Using Amazon card: {account_name}")
    log(f"Transfer payee: Transfer: {checking_account}")

    # Read payments from CSV
    payments = []
    with open(payments_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row["Date"]
            # Parse date (MM/DD/YYYY format)
            try:
                dt = datetime.strptime(date_str, "%m/%d/%Y")
            except ValueError:
                continue

            # Filter by year if specified
            if year and dt.year != year:
                continue

            # Get outflow amount (this is what left checking)
            outflow = row.get("Outflow", "").replace(",", "")
            if not outflow:
                continue

            try:
                amount = Decimal(outflow)
            except:
                continue

            payments.append({
                "date": dt.strftime("%Y-%m-%d"),
                "amount": amount,
                "memo": row.get("Memo", "Credit card payment"),
            })

    if not payments:
        log(f"No payments found{' for ' + str(year) if year else ''}")
        return

    log(f"Found {len(payments)} payment(s){' for ' + str(year) if year else ''}")

    # Get existing transactions to check for duplicates
    existing_ids = set()
    since_date = f"{year or 2020}-01-01"
    existing_txns = ynab.get_transactions(budget_id, account_id=account_id, since_date=since_date)
    for t in existing_txns:
        if t.import_id:
            existing_ids.add(t.import_id)

    # Build transactions for YNAB
    to_create = []
    stats = {"created": 0, "duplicate": 0, "failed": 0}

    for pmt in payments:
        # Import ID format: CCPAY:YYYYMMDD:amount_cents
        date_compact = pmt["date"].replace("-", "")
        amount_cents = int(pmt["amount"] * 100)
        import_id = f"CCPAY2:{date_compact}:{amount_cents}"

        if import_id in existing_ids:
            stats["duplicate"] += 1
            continue

        # Amount is positive (inflow to credit card reduces balance)
        amount_milliunits = int(pmt["amount"] * 1000)

        ynab_txn = {
            "account_id": account_id,
            "date": pmt["date"],
            "amount": amount_milliunits,
            "payee_name": f"Transfer: {checking_account}",
            "memo": pmt["memo"],
            "approved": False,
            "cleared": "cleared",
            "import_id": import_id,
        }
        to_create.append((pmt, ynab_txn))
        log(f"  {pmt['date']} ${pmt['amount']:.2f}")

    if not to_create:
        log(f"\nNo new payments to sync (found {stats['duplicate']} duplicates)")
        return

    if dry_run:
        log(f"\n[DRY RUN] Would create {len(to_create)} payment transfers")
        return

    # Create transactions
    log(f"\nCreating {len(to_create)} payment transfers...")
    batch_data = [ynab_txn for _, ynab_txn in to_create]

    try:
        result = writer.create_transactions_batch(budget_id, batch_data)
        duplicates = result.get("duplicate_import_ids", [])

        for pmt, ynab_txn in to_create:
            if ynab_txn["import_id"] in duplicates:
                stats["duplicate"] += 1
            else:
                stats["created"] += 1

    except Exception as e:
        log(f"Error creating payments: {e}")
        stats["failed"] = len(to_create)

    log(f"\nPayments: Created {stats['created']}, Duplicate {stats['duplicate']}, Failed {stats['failed']}")


def main():
    parser = argparse.ArgumentParser(description="Sync processed transactions to YNAB")
    parser.add_argument("cache_file", nargs="?", help="Cache file to sync (or 'all' for all files)")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview without creating")
    parser.add_argument("--list", "-l", action="store_true", help="List available cache files")
    parser.add_argument("--payments", "-p", action="store_true", help="Sync credit card payment transfers")
    parser.add_argument("--year", "-y", type=int, help="Filter by year (for --payments)")
    parser.add_argument("--checking-account", help="Checking account name for transfers")
    args = parser.parse_args()

    # Handle payment sync
    if args.payments:
        sync_payments(year=args.year, dry_run=args.dry_run, checking_account=args.checking_account)
        return

    if args.list or not args.cache_file:
        cache_dir = get_cache_dir()
        # Filter out category_cache.json which is used for AI categorization caching
        cache_files = sorted(f for f in cache_dir.glob("*.json") if f.name != "category_cache.json")

        if not cache_files:
            log(f"No cache files found in {cache_dir}")
            log("Run process_transactions.py first to create cache files.")
            return

        log("Available cache files:")
        for f in cache_files:
            try:
                with open(f, "r") as fp:
                    data = json.load(fp)
                total = len(data.get("transactions", []))
                synced = len(data.get("synced", []))
                pending = total - synced
                log(f"  {f.name}: {total} transactions, {synced} synced, {pending} pending")
            except (json.JSONDecodeError, IOError):
                log(f"  {f.name}: (error reading file)")
        return

    if args.cache_file == "all":
        for cache_file in sorted(f for f in get_cache_dir().glob("*.json") if f.name != "category_cache.json"):
            log(f"\n{'='*50}")
            log(f"Syncing {cache_file.name}")
            log(f"{'='*50}")
            sync_transactions(cache_file, args.dry_run)
    else:
        cache_file = Path(args.cache_file)
        if not cache_file.exists():
            cache_file = get_cache_dir() / args.cache_file
        if not cache_file.exists():
            cache_file = get_cache_dir() / f"{args.cache_file}.json"

        sync_transactions(cache_file, args.dry_run)


if __name__ == "__main__":
    main()
