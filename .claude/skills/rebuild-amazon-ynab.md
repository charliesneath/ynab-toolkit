# Skill: rebuild-amazon-ynab

Rebuild all YNAB transactions for an account from audit CSVs.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| Read audit CSVs | Auto-approved |
| YNAB API reads | One-time session approval |
| **Create YNAB transactions** | **Explicit approval per batch** |
| **Delete YNAB transactions** | **Explicit approval with reason** |

**YNAB writes are NEVER executed without presenting a detailed summary and receiving explicit "yes" approval.** For large rebuilds, approval is requested per month/batch.

## Instructions

1. **Run the rebuild script**
   ```bash
   python3 rebuild_ynab_from_audit.py
   ```

2. **Monitor progress**
   - Script processes each month from Feb 2021 to present
   - Shows created/skipped/error counts per month

3. **Handle rate limiting**
   - If Claude API rate limits occur, wait and retry
   - Can resume specific months with `--month YYYY-MM`

4. **Verify after completion**
   - Run `/reconcile-amazon` to check balance matches

## Options

```bash
# Full rebuild (all months)
python3 rebuild_ynab_from_audit.py

# Single month
python3 rebuild_ynab_from_audit.py --month 2025-01

# Dry run (no YNAB changes)
python3 rebuild_ynab_from_audit.py --dry-run
```

## Known Issues

The rebuild script may miss transactions when:

1. **Same order, multiple charges**: Split shipments generate multiple charges with the same order number but different transaction codes. The script deduplicates by order number, missing the second charge.

2. **Same day, same amount**: Two different merchants charging identical amounts on the same day may be deduplicated.

3. **Non-Amazon merchants**: Charges from JetBlue, medical providers, etc. on the Amazon card need manual categorization.

## After Rebuild

Always run `/reconcile-amazon` to verify the balance matches the actual account balance. If discrepancies exist, use `/sync-amazon-month` to fix specific months.

## Approval Flow

This skill **writes to YNAB**. Before executing, I will follow `/approval-flow`:

1. Show summary of transactions to be created
2. Wait for your explicit approval
3. Only execute after "yes"

For large rebuilds, I may batch by month and ask for approval per batch.

## Usage

```
/rebuild-amazon-ynab
```
