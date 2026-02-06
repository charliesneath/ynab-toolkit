# Skill: sync-amazon-month

Sync a single month's transactions from audit CSV to YNAB.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| Read audit CSV | Auto-approved |
| YNAB API reads | One-time session approval |
| **Create YNAB transactions** | **Explicit approval with full transaction list** |

**YNAB writes are NEVER executed without presenting a detailed summary and receiving explicit "yes" approval.**

## Arguments

- `YYYY-MM` - The month to sync (e.g., `2025-01`)
- Account name - Which account to sync (look up IDs from CLAUDE.md)

## Instructions

1. **Load the audit CSV** for the specified month
   - Path: `data/processed/{account}/audit/YYYY-MM-mon.csv`

2. **Get existing YNAB transactions** for that month
   - Look up Budget ID and Account ID from CLAUDE.md

3. **Compare and find missing transactions**
   - Build frequency map of (date, amount) pairs for both sources
   - Identify transactions in audit but not in YNAB
   - Skip "Points Redemption" transactions

4. **Present changes for approval** (following `/approval-flow`)
   - Show all missing transactions to be added
   - Wait for explicit "yes" before proceeding

5. **Add approved transactions to YNAB**
   - Use appropriate payee names
   - Set flag_color to "blue"
   - Set approved to False for review
   - Use unique import_id based on transaction code: `AMZ2:{tx_code}:{amount_cents}:{type}`

5. **Report results**
   - Transactions found in audit
   - Transactions already in YNAB
   - Transactions added
   - New balance

## Usage

```
/sync-amazon-month 2025-01
```

## Example Output

```
Syncing January 2025...

Audit CSV: 15 transactions (excl. Points Redemption)
YNAB: 14 transactions

Missing from YNAB:
  2025-01-15: $-42.99 - Amazon.com*XY1234

Adding 1 transaction...
  Added: 2025-01-15 $-42.99 - Amazon.com

Summary:
  Before: $1,457.01
  Added:  $-42.99
  After:  $1,500.00 ✓
```

## Sign Conventions

- Purchases/Tips/Digital: Negative (increases debt)
- Payments: Positive (reduces debt)
- Refunds: Positive (reduces debt)
