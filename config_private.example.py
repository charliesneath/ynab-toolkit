"""
Private configuration template.

Copy this file to config_private.py and fill in your values.
config_private.py is gitignored and will not be committed.
"""

# YNAB Account IDs
# Find these in YNAB URL: app.ynab.com/{budget_id}/accounts/{account_id}
YNAB_BUDGET_ID = "your-budget-uuid-here"
YNAB_ACCOUNTS = {
    "checking": "your-checking-account-uuid",
    "credit_card": "your-credit-card-account-uuid",
    "savings": "your-savings-account-uuid",
}

# Card identifiers (last 4 digits used in statement filenames)
CARD_IDENTIFIERS = {
    "credit_card": "0000",  # Last 4 of credit card
    "checking": "0000",     # Last 4 of checking account
}

# Email configuration (for automated processing)
RECEIPTS_EMAIL = "your-receipts-email@example.com"

# Statement filename patterns
# Format: YYYYMMDD-statements-{card_id}-.pdf
STATEMENT_PATTERNS = {
    "credit_card": r"\d{8}-statements-{card_id}-\.pdf",
    "checking": r"\d{8}-statements-{card_id}-\.pdf",
}
