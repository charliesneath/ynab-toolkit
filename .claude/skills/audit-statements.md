# Skill: audit-statements

Parse bank statement PDFs and generate audit CSVs for reconciliation.

## Permission Model

| Operation | Approval Required |
|-----------|-------------------|
| Read PDF statements | Auto-approved |
| **Create/overwrite CSV files** | **Explicit approval with file list** |

**File writes are NEVER executed without presenting a summary and receiving explicit "yes" approval.**

## Instructions

1. **Run the audit script**
   ```bash
   python3 audit_statements.py
   ```

2. **Verify output**
   - Check that CSVs were generated in `data/processed/{account}/audit/`
   - Verify each month has a CSV file (format: `YYYY-MM-mon.csv`)

3. **Check for parsing errors**
   - Look for any warnings about unrecognized transaction patterns
   - Verify totals match statement closing balances

4. **Report summary**
   - Number of statements processed
   - Number of transactions extracted
   - Any errors or warnings

## Data Locations

| Type | Path |
|------|------|
| Statement PDFs | `data/{account}/statements/` or `data/statements/` |
| Output CSVs | `data/processed/{account}/audit/` |

## CSV Output Format

```csv
Date,Type,Amount,Order Number,Transaction Code,Description,Merchant,Statement Source
```

Each row represents one transaction extracted from a statement PDF.

## Transaction Types

- **Purchase**: Regular Amazon or other merchant purchases
- **Digital**: Digital content (Prime Video, Kindle, etc.)
- **Tip**: Amazon delivery tips
- **Refund**: Returns/refunds (negative amount)
- **Payment**: Card payments (negative amount)
- **Points Redemption**: Shop with Points (excluded from YNAB)
- **Fee**: Late fees, return payment fees
- **Interest**: Interest charges

## Approval Flow

This skill **writes files** (CSV outputs). Before running, I will follow `/approval-flow`:

1. Confirm which statements will be processed
2. Show expected output files
3. Wait for your explicit approval

## Usage

```
/audit-statements
```

Or to re-audit a specific date range:
```
/audit-statements 2025-01 2025-12
```
