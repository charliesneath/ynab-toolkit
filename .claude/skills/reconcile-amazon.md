# Skill: reconcile-amazon

Reconcile a credit card account balance between YNAB and audit CSVs.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| Read local files (CSVs, cache) | Auto-approved |
| YNAB API reads | One-time session approval |
| **YNAB writes** | **Explicit approval (use /ynab-write)** |

**This skill is READ-ONLY.** If fixes are needed, use `/ynab-write` for corrections.

## Instructions

1. **Get current YNAB balance** for the account
   - Look up Budget ID and Account ID from CLAUDE.md

2. **Calculate expected balance from audit CSVs**
   - Load all CSVs from `data/processed/chase-amazon/audit/`
   - Sum all transactions EXCEPT "Points Redemption" type
   - Account for sign conventions:
     - Purchases, Tips, Digital, Donations → negative (increases debt)
     - Payments → positive (reduces debt) - amount in CSV is already negative
     - Refunds → positive (reduces debt)
   - Add the starting balance (check the Feb 2021 opening balance transaction)

3. **Compare balances**
   - If difference > $0.01, investigate

4. **Find missing transactions** (if discrepancy exists)
   - For each month, compare transaction counts by (date, amount) pairs
   - Identify transactions in audit CSV but not in YNAB
   - Common issues:
     - Same order number with multiple charges (split shipments)
     - Same-day, same-amount transactions from different merchants

5. **Report findings**
   - Show current YNAB balance
   - Show calculated audit balance
   - Show difference
   - List any missing transactions with details

## Approval Flow

This skill performs **read-only** operations (comparing balances). No approval needed.

If discrepancies are found and you ask me to fix them, I will follow the `/approval-flow` workflow:
- Batch all proposed YNAB changes
- Present summary for your approval
- Only execute after explicit "yes"

## Usage

```
/reconcile-amazon
```

## Example Output

```
Chase Amazon Reconciliation
===========================
YNAB Balance:    $1,500.00 (debt)
Audit Balance:   $1,500.00 (debt)
Difference:      $0.00 ✓

Status: RECONCILED
```
