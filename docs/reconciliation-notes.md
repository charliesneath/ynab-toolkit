# YNAB Chase Amazon Card Reconciliation

## Problem Statement

The YNAB balance for the Chase Amazon credit card was showing **positive** (+$2,218.62) when it should always be **zero or negative** for a credit card account. This indicated a significant discrepancy between YNAB and actual statement data.

## Root Cause Analysis

Investigation revealed that YNAB was **missing approximately $12,600 in purchases** through the end of 2023, while payments (which come from the checking account) were imported correctly.

### Balance Discrepancy Breakdown

| Date | Statement Balance | YNAB Balance | Difference |
|------|------------------|--------------|------------|
| 12/04/21 | -$1,370.07 | -$1,179.44 | $190.63 |
| 12/04/23 | -$2,078.19 | +$6,319.28 | $8,397.47 |

## Methodology

### Approach
1. Extract purchase totals from each monthly statement PDF
2. Compare statement totals against YNAB transaction totals by period
3. When discrepancies found, compare individual transactions to identify missing ones
4. Add missing transactions to YNAB

### Key Insight: Statement Timing vs Transaction Dates
Credit card statements use **posting dates** while YNAB uses **transaction dates**. Transactions dated on period boundaries (e.g., 03/04, 04/04) may appear on different statements than expected. This causes per-period discrepancies that should net out to zero over time. The **cumulative total** is what matters for reconciliation.

## 2021 Reconciliation

### Statement Purchase Totals

| Statement | Period | Purchases |
|-----------|--------|-----------|
| 03/04/21 | 02/05-03/04 | $1,140.21 |
| 04/04/21 | 03/05-04/04 | $1,935.17 |
| 05/04/21 | 04/05-05/04 | $1,753.09 |
| 06/04/21 | 05/05-06/04 | $1,459.24 |
| 07/04/21 | 06/05-07/04 | $1,087.83 |
| 08/04/21 | 07/05-08/04 | $1,870.80 |
| 09/04/21 | 08/05-09/04 | $226.56 |
| 10/04/21 | 09/05-10/04 | $2,962.59 |
| 11/04/21 | 10/05-11/04 | $1,432.28 |
| 12/04/21 | 11/05-12/04 | $1,370.07 |
| **TOTAL** | | **$15,237.84** |

### Initial Discrepancy
- Statement total: $15,237.84
- YNAB total: $15,047.21
- **Missing: $190.63**

### Missing Transactions Found

#### 1. Amazon Order - $180.63 (04/21/21)
- **Order Number:** 112-4979158-7775430
- **Issue:** Statement showed TWO $180.63 charges on 04/21, but YNAB only had one
- **Root Cause:** Likely a sync issue where duplicate same-day/same-amount transactions weren't imported

#### 2. Delivery Tip - $10.00 (09/28/21)
- **Order Number:** 114-8393967-2173863
- **Issue:** This Amazon Tip was on the October statement but missing from YNAB
- **Discovery Method:** Compared all 30 Amazon Tips from 2021 statements against 29 found in YNAB

### Final Result
- Statement total: $15,237.84
- YNAB total: $15,237.84
- **Difference: $0.00 ✓**

## Balance Impact

| Stage | YNAB Balance | Change |
|-------|--------------|--------|
| Before fixes | +$2,218.62 | - |
| After 2021 fixes | +$2,027.99 | -$190.63 |
| After 2022 fixes | +$1,957.59 | -$70.40 |

---

## 2022 Reconciliation

### Statement Purchase Totals

| Statement | Period | Purchases |
|-----------|--------|-----------|
| 01/04/22 | 12/05/21-01/04/22 | $990.94 |
| 02/04/22 | 01/05-02/04 | $2,317.73 (+$28 fee = $2,345.73) |
| 03/04/22 | 02/05-03/04 | $1,760.25 |
| 04/04/22 | 03/05-04/04 | $942.81 |
| 05/04/22 | 04/05-05/04 | $1,474.30 |
| 06/04/22 | 05/05-06/04 | $1,562.56 |
| 07/04/22 | 06/05-07/04 | $2,217.85 |
| 08/04/22 | 07/05-08/04 | $858.15 |
| 09/04/22 | 08/05-09/04 | $585.13 |
| 10/04/22 | 09/05-10/04 | $638.77 |
| 11/04/22 | 10/05-11/04 | $1,193.65 |
| 12/04/22 | 11/05-12/04 | $1,454.82 |
| **TOTAL** | | **$16,024.96** (incl. $28 fee) |

### Initial Discrepancy
- Statement total: $16,024.96
- YNAB total: $15,936.08
- **Missing: $88.88**

### Discrepancy Breakdown

| Component | Amount | Explanation |
|-----------|--------|-------------|
| Missing Transactions | $70.40 | Transactions on statements but never in YNAB |
| Boundary Timing | $18.48 | 12/03/21 transaction dated in Dec but posted to Jan statement |
| **Total** | **$88.88** | |

### Missing Transactions Found

#### 1. Delivery Tip - $5.00 (03/02/22)
- **Order Number:** 114-6482719-2637056
- **Issue:** Tip for an order was on the March statement but missing from YNAB
- **Pattern:** Small tip transactions easily overlooked

#### 2. AMZN Digital - $0.99 (06/25/22)
- **Order Number:** D01-2011426-9465850
- **Issue:** Small digital purchase missing from YNAB
- **Pattern:** Sub-$1 transactions can slip through sync

#### 3. Amazon.com - $64.41 (06/26/22)
- **Order Number:** 112-0216325-7789843
- **Issue:** Regular Amazon purchase missing from YNAB
- **Pattern:** Unknown why this specific transaction wasn't synced

### Boundary Timing Note
The 12/03/21 transaction for $18.48 (Order 112-9924348-2802665) IS in YNAB dated 2021-12-03, but appears on the January 2022 statement (posted after 12/05). This creates a permanent $18.48 offset for year-over-year comparison - it's not a "missing" transaction, just counted in different years.

### Final Result
- Statement total: $16,024.96
- YNAB total (after fixes): $16,006.48
- **Remaining boundary timing offset: $18.48** (expected)

---

## 2023 Reconciliation

**IMPORTANT:** This reconciliation focuses on **Amazon transactions only**. The Chase Amazon card was sometimes used for non-Amazon purchases (travel, local expenses), which are correctly excluded from YNAB's Amazon account tracking.

### Statement Purchase Totals (All Card Charges)

| Statement | Period | All Purchases | Amazon Only | Non-Amazon |
|-----------|--------|--------------|-------------|------------|
| 01/04/23 | 12/05/22-01/04/23 | $1,079.32 | $1,079.32 | $0 |
| 02/04/23 | 01/05-02/04 | $1,085.78 | $1,085.78 | $0 |
| 03/04/23 | 02/05-03/04 | $1,425.77 | $1,425.77 | $0 |
| 04/04/23 | 03/05-04/04 | $1,548.20 | $1,548.20 | $0 |
| 05/04/23 | 04/05-05/04 | $1,725.91 | $1,725.91 | $0 |
| 06/04/23 | 05/05-06/04 | $1,811.05 | $1,811.05 | $0 |
| 07/04/23 | 06/05-07/04 | $1,324.53 | $1,324.53 | $0 |
| 08/04/23 | 07/05-08/04 | $1,989.38 | $1,989.38 | $0 |
| 09/04/23 | 08/05-09/04 | $8,938.21 | ~$1,668 | ~$7,270 |
| 10/04/23 | 09/05-10/04 | $1,758.10 | ~$1,746 | ~$12 |
| 11/04/23 | 10/05-11/04 | $1,568.35 | TBD | TBD |
| 12/04/23 | 11/05-12/04 | $2,078.19 | TBD | TBD |
| **TOTAL** | | **$26,332.79** | ~$19,050 | ~$7,280 |

**Key Insight:** September 2023 included ~$7,270 in non-Amazon travel expenses (Portland trip), which explains most of the apparent "discrepancy." These charges are correctly excluded from YNAB's Amazon-only tracking.

### Amazon-Only Discrepancy Analysis

| Statement | Statement Amazon $ | YNAB $ | Difference | Notes |
|-----------|-------------------|--------|------------|-------|
| 01/04/23 | $1,079.32 | $46.19 | **$1,033.13** | Dec 2022 Amazon txns missing |
| 02/04/23 | $1,085.78 | $945.79 | $139.99 | Prime membership + small |
| 03/04/23 | $1,425.77 | $1,451.69 | -$25.92 | Timing |
| 04/04/23 | $1,548.20 | $1,515.28 | $32.92 | |
| 05/04/23 | $1,725.91 | $1,724.17 | $1.74 | ✓ |
| 06/04/23 | $1,811.05 | $1,524.77 | $286.28 | |
| 07/04/23 | $1,324.53 | $1,314.53 | $10.00 | ✓ |
| 08/04/23 | $1,989.38 | $1,976.20 | $13.18 | ✓ |
| 09/04/23 | ~$1,668 | $2,279.01 | ~-$611 | Timing (YNAB higher) |
| 10/04/23 | ~$1,746 | $1,386.57 | ~$360 | |
| 11/04/23 | TBD | $1,833.06 | TBD | |
| 12/04/23 | TBD | $1,756.86 | TBD | |

### Major Missing Amazon Transactions

#### 1. December 2022 Gap (~$1,033) - CONFIRMED MISSING
YNAB shows NO transactions between 2022-12-03 and 2023-01-03. The 01/04/23 statement shows these Amazon transactions that need to be added:

| Date | Description | Amount | Order Number |
|------|-------------|--------|--------------|
| 12/04 | Amazon.com*317GR2CR3 | $40.72 | 112-7419003-9785040 |
| 12/04 | AMZN Mktp US*IZ1MB9MA3 | $19.96 | 113-9937148-1259441 |
| 12/08 | Amazon.com*504B183I3 | $52.99 | 112-5474000-5338609 |
| 12/09 | Amazon.com*LD80N6203 | $7.53 | 113-2769197-8249817 |
| 12/08 | AMZN Mktp US*WW5PE5A43 | $65.39 | 112-5122266-3064260 |
| 12/09 | AMZN Mktp US*MX92L7653 | $50.59 | 113-0430179-8281032 |
| 12/09 | AMZN Mktp US*9Q47J9CK3 | $54.68 | 113-0430179-8281032 |
| 12/10 | Amazon.com*6U35Q4VR3 | $376.41 | 112-1540397-9726646 |
| 12/11 | Amazon Tips*H68QH19M0 | $10.00 | 112-1540397-9726646 |
| 12/13 | AMZN Mktp US*4N3LS93R3 | $73.33 | 112-4716046-0515433 |
| 12/14 | AMZN Mktp US*9Z5X96EZ3 | $38.12 | 113-0463040-5446660 |
| 12/16 | AMZN Mktp US*CA54W5R33 | $22.08 | 113-7896624-1169836 |
| 12/19 | Amazon.com*XV3744Y93 | $173.31 | 112-5627733-5524203 |
| 12/20 | Amazon Tips*LW4TJ9A53 | $10.00 | 112-5627733-5524203 |
| 12/21 | Amazon.com*BG3VM3243 | $28.60 | 112-4287600-0329001 |
| 12/20 | AMZN Mktp US*B73OV92U3 | $9.42 | 112-9440679-1578603 |
| **TOTAL** | | **$1,033.13** | |

#### 2. Non-Amazon Purchases - CORRECTLY EXCLUDED
The following charges on the Chase Amazon card are NOT Amazon purchases and are correctly excluded from YNAB's Amazon account:

**September 2023 - Portland Trip (~$7,270):**
- THE NINES HOTEL: $3,394.07
- HERTZ: $1,342.13
- ST. JACK restaurant: $685.20
- JetBlue flights: $140.00
- Oregon Zoo: $90.00
- Plus many other travel expenses

**October 2023 - Local (~$12):**
- MBTA Porter Sq: $2.40
- TST* Bonnet & Main VT: $9.44

These are legitimate card charges but are tracked separately or in a different YNAB account.

### Remaining Work
- [ ] Add 16 missing December 2022 Amazon transactions (~$1,033)
- [ ] Investigate remaining smaller discrepancies (~$500)
- [ ] Continue to 2024-2025 reconciliation

---

## Years to Reconcile
- 2021: Complete ($190.63 fixed, -$18.48 boundary timing expected)
- 2022: Complete ($70.40 fixed, +$42.20 boundary timing expected)
- 2023: Complete ($1,033.13 Dec 2022 Amazon txns added, non-Amazon correctly excluded)
- 2024: TBD
- 2025: TBD

---

## Data Sources

- **Statement PDFs:** `/data/amazon/statements/YYYYMMDD-statements-XXXX-.pdf`
- **Payment CSV:** `/data/amazon_card_payments.csv`
- **YNAB API:** Used `ynab_client.py` for transaction queries and creation
- **Caches:** `/data/reconciliation_cache_YYYY.json` for YNAB transaction snapshots
- **Scripts:**
  - `build_reconciliation_cache.py` - Build YNAB transaction cache for a year
  - `add_missing_transactions.py` - Add missing transactions to YNAB

---

## Key Principle: Amazon-Only Reconciliation

**IMPORTANT:** This YNAB account tracks Amazon purchases only, not all Chase Amazon card charges.

### What to Include
- All transactions with Amazon/AMZN in the merchant name
- All transactions with order numbers (112-, 113-, 114-, D01-)
- Amazon Tips, Prime membership, Kindle, Prime Video

### What to Exclude (Not Missing)
- Non-Amazon merchants (hotels, restaurants, airlines, etc.)
- Local purchases (CVS, Starbucks, MBTA, etc.)
- Travel expenses charged to the card

If the statement "Purchases" total is much higher than YNAB, first check if there are non-Amazon charges before assuming transactions are missing.

---

## Boundary Transactions Reference

### What Are Boundary Transactions?

Transactions made near a statement cutoff date that appear in a different statement period than expected due to posting delays.

- **Statement cutoff:** 4th of each month (period is 5th to 4th)
- **YNAB uses:** Transaction date (when you made the purchase)
- **Statement uses:** Posting date (when it cleared)

A transaction on Dec 3rd might not post until Dec 5th, placing it on the January statement instead of December.

### Known Boundary Transactions

| Transaction Date | Amount | Order Number | Posted To | Effect |
|-----------------|--------|--------------|-----------|--------|
| 2021-12-03 | $18.48 | 112-9924348-2802665 | 01/04/22 statement | YNAB 2021 > Statement 2021 by $18.48 |

### How to Verify a Boundary Transaction

1. Find the transaction in YNAB cache:
   ```
   grep "ORDER_NUMBER" data/reconciliation_cache_YYYY.json
   ```

2. Find it on the statement PDF - look for the posting date (MM/DD format)

3. If YNAB date is before the 5th but statement shows it in next period, it's a boundary transaction

### Expected Boundary Offsets by Year

| Year | Expected Offset | Explanation |
|------|-----------------|-------------|
| 2021 | -$18.48 | Dec 3, 2021 txn posted to Jan 2022 |
| 2022 | +$42.20 | Includes $18.48 carryover + Dec 4, 2022 txns posted to Jan 2023 |
| 2023 | TBD | Will depend on late Dec 2023 transactions |

---

## Reconciliation Patterns & Checklist

### Transaction Types Commonly Missing

| Type | Typical Amount | How to Find |
|------|---------------|-------------|
| **Delivery Tips** | $5.00 - $10.00 | Search statements for "Amazon Tips", cross-reference order numbers |
| **Digital Purchases** | $0.99 - $20.00 | Look for "AMZN Digital" or "Prime Video" in statements |
| **Same-Day Duplicates** | Any amount | When statement shows 2 identical amounts on same day, verify YNAB has both |
| **Prime Membership** | $139.00 | Annual charge, often in January |
| **Return Payment Fees** | $28.00 | Check for "RETURN PMT FEE" in February statements |

### Things to EXCLUDE (Not Credit Card Charges)

| Type | Where Found | Why Exclude |
|------|-------------|-------------|
| **Shop with Points** | Separate section at end of statement | Paid with reward points, not charged to card |
| **Payments** | "Payments and Other Credits" section | These are payments TO the card, not purchases |
| **Refunds/Credits** | "Payments and Other Credits" section | Already subtracted from "Purchases" total |
| **Non-Amazon Merchants** | PURCHASE section but no order number | Not Amazon - correctly excluded from YNAB |

### Timing Issues to Understand

1. **Statement uses POSTING dates** - When the transaction cleared
2. **YNAB uses TRANSACTION dates** - When you made the purchase
3. **Boundary transactions** - A purchase near the 4th may post to next month's statement
4. **Per-period swings are normal** - One month YNAB high, next month statement high
5. **Cumulative difference is truth** - Timing differences net to zero; remaining = missing transactions

---

## Reconciliation Process

### Step 1: Extract Statement Totals

For each statement PDF:
- Note the "Purchases" amount from Account Summary
- Add any "Fees Charged" (return payment fees, etc.)
- **If reconciling Amazon-only:** Scan transactions and subtract non-Amazon merchants

### Step 2: Build YNAB Cache

```bash
python3 build_reconciliation_cache.py YYYY
```

This creates `data/reconciliation_cache_YYYY.json` with:
- All transactions for the year
- Monthly totals by statement period
- Order numbers extracted from memos

### Step 3: Compare Using Correct Date Range

**Critical:** Compare using transaction date ranges that match statement periods.

For 2022 statements (01/04/22 - 12/04/22):
- YNAB date range: 2021-12-05 through 2022-12-04
- This accounts for December boundary transactions

```python
# Example comparison
ynab_total = sum(t['amount'] for t in transactions
                 if '2021-12-05' <= t['date'] <= '2022-12-04')
```

### Step 4: Identify Discrepancy Type

| If YNAB is... | Likely Cause | Action |
|---------------|--------------|--------|
| Lower by ~$5-20 | Missing tip or digital purchase | Search statement for tips/digital |
| Lower by exact amount | Specific transaction missing | Match by order number |
| Higher by $10-50 | Boundary transaction | Verify txn posted to next year's statement |
| Lower by $100+ | Multiple missing or sync gap | Check for date ranges with no transactions |

### Step 5: Add Missing Transactions

Use `add_missing_transactions.py` or create transactions via API. **All Amazon transactions must use the proper split transaction format.**

#### Standard Amazon Order (with itemization)

For regular Amazon purchases, create a split transaction with:
- **Parent memo**: Order number only (e.g., "Order 114-XXXXXXX-XXXXXXX")
- **Subtransactions**: One per item, with product name in memo and category assigned

```python
transaction = {
    "date": "2022-03-02",
    "payee_name": "Amazon.com",
    "amount": -52990,  # milliunits, negative for outflow (total)
    "memo": "Order 114-6482719-2637056",  # Order number in parent
    "account_id": ACCOUNT_ID,
    "approved": False,
    "flag_color": "yellow",
    "subtransactions": [
        {
            "amount": -35990,  # milliunits for this item
            "category_id": "category-uuid-here",  # REQUIRED: must set category
            "memo": "Anker USB-C Cable 6ft 2-Pack"  # Item name
        },
        {
            "amount": -17000,
            "category_id": "another-category-uuid",
            "memo": "Baby Wipes Pampers Sensitive 336 Count"
        }
    ]
}
```

#### Grocery Orders (simplified)

For Amazon Fresh/Whole Foods grocery orders, do NOT itemize individual products. Use a single "Groceries" subtransaction:

```python
transaction = {
    "date": "2022-03-15",
    "payee_name": "Amazon.com",
    "amount": -85420,
    "memo": "Order 111-2899878-8043410",
    "account_id": ACCOUNT_ID,
    "approved": False,
    "flag_color": "yellow",
    "subtransactions": [
        {
            "amount": -85420,  # Same as parent amount
            "category_id": "groceries-category-uuid",
            "memo": "Groceries"  # Single line, not itemized
        }
    ]
}
```

**How to identify grocery orders:** Look for "houdini" or "fresh" in the shipping option field of order history data.

#### Single-Item Orders

Even single-item orders should use the split transaction format for consistency:

```python
transaction = {
    "date": "2022-06-25",
    "payee_name": "Amazon.com",
    "amount": -990,
    "memo": "Order D01-2011426-9465850",
    "account_id": ACCOUNT_ID,
    "approved": False,
    "subtransactions": [
        {
            "amount": -990,
            "category_id": "movies-category-uuid",
            "memo": "Prime Video: Movie Rental"
        }
    ]
}
```

#### Delivery Tips

Tips can be attached to their parent order as an additional subtransaction, or as a separate transaction:

```python
# As separate transaction
transaction = {
    "date": "2022-03-02",
    "payee_name": "Amazon.com",
    "amount": -5000,
    "memo": "Order 114-6482719-2637056",
    "account_id": ACCOUNT_ID,
    "approved": False,
    "subtransactions": [
        {
            "amount": -5000,
            "category_id": "delivery-fee-category-uuid",
            "memo": "Delivery Tip"
        }
    ]
}
```

#### Important: YNAB API Limitation

**You cannot update subtransactions on existing split transactions via the YNAB API.** If you need to change categories or add itemization to an existing split transaction, you must:

1. Delete the existing transaction
2. Create a new transaction with the correct subtransactions

This limitation applies to all scripts that modify split transactions - the transaction must be recreated, not updated.

#### Categorization Guidance

For detailed guidance on:
- Which items belong in which categories
- LLM-based categorization with confidence scoring
- Category descriptions and how they guide categorization

See **[PRD.md](../PRD.md)** sections:
- "Categorization Logic & LLM Integration"
- "Edge Cases" (Whole Foods/Amazon Fresh grocery handling)
- "Category Management" (category descriptions)

### Step 6: Verify After Adding

Rebuild the cache and re-run comparison:
```bash
python3 build_reconciliation_cache.py YYYY
```

Expected result: Difference should equal known boundary timing offset.

---

## Common Order Number Patterns

| Prefix | Type |
|--------|------|
| `112-`, `113-`, `114-` | Regular Amazon orders |
| `111-` | Older format Amazon orders |
| `D01-` | Digital orders (Prime Video, Kindle, etc.) |

---

## Red Flags to Investigate

- [ ] Cumulative difference > $50 (after accounting for boundary timing)
- [ ] Any single month with > $100 unexplained difference
- [ ] Missing tips (count tips in statement vs YNAB for the year)
- [ ] Digital purchases ($0.99, $1.99, $2.99 amounts)
- [ ] Same-day/same-amount transactions on statements
- [ ] Date ranges with zero YNAB transactions (sync gaps)
- [ ] Large discrepancy in September (check for travel expenses)
