# Credit Card Payment Processing (TODO)

## Goal
Process credit card bill payments ("Payment Thank You" transactions) so they can be added to YNAB as transfers from Checking → Amazon Credit Card.

## Background
When rebuilding Amazon transaction history, we need to account for:
1. **Purchases** (outflows) - handled by `process_transactions.py`
2. **Refunds** (inflows with Order ID) - handled by `process_transactions.py`
3. **Credit card payments** (inflows without Order ID) - **NOT YET HANDLED**

## Data Format
From YNAB export, payment transactions look like:
```
Date,Payee,Memo,Outflow,Inflow
01/19/2024,Payment Thank You - Web,,1343.95
02/22/2024,Payment Thank You - Web,,1436.66
03/10/2024,Payment Thank You - Web,,500.00
```

## Proposed Script: `process_payments.py`

### Input
- YNAB export CSV with Amazon credit card transactions

### Output
- CSV/JSON with transfer transactions:
  - Date
  - Amount
  - From: Checking Account
  - To: Amazon Credit Card
  - Memo: "Credit Card Payment"

### Logic
1. Filter transactions where Payee contains "Payment Thank You"
2. Extract Date and Inflow amount
3. Generate transfer records for YNAB import

## Status
- [ ] Create `process_payments.py` script
- [ ] Test with 2024 data
- [ ] Import to YNAB
