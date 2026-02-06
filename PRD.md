# Amazon-YNAB Auto-Categorization Agent - Product Requirements Document

## Overview
An automated system that reconciles Amazon order details with YNAB transactions, automatically splitting and categorizing purchases based on actual items ordered. The system learns from user corrections and provides daily email summaries of categorization decisions.

## Problem Statement
Amazon transactions appear in YNAB as single line items with just a total amount and "Amazon" as the payee. To categorize them correctly, users must manually cross-reference their Amazon order history to see what items were actually purchased, then split the YNAB transaction across appropriate budget categories.

YNAB's default auto-categorization assigns categories based on the most recent transaction from that payee. Since Amazon sells everything, this means a grocery order might be auto-categorized as "Electronics" or vice versa, requiring manual correction every time.

**Current Manual Process:**
1. See uncategorized Amazon transaction in YNAB ($87.42)
2. Go to Amazon order history
3. Find the matching order by amount and date
4. Review items in that order
5. Return to YNAB and create split transaction
6. Assign each item/group to appropriate category
7. Repeat for every Amazon transaction

**This project automates steps 2-6.**

## Core Features

### 1. Transaction Reconciliation & Categorization
**User Story:** As a YNAB user, I want the system to automatically match my YNAB Amazon transactions with Amazon order details and categorize them based on what I actually bought.

**Functionality:**
- Fetches unapproved Amazon transactions from YNAB (all unlabeled transactions are unapproved)
- Retrieves Amazon order history with item-level details
- **Matches YNAB transactions to Amazon orders by:**
  - Transaction amount (exact match)
  - Transaction date (within reasonable window)
  - Merchant name (Amazon.com, Amazon Fresh, Whole Foods, etc.)
- For each matched order:
  - Retrieves all items in the order
  - Groups items by category based on category descriptions and learned patterns
  - Creates split transaction in YNAB with line items
  - Adds memo with summary details
  - Applies user-selected flag/label color to indicate agent processed it
  - Marks transaction as approved
- Handles unmatched transactions (flags for manual review)

**Matching Logic:**
- **Exact amount match**: YNAB shows $87.42, Amazon order totals $87.42 → match
- **Multiple orders same day**: If two Amazon orders on same day with same amount, use timestamp proximity or flag for manual review
- **Pending vs. posted**: Handle cases where YNAB shows pending amount that may later update (especially for Whole Foods)

**Edge Cases:**
- **Whole Foods/Amazon Fresh grocery orders:**
  - Should be categorized as a single "Groceries" line item with total amount
  - DO NOT itemize individual grocery items (bananas, chicken, etc.)
  - Final amount may differ from initial charge due to substitutions/unavailable items
  - Match initial pending transaction
  - Update when final amount posts
  - Note any discrepancy in memo
- **Amazon.com mixed orders** spanning multiple categories (e.g., books + electronics + household items):
  - DO split these into separate category line items
  - Group similar items together (e.g., all household items on one line)
- Gift purchases that should be categorized differently than personal use
- Subscribe & Save recurring items
- Returns and refunds (negative amounts)
- Digital purchases (Kindle, Prime Video, Music)
- Split shipments (multiple charges for one order)
- Marketplace third-party sellers

### 2. Learning System
**User Story:** As a user, I want the system to learn from my corrections so categorization accuracy improves over time and reflects my personal budgeting approach.

**Functionality:**
- Monitors transactions labeled "Auto-Categorized" for manual changes
- When user recategorizes an item or split, logs the correction
- Updates product-to-category mapping based on user's actual preferences
- Adjusts future categorization for similar items
- Builds user-specific rules over time

**Learning Triggers:**
- Daily comparison of yesterday's categorizations against current state
- If category changed on labeled transaction, records:
  - Product name/description
  - Original category assigned
  - User's preferred category
  - Timestamp of correction
- Updates internal mapping database
- Adjusts confidence scores for similar products

**Learning Examples:**
- System categorizes coffee as "Dining Out" → user changes to "Groceries" → future coffee purchases use "Groceries"
- User splits protein bars from "Groceries" into "Fitness" → system learns user's preference
- User categorizes dog treats as "Pet Care" but dog toys as "Discretionary" → system learns the distinction
- User consistently moves Amazon Fresh produce to "Groceries: Fresh" subcategory → system adopts this pattern

**Similarity Matching:**
- Exact product name matches
- Partial matches (e.g., "Organic Bananas 2lb" and "Bananas Organic")
- Brand-based patterns (e.g., user always puts Brand X in specific category)
- Product type keywords (e.g., anything with "organic" goes to premium grocery category)

### 3. Daily Email Summary
**User Story:** As a user, I want a daily email showing what was categorized so I can quickly verify accuracy without manually reviewing everything in YNAB.

**Email Contents:**

**Header Section:**
- Date range of summary
- Total transactions processed
- Total amount categorized
- Number of categories used
- Count of high/medium/low confidence categorizations

**Transaction Details (grouped by merchant):**

For each transaction:
- **Header**: Merchant, Order Date, Order Number (if available)
- **Amount**: Original charge, final amount (if different)
- **Match Confidence**: High/Medium/Low
- **Item Breakdown**:
  - Item name and quantity
  - Item price
  - Assigned category
  - Categorization confidence
- **Special Notes**:
  - Amount changed (Whole Foods substitutions)
  - Partial match (manual review suggested)
  - New product type (first time seeing this item)

**Learning Updates Section:**
- Summary of corrections detected from previous days
- For each correction:
  - Product name
  - Was categorized as: [original category]
  - You changed to: [new category]
  - Future impact: [what will change]

**Items Needing Review:**
- Transactions that couldn't be matched to Amazon orders
- Low-confidence categorizations
- Amount discrepancies beyond threshold

**Quick Actions:**
- Link to YNAB to review transactions
- Link to category management interface
- Feedback/report issue link

**Example Email Format:**
```
Amazon Categorization Report - January 9, 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Summary
• 3 transactions processed
• $247.53 categorized across 4 categories
• 2 high confidence, 1 medium confidence

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Amazon Fresh - January 8, 2026 • Order #123-4567890-1234567
Amount: $89.47 (originally charged $92.30 - items unavailable)
Match Confidence: High ✓
Flag: Orange

Items Categorized:
  Groceries                                    $89.47 → Groceries

Notes: Final amount lower due to unavailable items. Whole Foods order - not itemized.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Amazon.com - January 8, 2026 • Order #123-7654321-9876543
Amount: $142.98
Match Confidence: High ✓
Flag: Orange

Items Categorized:
  Household items (Command Strips, etc)        $24.99 → Household
  Books                                        $17.99 → Books & Entertainment
  Fitness equipment (Fitbit Charge 6)        $100.00 → Fitness & Health

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎓 Learning Updates

You made 2 corrections yesterday:

1. "Nature Valley Granola Bars, 12-pack"
   Originally: Groceries → Changed to: Fitness
   Impact: Future granola bars will use Fitness category

2. "Energizer AA Batteries, 48-pack"
   Originally: Electronics → Changed to: Household
   Impact: Future battery purchases will use Household category

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ Needs Your Review

• Amazon.com - $15.08 on Jan 7
  Could not match to any Amazon order
  Possible reasons: Amount mismatch, processing delay
  → Review manually in YNAB

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[Review in YNAB] [Manage Categories] [Send Feedback]
```

### 4. Account Management (Vercel Frontend)
**User Story:** As a user, I want to connect my YNAB and Amazon accounts so the agent can access my transaction and order data.

**Navigation: Accounts**

This section contains two sub-pages accessible from the left navigation:
- Accounts > YNAB Connection
- Accounts > Amazon Accounts

**Page: Accounts > YNAB Connection**

**YNAB Connection Section:**
- **Status Display:**
  - Connected: Shows budget name, last sync time, connection status (✓)
  - Not Connected: "Connect YNAB" button
- **OAuth Flow:**
  - Click "Connect YNAB" → redirect to YNAB OAuth
  - User authorizes access
  - Redirect back with success/error message
- **Budget Selection:**
  - Dropdown of available budgets (if user has multiple)
  - Selected budget is used for all operations
- **Reconnect/Disconnect:**
  - "Reconnect" button to refresh OAuth token
  - "Disconnect" button with confirmation modal
- **Permissions Display:**
  - Shows what access the app has (read transactions, write transactions, etc.)

**Page: Accounts > Amazon Accounts**

**Amazon Accounts Section:**
- **Multiple Account Support:**
  - List of connected Amazon accounts
  - Each account shows:
    - Account email/username
    - Nickname (user-defined, e.g., "User's Amazon", "Partner's Amazon")
    - Connection status
    - Last successful order fetch
    - Number of orders processed
- **Add Amazon Account:**
  - "Add Amazon Account" button
  - Modal with:
    - Nickname field (required)
    - Email/username field
    - Password field (encrypted storage)
    - "Test Connection" button to verify credentials
    - 2FA handling instructions/flow
  - Saves credentials securely
- **Account Management:**
  - Edit nickname
  - Reconnect (update credentials)
  - Remove account (with confirmation)
- **Use Case Support:**
  - Couple using same credit card but different Amazon accounts
  - Personal vs. business Amazon accounts
  - Family members' accounts all feeding into one YNAB budget

**Page Layout:**
```
┌─────────────────────────────────────────────┐
│ Accounts > YNAB Connection                   │
├─────────────────────────────────────────────┤
│                                              │
│ YNAB Budget                                  │
│ ┌──────────────────────────────────────┐   │
│ │ ✓ Connected: My Budget                │   │
│ │   Last synced: 2 hours ago            │   │
│ │   [Reconnect] [Disconnect]            │   │
│ └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ Accounts > Amazon Accounts                   │
├─────────────────────────────────────────────┤
│                                              │
│ Connected Amazon Accounts                    │
│ ┌──────────────────────────────────────┐   │
│ │ User's Amazon                      │   │
│ │ user@example.com                   │   │
│ │ ✓ Connected • Last fetch: 1 hour ago  │   │
│ │ [Edit] [Remove]                       │   │
│ ├──────────────────────────────────────┤   │
│ │ Partner's Amazon                         │   │
│ │ wife@example.com                      │   │
│ │ ✓ Connected • Last fetch: 1 hour ago  │   │
│ │ [Edit] [Remove]                       │   │
│ └──────────────────────────────────────┘   │
│                                              │
│ [+ Add Amazon Account]                      │
└─────────────────────────────────────────────┘
```

### 5. Payees Settings (Vercel Frontend)
**User Story:** As a user, I want to specify which payees should have their transactions automatically categorized, so the agent only processes my Amazon purchases and ignores other transactions.

**Navigation: Settings > Payees**

This page controls **which transactions get processed** by the agent. Only transactions from selected payees will be reviewed and categorized. All other transactions are ignored completely.

**Purpose:** Acts as a filter to determine scope of auto-categorization. If a transaction's payee isn't selected here, the agent will never touch it.

**Account Scope Section:**
- **Which YNAB accounts to monitor:**
  - Checkbox list of all accounts from connected YNAB budget
  - Examples:
    - ☑ Chase Amazon Card
    - ☑ Chase Sapphire Reserve
    - ☐ Checking Account
    - ☐ Savings Account
  - "Select All" / "Deselect All" helpers
  - Only transactions from selected accounts will be processed

**Payee Scope Section:**
- **Which payees to auto-categorize:**
  - Pulled from YNAB (list of all payees user has transacted with)
  - Default: Pre-selects common Amazon payees
    - ☑ Amazon.com
    - ☑ Amazon Fresh
    - ☑ Whole Foods Market
    - ☑ Amazon Prime
    - ☑ Amazon Marketplace
  - Search/filter functionality
  - User can add additional payees to monitor
  - "Add Custom Payee" button for variations not yet in YNAB
  
- **Payee Configuration (for each selected payee):**
  - **Amazon Account Mapping:** Which Amazon account(s) to check for orders
    - Example: "Amazon.com" → Check both "User's Amazon" and "Partner's Amazon"
    - Example: "Whole Foods" → Check only "Partner's Amazon"
  - **YNAB Account:** Which YNAB account this payee charges to
    - Example: "Amazon.com" charges to "Chase Amazon Card"
    - Used to narrow matching (only look at transactions from this account)
  
- **Bulk Actions:**
  - "Select all Amazon-related payees"
  - "Deselect all"

**Category Scope Section:**
- **Which categories the agent can use:**
  - Checkbox list of all categories from YNAB budget
  - Organized by category groups
  - Examples:
    - **Food & Dining**
      - ☑ Groceries
      - ☑ Dining Out
      - ☐ Alcohol & Bars
    - **Household**
      - ☑ Household Items
      - ☑ Home Maintenance
    - **Shopping**
      - ☑ Clothing
      - ☑ Electronics
      - ☑ Books & Supplies
  - "Select All in Group" helpers
  - Only selected categories will be used by the agent
  - Unselected categories can still be used manually but won't be auto-assigned

**Processing Rules:**
- **Minimum transaction amount:**
  - Slider or input field
  - Default: $0 (process all)
  - Use case: Skip small digital purchases under $5
- **Date range:**
  - "Process historical transactions" toggle
  - If enabled: Date picker for "start from" date
  - Use case: Bulk-process last 30/60/90 days on first setup
- **Flag settings:**
  - **Flag color selector**: Choose which YNAB flag color to apply
    - Options: Red, Orange (default), Yellow, Green, Blue, Purple
    - Visual color picker with preview
  - Checkbox: "Apply flag to processed transactions"
  - Help text: "Flag helps you identify auto-categorized transactions in YNAB"

**Page Layout:**
```
┌─────────────────────────────────────────────┐
│ Settings > Payees                            │
├─────────────────────────────────────────────┤
│                                              │
│ YNAB Accounts to Monitor                     │
│ ┌──────────────────────────────────────┐   │
│ │ ☑ Chase Amazon Card                   │   │
│ │ ☐ Bank of America Checking            │   │
│ │ ☐ Savings Account                     │   │
│ │                                        │   │
│ │ [Select All] [Deselect All]           │   │
│ └──────────────────────────────────────┘   │
│                                              │
│ Payees to Process                            │
│ ┌──────────────────────────────────────┐   │
│ │ [Search payees...]                    │   │
│ │                                        │   │
│ │ ☑ Amazon.com                          │   │
│ │   Amazon accounts: User's, Partner's     │   │
│ │   YNAB account: Chase Amazon Card     │   │
│ │                                        │   │
│ │ ☑ Amazon Fresh                        │   │
│ │   Amazon accounts: Partner's             │   │
│ │   YNAB account: Chase Amazon Card     │   │
│ │                                        │   │
│ │ ☑ Whole Foods Market                  │   │
│ │   Amazon accounts: Partner's             │   │
│ │   YNAB account: Chase Amazon Card     │   │
│ │                                        │   │
│ │ ☐ Amazon Prime (subscriptions only)   │   │
│ │                                        │   │
│ │ [+ Add Custom Payee]                  │   │
│ └──────────────────────────────────────┘   │
│                                              │
│ Processing Rules                             │
│ ┌──────────────────────────────────────┐   │
│ │ Minimum amount: $_____ [0]            │   │
│ │ ☑ Process historical transactions     │   │
│ │   Start from: [01/01/2026]            │   │
│ │                                        │   │
│ │ Flag Color:                            │   │
│ │ ○ Red  ● Orange  ○ Yellow             │   │
│ │ ○ Green  ○ Blue  ○ Purple             │   │
│ │ ☑ Apply flag to processed trans.      │   │
│ └──────────────────────────────────────┘   │
│                                              │
│ [Save Settings]                             │
└─────────────────────────────────────────────┘
```

### 6. Category Management (Vercel Frontend)
**User Story:** As a user, I want to describe how each YNAB category should be used so the agent can accurately categorize items from my Amazon orders.

**Navigation: Settings > Categories**

This page allows users to configure which categories can be used for auto-categorization and provide detailed descriptions to guide the categorization logic.

**Category Descriptions:**
- **Local storage only** (not synced with YNAB)
- YNAB's 200-character note limit is too restrictive for effective categorization guidance
- Descriptions can be as detailed as needed (recommended: 200-500 words for complex categories)
- Used by categorization logic (keyword matching or LLM) to determine which items belong in each category

**Category List View:**
- Display all YNAB budget categories organized by category groups (collapsible)
- **Each category shows:**
  - Toggle switch: Enable/disable for auto-categorization
  - Visual indicators:
    - ✓ Has description
    - ⚠️ No description (needs attention - will use generic matching)
    - 📊 Recently used (activity in last 7 days)
    - 🔄 High correction rate (may need better description)
  - **Metrics:**
    - Number of items categorized (last 30 days)
    - Current accuracy rate (% not corrected)
    - Last used timestamp
- Search and filter capabilities
- **Filter options:**
  - Show only enabled categories
  - Show only categories needing descriptions
  - Show by category group
- Sort options:
  - Alphabetical
  - Usage frequency
  - Last modified
  - Correction rate (ascending/descending)
  - Needs attention (no description first)

**Category Detail/Edit View:**
- **Header:**
  - Category name (synced from YNAB, read-only)
  - Category group badge
  - **Toggle: "Enable for auto-categorization"** (on/off)
    - When OFF: Category is grayed out and won't be used by agent
    - When ON: Category is active and can be assigned to transactions
  
- **Description Editor:**
  - Large text area for category descriptions
  - No character limit (stored locally, not in YNAB)
  - **Helpful prompts:**
    - "What types of items belong here?"
    - "Keywords and product types to match"
    - "Specific examples of products"
    - "What should NOT go in this category?"
    - "Brand names that always belong here"
  - Word/character counter for reference
  - **Save options:**
    - "Save" button (saves to local database)
  - Quality score indicator (based on length, specificity, examples)
  - **Template assist:**
    - "Use Template" button (applies pre-made description template)
    - "Generate with AI" button (creates suggested description based on category name and recent items)
  
- **Example Items Panel (auto-populated):**
  - Shows 10-20 recent items categorized here
  - Each item shows:
    - Product name
    - Date categorized
    - Whether it was corrected
    - Confidence score when categorized
  - "Refresh examples" button
  - Helps user verify description is working as intended
  
- **Statistics Panel:**
  - Items categorized here (7/30/90 day breakdown)
  - Average confidence score
  - Correction history:
    - Number of corrections received
    - Common correction targets (where items were moved to)
  - Trend indicator (improving/stable/declining accuracy)
  
- **Advanced Settings:**
  - **Confidence threshold slider:**
    - Adjust how conservative categorization should be
    - Range: 0.5 (permissive) to 0.95 (very conservative)
    - Default: 0.75
    - Help text explains impact
  - **Priority level:**
    - High/Medium/Low
    - Used when item could match multiple categories
  - **Auto-split behavior:**
    - Toggle: "Allow items to be grouped with other categories"
    - Some categories might always require solo splits

**Category Creation:**
- "Create New Category" button (prominent in header)
- Modal with fields:
  - Category name (required)
  - Parent group (dropdown of existing groups)
  - Initial description (optional but encouraged)
  - Copy settings from existing category (optional)
- Creates category in both YNAB and local system
- Immediately available for categorization
- Opens detail view after creation for further setup

**Bulk Operations:**
- Multi-select checkboxes on category list
- Actions available:
  - Export selected descriptions (JSON/CSV)
  - Import descriptions from file
  - Copy description template to multiple categories
  - Enable/disable for processing
  - Bulk edit confidence threshold
- "Export All" / "Import All" for category descriptions

**Template Library:**
- Pre-built description templates for common categories
- Examples:
  - "Groceries - General"
  - "Groceries - Organic/Premium"
  - "Household Items"
  - "Pet Care"
  - "Personal Care"
  - "Electronics"
  - "Books & Entertainment"
- User can save custom templates
- One-click apply to category

**Example Category Description Interface:**
```
┌─────────────────────────────────────────────┐
│ Settings > Categories > Groceries            │
│                                              │
│ Groceries                    [Food & Dining] │
│ ☑ Enable for auto-categorization            │
├─────────────────────────────────────────────┤
│                                              │
│ Category Description                         │
│ ┌──────────────────────────────────────┐   │
│ │ All Whole Foods and Amazon Fresh     │   │
│ │ orders are categorized here as a     │   │
│ │ single line item (not itemized).     │   │
│ │                                       │   │
│ │ For Amazon.com grocery items:        │   │
│ │ • Packaged foods, snacks, cereals    │   │
│ │ • Beverages (coffee, tea, juice,     │   │
│ │   not alcohol)                        │   │
│ │ • Pantry staples (rice, pasta, flour,│   │
│ │   canned goods, spices)               │   │
│ │ • Baking ingredients (sugar, baking  │   │
│ │   powder, vanilla extract)            │   │
│ │                                       │   │
│ │ Exclude:                              │   │
│ │ • Restaurant/takeout → Dining Out    │   │
│ │ • Alcohol → Alcohol & Bars           │   │
│ │ • Pet food → Pet Care                │   │
│ │ • Vitamins/supplements → Health      │   │
│ │ • Cleaning supplies → Household      │   │
│ │                                       │   │
│ │ Brands that always go here:          │   │
│ │ • Organic Valley, Stonyfield Farm    │   │
│ │ • 365 Whole Foods brand               │   │
│ │ • Any items labeled "organic"        │   │
│ └──────────────────────────────────────┘   │
│ 587 characters • Quality: Excellent ✓       │
│ [Save] [Use Template] [Generate with AI]    │
│                                              │
│ Example Items (Recent)                       │
│ ┌──────────────────────────────────────┐   │
│ │ • Whole Foods order 1/8 - $89.47 ✓    │   │
│ │ • Amazon Fresh order 1/7 - $62.34 ✓   │   │
│ │ • Coffee Beans (Amazon.com) 1/6 ✓     │   │
│ │ • Granola Bars 1/5 ✗ → Fitness       │   │
│ │ • Whole Foods order 1/4 - $45.21 ✓    │   │
│ └──────────────────────────────────────┘   │
│ [View All Items]                            │
│                                              │
│ Note: Whole Foods/Amazon Fresh orders shown │
│ as single line items (not itemized)         │
│                                              │
│ Statistics (Last 30 Days)                    │
│ ┌──────────────────────────────────────┐   │
│ │ Items categorized: 47                 │   │
│ │ Avg confidence: 0.82                  │   │
│ │ Corrections: 3 (6.4%)                 │   │
│ │ Trend: ↗️ Improving                   │   │
│ └──────────────────────────────────────┘   │
│                                              │
│ Advanced Settings                            │
│ ┌──────────────────────────────────────┐   │
│ │ Confidence threshold: [====··] 0.75   │   │
│ │ Priority: ● High ○ Medium ○ Low      │   │
│ │ ☑ Allow grouping with other items    │   │
│ └──────────────────────────────────────┘   │
│                                              │
│ [Save Changes]                              │
└─────────────────────────────────────────────┘
```

### 7. Overview Dashboard (Vercel Frontend)
**User Story:** As a user, I want a central dashboard to monitor processing status, review recent activity, and quickly access key features.

**Navigation: Overview**

**Page: Overview (Home)**

**Status Overview Cards:**
- **YNAB Connection Status:**
  - Connected budget name
  - Last sync time
  - Connection health (✓ or ⚠️)
  - Quick action: "Sync Now"
  
- **Amazon Accounts Status:**
  - Number of connected accounts
  - Last order fetch for each
  - Any connection issues flagged
  - Quick action: "Manage Accounts"
  
- **Processing Status:**
  - Transactions processed (today/this week/this month)
  - Amount categorized
  - Categories used
  - Accuracy rate (% not corrected)

**Recent Activity Feed:**
- Last 10 processing runs with:
  - Timestamp
  - Transactions processed count
  - Success/partial/failure indicator
  - Link to detailed email summary
- Click to expand for details

**Pending Items:**
- Transactions awaiting processing (unlabeled Amazon transactions)
- Count by payee
- Estimated next processing time
- "Process Now" manual trigger button

**Quick Actions:**
- Large, prominent buttons for common tasks:
  - "Process Transactions Now"
  - "Review Recent Categorizations" (links to YNAB with flag filter)
  - "Manage Categories" (→ Settings > Categories)
  - "Manage Payees" (→ Settings > Payees)
  - "View Latest Email Summary"

**Alerts & Notifications:**
- Connection issues (YNAB token expired, Amazon login failed)
- High correction rate for specific categories (suggests description update needed)
- New payees detected not in scope settings
- Processing errors from last run

**Charts & Insights:**
- Categorization accuracy trend (last 30 days)
- Top categories by transaction count
- Processing volume by day of week
- Confidence score distribution

**Page Layout:**
```
┌─────────────────────────────────────────────┐
│ Overview                                     │
├─────────────────────────────────────────────┤
│                                              │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│ │ YNAB     │ │ Amazon   │ │ Today    │    │
│ │ ✓ My Bdgt│ │ 2 accts  │ │ 5 trans  │    │
│ │ 2h ago   │ │ ✓ Active │ │ $247.53  │    │
│ └──────────┘ └──────────┘ └──────────┘    │
│                                              │
│ ⚠️ Alerts                                    │
│ ┌──────────────────────────────────────┐   │
│ │ • "Groceries" category has 15%        │   │
│ │   correction rate - consider updating │   │
│ │   description                          │   │
│ └──────────────────────────────────────┘   │
│                                              │
│ Pending Processing                           │
│ ┌──────────────────────────────────────┐   │
│ │ 3 Amazon transactions awaiting        │   │
│ │ Next auto-run: Tomorrow 2:00 AM       │   │
│ │ [Process Now]                         │   │
│ └──────────────────────────────────────┘   │
│                                              │
│ Recent Activity                              │
│ ┌──────────────────────────────────────┐   │
│ │ Today 2:15 AM - 5 transactions ✓      │   │
│ │ Yesterday 2:15 AM - 3 transactions ✓  │   │
│ │ Jan 7 2:15 AM - 8 transactions ✓      │   │
│ └──────────────────────────────────────┘   │
│ [View All Activity]                         │
│                                              │
│ Quick Actions                                │
│ [Process Now] [Review Recent]               │
│ [Categories] [Payees]                       │
│                                              │
│ Accuracy Trend (Last 30 Days)               │
│ ┌──────────────────────────────────────┐   │
│ │     ╱╲                                 │   │
│ │    ╱  ╲    ╱╲                          │   │
│ │   ╱    ╲  ╱  ╲                         │   │
│ │  ╱      ╲╱    ╲___                    │   │
│ │                                        │   │
│ │ 85% average accuracy                   │   │
│ └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

**Navigation Structure:**

```
Left-Hand Navigation:
├─ 📊 Overview
│   └─ Dashboard home page
├─ 🔗 Accounts
│   ├─ YNAB Connection
│   └─ Amazon Accounts
└─ ⚙️ Settings
    ├─ Categories
    └─ Payees
```

**Page Descriptions:**

**Overview** - Dashboard showing status, recent activity, and quick actions

**Accounts** - Connection management
- YNAB Connection: OAuth setup, budget selection, sync status
- Amazon Accounts: Add/manage multiple Amazon accounts with nicknames

**Settings > Categories** - Category configuration
- List of YNAB categories
- Category descriptions for categorization logic
- Enable/disable categories for processing
- Confidence thresholds
- Template library

**Settings > Payees** - Payee scope configuration
- Which payees to process (Amazon.com, Whole Foods, etc.)
- Map payees to specific Amazon accounts
- Which YNAB accounts to monitor
- Processing rules (minimum amount, flag color, historical processing)

### 8. YNAB Integration & Labeling
**User Story:** As a user, I want to easily identify which transactions were auto-categorized versus manually categorized, and have the option to review agent decisions.

**Functionality:**
- **Uses YNAB flag colors** (not custom labels - YNAB provides fixed set of colors):
  - Available flags: Red, Orange, Yellow, Green, Blue, Purple, or none
  - User selects which flag color to use for auto-categorized transactions
  - Default: Orange flag
  - Configurable in frontend settings
- Applies selected flag to all transactions processed by the agent
- Marks transactions as "approved" after categorization
- Memo field includes:
  - "Categorized by Amazon-YNAB Agent"
  - Order number
  - Match confidence level
  - Processing date
  - For Whole Foods: note if amount changed and why
- User can filter YNAB by flag color to review all agent categorizations
- Flag can be removed by user to indicate "reviewed and verified"

**Flag-Based Workflows:**
- **Review mode**: Filter to selected flag color (e.g., Orange), review recent splits
- **Correction detection**: System monitors flagged transactions for category changes
- **Batch approval**: User can remove flags from multiple transactions at once in YNAB
- **Re-processing**: User can remove flag and mark as unapproved to trigger re-categorization

## User Flow

### Initial Setup
1. User creates account on Vercel frontend
2. **Accounts > YNAB Connection:** User authenticates with YNAB (OAuth)
3. **Accounts > Amazon Accounts:** User connects Amazon account(s) with nicknames (secure credential storage)
4. **Settings > Payees:** User configures processing scope:
   - Select which YNAB accounts to monitor
   - Select which payees to process
   - Map payees to Amazon accounts
   - Map payees to YNAB accounts
   - Set processing rules (minimum amount, flag color, historical processing)
5. **Settings > Categories:** User configures categories:
   - Enable categories for auto-categorization
   - Add detailed descriptions for primary categories
   - Descriptions guide LLM categorization logic (no character limit)
6. User sets email address for daily summaries (in account settings)
7. Optional: Process historical transactions

### Daily Automated Processing
1. Agent runs at scheduled time
2. Fetches all unapproved Amazon transactions from YNAB (filtered by selected payees in scope settings)
3. Fetches recent Amazon order history from all connected Amazon accounts
4. **Reconciliation phase:**
   - For each YNAB transaction, attempts to match with Amazon order
   - Uses exact amount match, date, merchant, and account mapping to find matches
   - Flags uncertain matches for user review
5. **Categorization phase:**
   - For each matched order, retrieves item details
   - **For Whole Foods/Amazon Fresh orders**: 
     - Categorizes entire order as "Groceries" (no itemization)
     - No LLM call needed
   - **For Amazon.com orders**: 
     - Sends order items + enabled category descriptions to Claude API
     - Receives categorization with confidence scores and reasoning
     - Validates LLM response
   - Groups items by category
   - Creates split transaction in YNAB with category line items
   - Adds memos with order details and confidence scores
   - Applies user-selected flag color (e.g., Orange)
   - Marks transaction as approved
   - Stores LLM categorizations and reasoning in database
6. **Learning phase:**
   - Checks previous day's flagged transactions for manual category changes
   - Logs any corrections to database
   - Updates product-to-category mappings
   - Marks LLMCategorizations as corrected when applicable
7. **Reporting phase:**
   - Compiles email summary
   - Includes confidence scores and reasoning for transparency
   - Flags low-confidence items for review
   - Sends to user
   - Logs activity for debugging

### Manual Review & Correction Flow
1. User receives daily email summary
2. User reviews categorizations (in email or YNAB)
3. User identifies incorrect categorization
4. User manually updates split transaction in YNAB
5. Transaction retains flag color
6. Next day, agent detects the change during learning phase
7. Agent updates internal product mapping
8. Next email includes note about the correction learned
9. Future similar items use corrected categorization

**Alternative: Request Re-processing**
1. User removes flag from transaction in YNAB
2. User marks transaction as unapproved
3. Next processing run picks it up again
4. Agent re-categorizes with updated learned patterns

### Category Description Update Flow
1. User notices recurring incorrect categorization
2. User visits Settings > Categories
3. User navigates to relevant category
4. User updates description with more specific guidance or examples
5. User clicks "Save"
6. Changes save immediately to local database
7. Next processing run uses updated description in LLM prompt
8. User can review example items and LLM reasoning to verify improvement

## Categorization Logic & LLM Integration

### Overview
Determining the correct category for individual Amazon items (toothpaste, toys, trash bags, etc.) is a complex matching problem that benefits significantly from LLM capabilities. While keyword matching is possible, an LLM provides much better accuracy and handles edge cases naturally.

### Why LLM is the Best Approach

**Problems with Pure Keyword Matching:**
- Requires exhaustive keyword lists for every category
- Struggles with synonyms (garbage bags vs trash bags vs waste bags)
- Can't handle context (dog toy vs baby toy, protein bar as Groceries vs Fitness)
- Brittle when products have non-descriptive names ("365 Brand Organic Mix")
- Difficult to maintain as product catalog changes
- Poor handling of multi-word product names with ambiguous keywords

**LLM Advantages:**
- Natural language understanding of product descriptions
- Contextual decision-making (understands intent from category descriptions)
- Handles synonyms and variations automatically
- Can reason about edge cases ("is this a grocery item or a health supplement?")
- Learns from category descriptions without explicit keyword engineering
- Can explain its reasoning (helpful for debugging and user trust)
- Easily adapts to new products without code changes

### Recommended LLM: Claude via Anthropic API

**Why Claude:**
- High accuracy for classification tasks
- Fast response times (suitable for batch processing)
- Supports structured output (JSON)
- Can process multiple items in single request (batch efficiency)
- Cost-effective for this use case (~$3 per million input tokens)
- Reliable and maintained by Anthropic

**Model Selection:**
- **Claude 3.5 Haiku** (recommended for production):
  - Fast and cost-effective
  - Excellent for straightforward categorization tasks
  - Pricing: $0.80 per million input tokens, $4.00 per million output tokens
- **Claude 3.5 Sonnet** (for complex cases or testing):
  - Higher accuracy for ambiguous items
  - Pricing: $3 per million input tokens, $15 per million output tokens

### Implementation Architecture

**API Integration:**
```
User's Application Server
    ↓
Anthropic API (Claude)
    ↓
Structured JSON Response
    ↓
Database (store categorizations)
```

**Setup Requirements:**
1. Create Anthropic API account at https://console.anthropic.com
2. Generate API key
3. Store API key securely in environment variables
4. Install Anthropic SDK: `npm install @anthropic-ai/sdk` or `pip install anthropic`

### Data Flow for Categorization

**Input to LLM (per Amazon order):**
```json
{
  "order_id": "123-4567890-1234567",
  "merchant": "Amazon.com",
  "total_amount": 142.98,
  "items": [
    {
      "name": "Command Picture Hanging Strips Variety Pack, 48 pairs",
      "price": 24.99,
      "quantity": 1
    },
    {
      "name": "The Anthropocene Reviewed: Essays on a Human-Centered Planet",
      "price": 17.99,
      "quantity": 1
    },
    {
      "name": "Fitbit Charge 6 Fitness Tracker",
      "price": 100.00,
      "quantity": 1
    }
  ],
  "enabled_categories": [
    {
      "id": "cat_123",
      "name": "Household",
      "description": "Home maintenance items including: cleaning supplies, organization products, command strips, light bulbs, batteries, paper towels, trash bags. Exclude: furniture, appliances."
    },
    {
      "id": "cat_456",
      "name": "Books & Entertainment",
      "description": "Physical and digital books, audiobooks, magazines, movies, music. Include: fiction, non-fiction, textbooks, educational materials."
    },
    {
      "id": "cat_789",
      "name": "Fitness & Health",
      "description": "Fitness equipment, trackers, workout gear, yoga mats, weights, resistance bands. Also vitamins and supplements. Exclude: over-the-counter medicine."
    }
  ]
}
```

**LLM Prompt Structure:**
```
System Prompt:
You are a transaction categorization assistant. Your task is to categorize Amazon purchase items into budget categories based on the provided category descriptions.

For each item, determine the most appropriate category based on:
1. The item name and description
2. The category descriptions provided
3. Common sense about how people budget

Rules:
- Whole Foods and Amazon Fresh orders should ALWAYS be categorized as "Groceries" with NO item-level breakdown
- For Amazon.com orders, categorize each item individually
- Each item must map to exactly one category
- If unsure between categories, choose the most specific match
- Include a confidence score (0.0-1.0)
- Provide brief reasoning for your choice

Respond with valid JSON only, no other text.

User Prompt:
Categorize these items from an Amazon.com order totaling $142.98:

Items:
1. "Command Picture Hanging Strips Variety Pack, 48 pairs" - $24.99
2. "The Anthropocene Reviewed: Essays on a Human-Centered Planet" - $17.99
3. "Fitbit Charge 6 Fitness Tracker" - $100.00

Available Categories:
- Household: Home maintenance items including: cleaning supplies, organization products, command strips, light bulbs, batteries, paper towels, trash bags. Exclude: furniture, appliances.
- Books & Entertainment: Physical and digital books, audiobooks, magazines, movies, music. Include: fiction, non-fiction, textbooks, educational materials.
- Fitness & Health: Fitness equipment, trackers, workout gear, yoga mats, weights, resistance bands. Also vitamins and supplements. Exclude: over-the-counter medicine.

Return JSON in this format:
{
  "categorizations": [
    {
      "item_name": "item name here",
      "category_id": "cat_123",
      "category_name": "Category Name",
      "confidence": 0.95,
      "reasoning": "brief explanation"
    }
  ]
}
```

**Expected LLM Response:**
```json
{
  "categorizations": [
    {
      "item_name": "Command Picture Hanging Strips Variety Pack, 48 pairs",
      "category_id": "cat_123",
      "category_name": "Household",
      "confidence": 0.98,
      "reasoning": "Command strips are explicitly mentioned in the Household category description as organization products"
    },
    {
      "item_name": "The Anthropocene Reviewed: Essays on a Human-Centered Planet",
      "category_id": "cat_456",
      "category_name": "Books & Entertainment",
      "confidence": 0.99,
      "reasoning": "This is a non-fiction book, which falls under Books & Entertainment category"
    },
    {
      "item_name": "Fitbit Charge 6 Fitness Tracker",
      "category_id": "cat_789",
      "category_name": "Fitness & Health",
      "confidence": 0.99,
      "reasoning": "Fitness tracker is explicitly mentioned in Fitness & Health category description"
    }
  ]
}
```

### Processing Results

**After receiving LLM response:**
1. Parse JSON response
2. Validate all items were categorized
3. Check confidence scores:
   - High confidence (>0.85): Auto-apply
   - Medium confidence (0.65-0.85): Auto-apply but flag in email for review
   - Low confidence (<0.65): Flag for manual review, don't auto-apply
4. Store categorizations in LLMCategorizations table
5. Create split transaction in YNAB:
   - Group items by category
   - Sum amounts per category
   - Create split lines
6. Log LLM reasoning for debugging and learning

**Error Handling:**
- If LLM returns invalid JSON → retry once, then flag for manual review
- If LLM misses an item → flag entire order for manual review
- If LLM returns category not in enabled list → use fallback category or flag for review
- If API call fails → queue for retry, send error notification

### Cost Estimation

**Typical order processing:**
- Input: ~500 tokens (order details + category descriptions)
- Output: ~200 tokens (categorization JSON)
- Cost per order (Haiku): ~$0.0008 (less than a tenth of a cent)
- 100 orders/day = ~$0.08/day = $2.40/month
- 500 orders/day = ~$0.40/day = $12/month

**Optimization strategies:**
- Cache categorizations for identical product names in ProductMappings table
- Batch multiple orders in single API call when possible
- Use Haiku for most orders, Sonnet only for low-confidence retry

### Implementation Code Example (Node.js)

```javascript
import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

async function categorizeAmazonOrder(order, enabledCategories) {
  // Build category descriptions for prompt
  const categoryList = enabledCategories.map(cat => 
    `- ${cat.name}: ${cat.description}`
  ).join('\n');

  // Build items list for prompt
  const itemsList = order.items.map((item, idx) => 
    `${idx + 1}. "${item.name}" - $${item.price}`
  ).join('\n');

  const message = await anthropic.messages.create({
    model: "claude-3-5-haiku-20241022",
    max_tokens: 1024,
    system: `You are a transaction categorization assistant. Your task is to categorize Amazon purchase items into budget categories based on the provided category descriptions.

For each item, determine the most appropriate category based on:
1. The item name and description
2. The category descriptions provided
3. Common sense about how people budget

Rules:
- Whole Foods and Amazon Fresh orders should ALWAYS be categorized as "Groceries" with NO item-level breakdown
- For Amazon.com orders, categorize each item individually
- Each item must map to exactly one category
- If unsure between categories, choose the most specific match
- Include a confidence score (0.0-1.0)
- Provide brief reasoning for your choice

Respond with valid JSON only, no other text.`,
    messages: [
      {
        role: "user",
        content: `Categorize these items from an ${order.merchant} order totaling $${order.total_amount}:

Items:
${itemsList}

Available Categories:
${categoryList}

Return JSON in this format:
{
  "categorizations": [
    {
      "item_name": "item name here",
      "category_id": "cat_123",
      "category_name": "Category Name",
      "confidence": 0.95,
      "reasoning": "brief explanation"
    }
  ]
}`
      }
    ]
  });

  // Extract and parse response
  const responseText = message.content[0].text;
  const categorizations = JSON.parse(responseText);

  return categorizations;
}
```

### Fallback Strategy (Non-LLM)

**If LLM is not available or fails:**
1. Simple keyword matching against category descriptions
2. Use product category from ProductMappings (learned from past corrections)
3. Flag everything as low-confidence for manual review
4. Fall back to uncategorized

**Basic Keyword Matching Implementation:**
```javascript
function keywordMatch(itemName, categories) {
  const itemLower = itemName.toLowerCase();
  const scores = {};

  for (const category of categories) {
    // Extract keywords from description
    const keywords = category.description.toLowerCase()
      .split(/[,\s]+/)
      .filter(word => word.length > 3); // Skip short words
    
    // Count keyword matches
    let score = 0;
    for (const keyword of keywords) {
      if (itemLower.includes(keyword)) {
        score++;
      }
    }
    scores[category.id] = score;
  }

  // Return category with highest score
  const bestCategory = Object.entries(scores)
    .sort(([,a], [,b]) => b - a)[0];
  
  return {
    category_id: bestCategory[0],
    confidence: Math.min(bestCategory[1] / 5, 0.7) // Cap at 0.7 for keyword matching
  };
}
```

This approach works but is significantly less accurate than LLM.

### Monitoring & Improvement

**Track metrics:**
- LLM confidence score distribution
- User correction rate by confidence bucket
- Most frequently corrected categories
- LLM cost per transaction
- API latency and error rates

**Continuous improvement:**
- When user corrects a categorization, log the correction in LLMCategorizations table
- Periodically review low-confidence items
- Update category descriptions based on correction patterns
- A/B test between Haiku and Sonnet for cost/accuracy tradeoff

## Technical Considerations

### Data Sources & APIs
- **YNAB API**: 
  - Transaction read/write
  - Category management (read category names and IDs)
  - Label/flag management
  - Account/budget access
  - Rate limits: ~200 requests per hour
- **Anthropic API (Claude)**:
  - LLM-based categorization of Amazon items
  - Model: Claude 3.5 Haiku (recommended) or Claude 3.5 Sonnet
  - Structured JSON output for categorizations
  - Rate limits: Tier-dependent (typically 50-500 requests/minute)
  - Pricing: ~$0.80-$3 per million input tokens
- **Amazon**: 
  - No official API available
  - Options: Web scraping, browser automation (Puppeteer/Playwright), or third-party services
  - Must handle authentication, 2FA
  - Order history with item-level details
  - Rate limiting and anti-bot detection considerations
- **Email Service**: 
  - SendGrid, AWS SES, Resend, or similar
  - Template management for daily summaries
  - Tracking for open rates/engagement

### Architecture (High-Level)
- **Frontend**: 
  - Next.js on Vercel
  - Server-side rendering for category management UI
  - API routes for backend communication
  
- **Backend Services**:
  - Vercel Functions or separate API server
  - Scheduled job (cron) for daily processing
  - API endpoints for:
    - Category CRUD operations
    - LLM categorization service
    - Manual re-processing triggers
    - User preferences
    - Learning data viewing
  
- **Database**: 
  - PostgreSQL (Vercel Postgres, Supabase, or similar)
  - Tables for:
    - User accounts and auth tokens
    - Category descriptions
    - Product-to-category mappings (learning data)
    - Correction history
    - Processing logs    - Transaction matching cache
  
- **Job Queue** (optional but recommended):
  - For handling processing of multiple transactions
  - Retry logic for failed API calls
  - Bull/BullMQ with Redis, or similar

### Data Models (Detailed)

**Users**
- id (UUID, primary key)
- email (unique)
- created_at, updated_at
- preferences (JSONB):
  - email_frequency (daily/weekly/manual)
  - timezone
  - date_format
  - flag_color (red/orange/yellow/green/blue/purple)
- subscription_status (free/pro/enterprise)
- subscription_expires_at

**YNABConnections**
- id (UUID, primary key)
- user_id (foreign key → Users)
- budget_id (YNAB budget ID)
- budget_name
- access_token (encrypted)
- refresh_token (encrypted)
- token_expires_at
- last_sync_at
- connection_status (active/expired/error)
- created_at, updated_at

**AmazonAccounts**
- id (UUID, primary key)
- user_id (foreign key → Users)
- nickname (user-defined, e.g., "User's Amazon")
- email (Amazon account email)
- credentials (encrypted JSON with login details)
- last_order_fetch_at
- last_successful_login_at
- connection_status (active/needs_reauth/error)
- order_count_processed
- created_at, updated_at

**AccountMappings**
- id (UUID, primary key)
- user_id (foreign key → Users)
- amazon_account_id (foreign key → AmazonAccounts)
- ynab_account_id (YNAB account ID)
- ynab_account_name (cached for display)
- created_at

**ProcessingScope**
- id (UUID, primary key)
- user_id (foreign key → Users)
- ynab_accounts (array of YNAB account IDs to monitor)
- payees (JSONB array):
  - payee_name
  - ynab_payee_id
  - amazon_account_ids (which Amazon accounts to check)
- categories (array of YNAB category IDs allowed for use)
- min_transaction_amount (decimal)
- process_historical (boolean)
- historical_start_date (date, nullable)
- auto_flag_enabled (boolean)
- flag_color (enum: red/orange/yellow/green/blue/purple, default: orange)
- updated_at

**Categories**
- id (UUID, primary key)
- user_id (foreign key → Users)
- ynab_category_id (YNAB category ID)
- ynab_category_group_id (YNAB group ID)
- name (synced from YNAB)
- group_name (synced from YNAB)
- description (user-provided, stored locally - no character limit)
- confidence_threshold (decimal 0.0-1.0, default 0.75)
- priority (enum: high/medium/low)
- allow_grouping (boolean, default true)
- enabled_for_processing (boolean)
- quality_score (calculated based on description length and specificity)
- last_updated_at
- created_at

**ProductMappings** (learning data)
- id (UUID, primary key)
- user_id (foreign key → Users)
- product_identifier (normalized product name/description)
- product_keywords (array for matching)
- brand (extracted brand name, nullable)
- category_id (foreign key → Categories)
- confidence_score (decimal 0.0-1.0)
- times_categorized (integer, tracks usage)
- correction_count (integer)
- last_used_at
- created_at

**CorrectionHistory**
- id (UUID, primary key)
- user_id (foreign key → Users)
- ynab_transaction_id (YNAB transaction ID)
- product_name
- original_category_id (foreign key → Categories)
- corrected_category_id (foreign key → Categories)
- correction_detected_at
- amazon_order_id (nullable)

**TransactionMatches** (cache)
- id (UUID, primary key)
- user_id (foreign key → Users)
- ynab_transaction_id (YNAB transaction ID)
- ynab_account_id (YNAB account ID)
- amazon_account_id (foreign key → AmazonAccounts)
- amazon_order_id (Amazon order number)
- match_confidence (enum: high/medium/low)
- match_method (exact_amount/close_amount/timestamp)
- ynab_amount (decimal)
- amazon_amount (decimal)
- transaction_date
- matched_at
- items_data (JSONB cache of order items)

**ProcessingLogs**
- id (UUID, primary key)
- user_id (foreign key → Users)
- run_started_at
- run_completed_at
- status (success/partial/failure)
- transactions_fetched (integer)
- transactions_matched (integer)
- transactions_processed (integer)
- categories_used (integer)
- llm_api_calls (integer)
- llm_total_cost (decimal, in dollars)
- errors (JSONB array)
- summary (JSONB):
  - high_confidence_count
  - medium_confidence_count
  - low_confidence_count
  - total_amount_processed
  - llm_average_confidence
  
**LLMCategorizations**
- id (UUID, primary key)
- user_id (foreign key → Users)
- transaction_match_id (foreign key → TransactionMatches)
- item_name (product name from Amazon)
- category_id (foreign key → Categories, the category chosen by LLM)
- confidence_score (decimal 0.0-1.0, from LLM)
- llm_reasoning (text, explanation from LLM)
- was_corrected (boolean, if user changed it)
- corrected_category_id (foreign key → Categories, nullable)
- model_used (string, e.g., "claude-3-5-haiku-20241022")
- created_at

**EmailSummaries**
- id (UUID, primary key)
- user_id (foreign key → Users)
- processing_log_id (foreign key → ProcessingLogs)
- sent_at
- email_opened_at (nullable, for tracking)
- content (text, stored summary for history viewing)

**CategoryTemplates**
- id (UUID, primary key)
- name (template name, e.g., "Groceries - General")
- description_template (template text, no character limit)
- category_type (groceries/household/entertainment/etc)
- is_system_template (boolean)
- created_by_user_id (nullable, for user-created templates)
- usage_count (integer)

### Key Technical Challenges

**1. Amazon Data Access**
- No official API requires scraping or automation
- Must handle 2FA, CAPTCHAs
- Structure of Amazon pages may change
- Multiple Amazon accounts per user adds complexity
- Possible solutions:
  - Puppeteer/Playwright for browser automation
  - Third-party services (if available and cost-effective)
  - Email parsing (Amazon order confirmation emails)
- **Multi-account strategy:**
  - Separate browser sessions per Amazon account
  - Cookie/session management
  - Parallel fetching with rate limiting

**2. Transaction Matching Logic**
- **Exact amount matching**: Amounts will always line up between YNAB and Amazon
- **Collision handling**: Multiple Amazon orders on same day with same amount
  - Use timestamp proximity when available
  - Use account mappings to narrow search space (check only relevant Amazon accounts)
  - Flag ambiguous matches for manual review
- **Timing issues**: 
  - YNAB pending vs posted transactions
  - Amazon order date vs charge date
  - Whole Foods amount updates (pending → final)
- **Multiple Amazon accounts**: Same transaction could match orders from different accounts
  - Solution: Use account mappings to determine which Amazon account(s) to check for each payee
- Solution approach:
  - Multi-factor matching (exact amount + date + merchant + account mapping)
  - Confidence scoring for ambiguous cases
  - Manual review queue when confidence is low

**3. Whole Foods Amount Reconciliation**
- Initial charge ≠ final charge due to weight-based items, substitutions
- Must track pending → posted state changes
- Solution:
  - Match initially on pending amount
  - Monitor for updates to transaction
  - Update categorization when final amount posts
  - Note discrepancies in memo

## Categorization Logic & LLM Integration

### Overview
Determining the correct category for individual Amazon items (toothpaste, toys, trash bags, etc.) is a complex matching problem that benefits significantly from LLM capabilities. While keyword matching is possible, an LLM provides much better accuracy and handles edge cases naturally.

### Why LLM is the Best Approach

**Problems with Pure Keyword Matching:**
- Requires exhaustive keyword lists for every category
- Struggles with synonyms (garbage bags vs trash bags vs waste bags)
- Can't handle context (dog toy vs baby toy, protein bar as Groceries vs Fitness)
- Brittle when products have non-descriptive names ("365 Brand Organic Mix")
- Difficult to maintain as product catalog changes
- Poor handling of multi-word product names with ambiguous keywords

**LLM Advantages:**
- Natural language understanding of product descriptions
- Contextual decision-making (understands intent from category descriptions)
- Handles synonyms and variations automatically
- Can reason about edge cases ("is this a grocery item or a health supplement?")
- Learns from category descriptions without explicit keyword engineering
- Can explain its reasoning (helpful for debugging and user trust)
- Easily adapts to new products without code changes

### Recommended LLM: Claude via Anthropic API

**Why Claude:**
- High accuracy for classification tasks
- Fast response times (suitable for batch processing)
- Supports structured output (JSON)
- Can process multiple items in single request (batch efficiency)
- Cost-effective for this use case (~$3 per million input tokens)
- Reliable and maintained by Anthropic

**Model Selection:**
- **Claude 3.5 Haiku** (recommended for production):
  - Fast and cost-effective
  - Excellent for straightforward categorization tasks
  - Pricing: $0.80 per million input tokens, $4.00 per million output tokens
- **Claude 3.5 Sonnet** (for complex cases or testing):
  - Higher accuracy for ambiguous items
  - Pricing: $3 per million input tokens, $15 per million output tokens

### Implementation Architecture

**API Integration:**
```
User's Application Server
    ↓
Anthropic API (Claude)
    ↓
Structured JSON Response
    ↓
Database (store categorizations)
```

**Setup Requirements:**
1. Create Anthropic API account at https://console.anthropic.com
2. Generate API key
3. Store API key securely in environment variables
4. Install Anthropic SDK: `npm install @anthropic-ai/sdk` or `pip install anthropic`

### Data Flow for Categorization

**Input to LLM (per Amazon order):**
```json
{
  "order_id": "123-4567890-1234567",
  "merchant": "Amazon.com",
  "total_amount": 142.98,
  "items": [
    {
      "name": "Command Picture Hanging Strips Variety Pack, 48 pairs",
      "price": 24.99,
      "quantity": 1
    },
    {
      "name": "The Anthropocene Reviewed: Essays on a Human-Centered Planet",
      "price": 17.99,
      "quantity": 1
    },
    {
      "name": "Fitbit Charge 6 Fitness Tracker",
      "price": 100.00,
      "quantity": 1
    }
  ],
  "enabled_categories": [
    {
      "id": "cat_123",
      "name": "Household",
      "description": "Home maintenance items including: cleaning supplies, organization products, command strips, light bulbs, batteries, paper towels, trash bags. Exclude: furniture, appliances."
    },
    {
      "id": "cat_456",
      "name": "Books & Entertainment",
      "description": "Physical and digital books, audiobooks, magazines, movies, music. Include: fiction, non-fiction, textbooks, educational materials."
    },
    {
      "id": "cat_789",
      "name": "Fitness & Health",
      "description": "Fitness equipment, trackers, workout gear, yoga mats, weights, resistance bands. Also vitamins and supplements. Exclude: over-the-counter medicine."
    }
  ]
}
```

**LLM Prompt Structure:**
```
System Prompt:
You are a transaction categorization assistant. Your task is to categorize Amazon purchase items into budget categories based on the provided category descriptions.

For each item, determine the most appropriate category based on:
1. The item name and description
2. The category descriptions provided
3. Common sense about how people budget

Rules:
- Whole Foods and Amazon Fresh orders should ALWAYS be categorized as "Groceries" with NO item-level breakdown
- For Amazon.com orders, categorize each item individually
- Each item must map to exactly one category
- If unsure between categories, choose the most specific match
- Include a confidence score (0.0-1.0)
- Provide brief reasoning for your choice

Respond with valid JSON only, no other text.

User Prompt:
Categorize these items from an Amazon.com order totaling $142.98:

Items:
1. "Command Picture Hanging Strips Variety Pack, 48 pairs" - $24.99
2. "The Anthropocene Reviewed: Essays on a Human-Centered Planet" - $17.99
3. "Fitbit Charge 6 Fitness Tracker" - $100.00

Available Categories:
- Household: Home maintenance items including: cleaning supplies, organization products, command strips, light bulbs, batteries, paper towels, trash bags. Exclude: furniture, appliances.
- Books & Entertainment: Physical and digital books, audiobooks, magazines, movies, music. Include: fiction, non-fiction, textbooks, educational materials.
- Fitness & Health: Fitness equipment, trackers, workout gear, yoga mats, weights, resistance bands. Also vitamins and supplements. Exclude: over-the-counter medicine.

Return JSON in this format:
{
  "categorizations": [
    {
      "item_name": "item name here",
      "category_id": "cat_123",
      "category_name": "Category Name",
      "confidence": 0.95,
      "reasoning": "brief explanation"
    }
  ]
}
```

**Expected LLM Response:**
```json
{
  "categorizations": [
    {
      "item_name": "Command Picture Hanging Strips Variety Pack, 48 pairs",
      "category_id": "cat_123",
      "category_name": "Household",
      "confidence": 0.98,
      "reasoning": "Command strips are explicitly mentioned in the Household category description as organization products"
    },
    {
      "item_name": "The Anthropocene Reviewed: Essays on a Human-Centered Planet",
      "category_id": "cat_456",
      "category_name": "Books & Entertainment",
      "confidence": 0.99,
      "reasoning": "This is a non-fiction book, which falls under Books & Entertainment category"
    },
    {
      "item_name": "Fitbit Charge 6 Fitness Tracker",
      "category_id": "cat_789",
      "category_name": "Fitness & Health",
      "confidence": 0.99,
      "reasoning": "Fitness tracker is explicitly mentioned in Fitness & Health category description"
    }
  ]
}
```

### Processing Results

**After receiving LLM response:**
1. Parse JSON response
2. Validate all items were categorized
3. Check confidence scores:
   - High confidence (>0.85): Auto-apply
   - Medium confidence (0.65-0.85): Auto-apply but flag in email for review
   - Low confidence (<0.65): Flag for manual review, don't auto-apply
4. Store categorizations in database
5. Create split transaction in YNAB:
   - Group items by category
   - Sum amounts per category
   - Create split lines
6. Log LLM reasoning for debugging and learning

**Error Handling:**
- If LLM returns invalid JSON → retry once, then flag for manual review
- If LLM misses an item → flag entire order for manual review
- If LLM returns category not in enabled list → use fallback category or flag for review
- If API call fails → queue for retry, send error notification

### Cost Estimation

**Typical order processing:**
- Input: ~500 tokens (order details + category descriptions)
- Output: ~200 tokens (categorization JSON)
- Cost per order (Haiku): ~$0.0008 (less than a tenth of a cent)
- 100 orders/day = ~$0.08/day = $2.40/month
- 500 orders/day = ~$0.40/day = $12/month

**Optimization strategies:**
- Cache categorizations for identical product names
- Batch multiple orders in single API call when possible
- Use Haiku for most orders, Sonnet only for low-confidence retry

### Implementation Code Example (Node.js)

```javascript
import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

async function categorizeAmazonOrder(order, enabledCategories) {
  // Build category descriptions for prompt
  const categoryList = enabledCategories.map(cat => 
    `- ${cat.name}: ${cat.description}`
  ).join('\n');

  // Build items list for prompt
  const itemsList = order.items.map((item, idx) => 
    `${idx + 1}. "${item.name}" - $${item.price}`
  ).join('\n');

  const message = await anthropic.messages.create({
    model: "claude-3-5-haiku-20241022",
    max_tokens: 1024,
    system: `You are a transaction categorization assistant. Your task is to categorize Amazon purchase items into budget categories based on the provided category descriptions.

For each item, determine the most appropriate category based on:
1. The item name and description
2. The category descriptions provided
3. Common sense about how people budget

Rules:
- Whole Foods and Amazon Fresh orders should ALWAYS be categorized as "Groceries" with NO item-level breakdown
- For Amazon.com orders, categorize each item individually
- Each item must map to exactly one category
- If unsure between categories, choose the most specific match
- Include a confidence score (0.0-1.0)
- Provide brief reasoning for your choice

Respond with valid JSON only, no other text.`,
    messages: [
      {
        role: "user",
        content: `Categorize these items from an ${order.merchant} order totaling $${order.total_amount}:

Items:
${itemsList}

Available Categories:
${categoryList}

Return JSON in this format:
{
  "categorizations": [
    {
      "item_name": "item name here",
      "category_id": "cat_123",
      "category_name": "Category Name",
      "confidence": 0.95,
      "reasoning": "brief explanation"
    }
  ]
}`
      }
    ]
  });

  // Extract and parse response
  const responseText = message.content[0].text;
  const categorizations = JSON.parse(responseText);

  return categorizations;
}
```

### Fallback Strategy (Non-LLM)

**If LLM is not available or fails:**
1. Simple keyword matching against category descriptions
2. Use product category from ProductMappings (learned from past corrections)
3. Flag everything as low-confidence for manual review
4. Fall back to uncategorized

**Basic Keyword Matching Implementation:**
```javascript
function keywordMatch(itemName, categories) {
  const itemLower = itemName.toLowerCase();
  const scores = {};

  for (const category of categories) {
    // Extract keywords from description
    const keywords = category.description.toLowerCase()
      .split(/[,\s]+/)
      .filter(word => word.length > 3); // Skip short words
    
    // Count keyword matches
    let score = 0;
    for (const keyword of keywords) {
      if (itemLower.includes(keyword)) {
        score++;
      }
    }
    scores[category.id] = score;
  }

  // Return category with highest score
  const bestCategory = Object.entries(scores)
    .sort(([,a], [,b]) => b - a)[0];
  
  return {
    category_id: bestCategory[0],
    confidence: Math.min(bestCategory[1] / 5, 0.7) // Cap at 0.7 for keyword matching
  };
}
```

This approach works but is significantly less accurate than LLM.

### Monitoring & Improvement

**Track metrics:**
- LLM confidence score distribution
- User correction rate by confidence bucket
- Most frequently corrected categories
- LLM cost per transaction
- API latency and error rates

**Continuous improvement:**
- When user corrects a categorization, log the correction
- Periodically review low-confidence items
- Update category descriptions based on correction patterns
- A/B test between Haiku and Sonnet for cost/accuracy tradeoff
- **Grocery orders (Whole Foods/Amazon Fresh):**
  - DO NOT itemize individual products (no bananas, chicken, etc. line items)
  - Categorize entire order as single "Groceries" amount
  - Simpler, cleaner, matches user's existing workflow
- **Non-grocery orders (Amazon.com):**
  - DO split by category when order contains diverse items
  - Group similar items (e.g., all household items together)
  - Product descriptions vary widely
  - Same product might belong in different categories based on user preference
- **Learning challenges:**
  - New products user hasn't seen before
  - User-specific preferences (one user's "Groceries" is another's "Health & Wellness")
- Solution approach:
  - Merchant-based rules (Whole Foods → Groceries, no split)
  - Keyword matching on category notes for Amazon.com orders
  - Machine learning on user corrections over time
  - Confidence scoring
  - Conservative approach (flag low-confidence items)
  - Priority system when multiple categories match

**5. Category Notes Bidirectional Sync**
- **YNAB note field character limit:** 200 characters
- **Sync timing challenges:**
  - User edits note in app → must push to YNAB API
  - User edits note in YNAB → must detect and pull changes
  - Conflict resolution if edited in both places simultaneously
- **Sync frequency:**
  - Automatic sync during daily processing runs
  - Manual "Sync Now" trigger available
  - Real-time sync on save (optional, API rate limits permitting)
- **Conflict handling:**
  - Timestamp-based: most recent edit wins
  - Flag conflicts for user review
  - Never silently overwrite without user awareness
- Solution approach:
  - Track last_synced_at timestamp per category
  - Compare local vs YNAB timestamps to detect changes
  - Sync status indicator (synced/pending/conflict)
  - Queue-based sync to handle rate limits
  - Retry logic for failed syncs

**6. Rate Limiting & API Constraints**
- YNAB API has rate limits (~200 requests/hour)
- Amazon scraping must be throttled to avoid detection
- Multiple Amazon accounts means more requests
- **Category note syncs add to YNAB API usage**
  - Reading all category notes during sync
  - Writing updated notes when user makes changes
  - Must be efficient to preserve rate limit budget for transactions
- Solution:
  - Batch operations where possible
  - Cache Amazon order data with TTL
  - Cache YNAB category notes, only sync on changes
  - Queue-based processing with retry logic
  - Respect rate limits with exponential backoff
  - Distribute Amazon account fetching across time
  - Only sync changed category notes (compare timestamps)

**7. Scope Management Complexity**
- Users can configure which accounts, payees, categories to include
- Configuration affects what transactions are fetched and how they're processed
- Must efficiently filter at query time
- Solution:
  - Database indexes on scope-related fields
  - Scope validation before processing
  - Clear UI feedback when scope excludes transactions

### Security & Privacy
- OAuth 2.0 for YNAB authentication
- Encrypted storage of Amazon credentials (AES-256)
- No storage of full transaction details beyond matching metadata
- User data isolation (row-level security in database)
- HTTPS for all communications
- Secure environment variables for API keys
- Regular security audits of dependencies
- **Multi-account considerations:**
  - Prevent cross-user Amazon account access
  - Audit logging for account connections/disconnections
  - Secure session management for browser automation

### Performance Considerations
- Process transactions in batches
- Cache Amazon order data (with TTL)
- Optimize database queries (indexes on user_id, dates, scope fields)
- Lazy-load frontend data (pagination for large category lists)
- Background processing for heavy operations
- **Multi-account optimizations:**
  - Parallel processing of different Amazon accounts
  - Shared rate limiting pool management
  - Connection pooling for database

## Success Metrics

**Primary Metrics:**
- **Categorization accuracy**: % of auto-categorized transactions that don't require manual correction
- **Time saved**: Estimated minutes saved per week (based on transaction volume)
- **Match rate**: % of YNAB transactions successfully matched to Amazon orders
- **Multi-account usage**: % of users with 2+ Amazon accounts connected

**Engagement Metrics:**
- Daily email open rate
- Frontend usage frequency
- Category descriptions completed (% of enabled categories with descriptions)
- Number of active users
- Scope configuration completion rate

**Learning Effectiveness:**
- Accuracy improvement over time (week-over-week)
- Reduction in correction rate for repeat products
- Confidence score trends
- Time to 90% accuracy for new users

**System Health:**
- Processing success rate
- API error rates
- Average processing time per transaction
- Match confidence distribution
- Amazon account connection success rate

## Out of Scope (V1)

- Mobile app (frontend is web-only)
- Support for retailers beyond Amazon
- Budget forecasting or spending insights
- Shared budgets / multi-user YNAB accounts
- Real-time processing (daily batch is sufficient)
- Receipt image storage
- Integration with other budgeting tools
- Automatic category creation based on patterns
- Export/reporting beyond daily email
- Natural language category descriptions (AI interpretation)
- Collaborative learning across users

## Future Enhancements (Post-V1)

**Phase 2:**
- Support for other major retailers (Target, Walmart, Costco)
- Natural language queries ("Show me all pet spending from Amazon")
- Browser extension for real-time feedback while shopping
- Mobile app for on-the-go review
- Push notifications for processing completion/errors
- Slack/Discord integration for notifications

**Phase 3:**
- Automatic category suggestions based on spending patterns
- Budget alerts when category is over-spent
- Receipt OCR for non-Amazon purchases
- Shared learning across users (opt-in, privacy-preserving)
- API for third-party integrations
- Advanced analytics dashboard (spending trends, category insights)
- Rule builder (IF product contains X THEN category Y)

**Phase 4:**
- AI-powered category description generator
- Automatic anomaly detection (unusual purchases)
- Predictive categorization (suggesting categories before purchase)
- Integration with grocery delivery apps
- Family/shared budget support with role-based permissions

## Open Questions & Decisions Needed

1. **Amazon data access method**: Browser automation vs. email parsing vs. third-party service?
2. **Processing frequency**: Daily batch vs. multiple times per day? User-configurable?
3. **Confidence threshold defaults**: How conservative should initial categorization be?
4. **Default flag color**: Should Orange be the default, or let users choose during onboarding?
5. **Failed matches**: Auto-flag in YNAB or just email notification? Or both?
6. **Category description format**: Free text vs. structured fields vs. hybrid?
7. **Pricing model**: Free tier + paid plans? Subscription? One-time payment?
8. **Multi-account limits**: How many Amazon accounts should be supported per user?
9. **Historical processing**: How far back should we allow users to process on initial setup?
10. **Scope UI**: Should scope selection be part of onboarding or separate settings?
11. **Whole Foods itemization**: Should users have the option to override and get detailed itemization if desired?
12. **Amazon.com grouping**: How granular should category grouping be? (e.g., group all books vs. split fiction/non-fiction?)

## Next Steps

1. **Validate Amazon data access**: 
   - Test Puppeteer automation with real Amazon account
   - Test with multiple Amazon accounts simultaneously
   - Evaluate third-party services if available
   - Consider email parsing as fallback

2. **YNAB API prototype**:
   - Build basic integration for reading/writing transactions
   - Test split transaction creation
   - Verify label/flag functionality
   - Test multi-account scenarios

3. **Set up Anthropic API integration**:
   - Create Anthropic account and generate API key
   - Install Anthropic SDK (`npm install @anthropic-ai/sdk`)
   - Test basic categorization with sample Amazon orders
   - Validate JSON response parsing
   - Implement error handling and retries
   - Test cost/performance with Haiku vs Sonnet
   - Build caching layer for repeat products

4. **Design database schema**:
   - Finalize data models with multi-account support
   - Add LLMCategorizations table for tracking reasoning
   - Set up development database
   - Create migrations
   - Plan for scope configuration storage

4. **Create frontend wireframes**:
   - Account connections page
   - Processing scope configuration (Payees settings)
   - Category management UI with note sync indicators
   - Dashboard (Overview)
   - User onboarding flow
   - Settings/preferences page

5. **Build categorization algorithm prototype**:
   - Simple keyword matching based on category notes
   - Test with sample data and various note formats
   - Establish confidence scoring approach
   - Test with different category note styles (concise vs detailed)

6. **Set up development environment**:
   - Vercel project structure
   - Next.js scaffolding
   - PostgreSQL setup
   - Environment configuration
   - Set up multiple test Amazon accounts

7. **Plan onboarding experience**:
   - Define required vs. optional setup steps
   - Create sample category note templates (under 200 chars)
   - Build category note templates library
   - Design scope selection wizard
   - Plan initial YNAB category note sync flow
