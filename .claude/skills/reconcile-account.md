# Skill: reconcile-account

Reconcile a bank account balance between YNAB and statement audit CSVs.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| Read local files (CSVs, cache) | Auto-approved |
| YNAB API reads | One-time session approval via AskUserQuestion |
| **YNAB writes** | **Explicit approval with detailed summary** |
| **File writes** | **Explicit approval with detailed summary** |

**Write operations are NEVER executed without presenting a clear summary and receiving explicit "yes" approval.**

## Instructions

1. **Identify the account to reconcile**
   - User specifies which account (checking, credit card, savings, etc.)
   - Look up account ID from CLAUDE.md or project config

2. **Find latest audit CSV**
   - Location: `data/processed/{account-name}/audit/`
   - Get the most recent file by date

3. **Request YNAB API access** (one-time per session)
   - Use AskUserQuestion to request read permission
   - Explain what data will be fetched
   - Proceed only after approval

4. **Fetch and compare data**
   - Load statement transactions from audit CSV
   - Fetch YNAB transactions for the account
   - Match by (date ±5 days, amount)
   - Calculate balance difference

5. **Report findings**
   ```
   RECONCILIATION SUMMARY
   ======================
   Account: [name]
   Statement Date: [date]

   Statement Balance: $X,XXX.XX
   YNAB Balance:      $X,XXX.XX
   Difference:        $X.XX

   Status: RECONCILED | DISCREPANCY FOUND
   ```

6. **If fixes needed** → Use `/ynab-write` workflow
   - Collect all proposed changes
   - Present detailed summary
   - Wait for explicit approval before executing

## Usage

```
/reconcile-account [account-name]
```
