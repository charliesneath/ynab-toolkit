"""
Evaluate categorization quality.

Usage:
    # Evaluate a processed JSON file
    python eval_categorizations.py data/processed/chase-amazon/2025-all.json

    # Evaluate all processed files
    python eval_categorizations.py --all

    # Run golden set test only (tests the categorizer directly)
    python eval_categorizations.py --golden-only
"""

import argparse
import csv
import json
import os
import re
import random
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# =============================================================================
# KEYWORD RULES - Items containing these keywords should map to these categories
# Uses word boundary matching to avoid false positives like "breastmilk" -> "milk"
# =============================================================================

def word_boundary_match(keyword: str, text: str) -> bool:
    """Check if keyword exists as a whole word/phrase in text."""
    # Use word boundaries (\b) to match whole words only
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, text, re.IGNORECASE))


# =============================================================================
# BRAND NAME RULES - Known brands and their correct categories
# When a brand is detected, trust the assigned category over ingredient keywords
# =============================================================================
BRAND_CATEGORIES = {
    # Snack brands - don't flag for ingredient keywords
    "cheez-it": "Snacks",
    "goldfish": "Snacks",
    "annie's": "Snacks",
    "pirate's booty": "Snacks",
    "pirate brands": "Snacks",
    "hippeas": "Snacks",
    "harvest snaps": "Snacks",
    "special k": "Snacks",
    "cheerios": "Snacks",
    "kind bar": "Snacks",
    "clif bar": "Snacks",
    "rxbar": "Snacks",
    "larabar": "Snacks",
    "nature valley": "Snacks",
    "quaker": "Snacks",
    "kellogg": "Snacks",
    "general mills": "Snacks",
    "nabisco": "Snacks",
    "pepperidge farm": "Snacks",
    "stonyfield yogis": "Snacks",
    "happy baby yogis": "Snacks",
    "plum organics puffs": "Snacks",
    "gerber puffs": "Snacks",
    # Baby/Kids food brands
    "happy baby": "🎒 Gear",
    "plum organics": "🎒 Gear",
    "gerber": "🎒 Gear",
    "earth's best": "🎒 Gear",
    "beech-nut": "🎒 Gear",
    # Beverage brands
    "lacroix": "Beverages",
    "spindrift": "Beverages",
    "topo chico": "Beverages",
    "polar seltzer": "Beverages",
    "olipop": "Beverages",
    "gt's kombucha": "Beverages",
    "kevita": "Beverages",
    # Coffee brands
    "peet's coffee": "Coffee",
    "starbucks": "Coffee",
    "dunkin": "Coffee",
    "lavazza": "Coffee",
    "illy": "Coffee",
    # Personal care brands - don't flag for food keywords
    "dr. bronner": "Personal Care",
    "mrs. meyer": "Kitchen & Cleaning Supplies",
    "seventh generation": "Kitchen & Cleaning Supplies",
    "method": "Kitchen & Cleaning Supplies",
    # Cleaning brands
    "cascade": "Kitchen & Cleaning Supplies",
    "dawn": "Kitchen & Cleaning Supplies",
    "tide": "Kitchen & Cleaning Supplies",
    # Toothpaste/personal care with flavors
    "hello natural": "Personal Care",
    "tom's of maine": "Personal Care",
    "crest": "Personal Care",
    "colgate": "Personal Care",
    # Baby food brands (pouches with fruit/veggie names)
    "happy tot": "🎒 Gear",
    "once upon a farm": "🎒 Gear",
    "serenity kids": "🎒 Gear",
    "peter rabbit organics": "🎒 Gear",
}

# Categories that are acceptable "catch-all" alternatives
# If an item is in one of these, don't flag for specific subcategory keywords
CATCH_ALL_CATEGORIES = {
    "🍌Groceries": ["Dairy", "Vegetables", "Fruit", "Berries", "Meat", "Beans", "Bakery"],
    "🍌groceries": ["Dairy", "Vegetables", "Fruit", "Berries", "Meat", "Beans", "Bakery"],
    "Groceries": ["Dairy", "Vegetables", "Fruit", "Berries", "Meat", "Beans", "Bakery"],
}


def get_brand_category(item: str) -> str | None:
    """Check if item matches a known brand and return expected category."""
    item_lower = item.lower()
    for brand, category in BRAND_CATEGORIES.items():
        if brand in item_lower:
            return category
    return None


# Words that commonly cause false positives - skip these in keyword matching
FALSE_POSITIVE_PATTERNS = [
    # "milk" in product names that aren't dairy
    (r"breastmilk", "milk"),
    (r"oat\s*milk", "milk"),  # oat milk is not dairy
    (r"almond\s*milk", "milk"),
    (r"coconut\s*milk", "milk"),
    (r"soy\s*milk", "milk"),
    # "pepper" in non-vegetable contexts
    (r"peppermint", "pepper"),
    (r"dr\.?\s*pepper", "pepper"),
    (r"pepper\s*jack", "pepper"),  # cheese, not vegetable
    # "ham" in brand names
    (r"gotham", "ham"),
    (r"graham", "ham"),
    (r"birmingham", "ham"),
    # "lime" in non-fruit contexts
    (r"sublime", "lime"),
    (r"slime", "lime"),
    # "orange" as color not fruit
    (r"orange\s*(color|flavored|scent)", "orange"),
    # "lemon" in non-fruit contexts
    (r"lemon\s*(scent|fragrance|verbena)", "lemon"),
    # "cherry" in non-fruit contexts
    (r"cherry\s*(blossom|wood|tomato)", "cherry"),
    # "corn" in non-vegetable contexts
    (r"unicorn", "corn"),
    (r"corner", "corn"),
    (r"acorn", "corn"),
    # "pea" false positives
    (r"peace", "pea"),
    (r"speak", "pea"),
    # Chocolate/candy with fruit names
    (r"chocolate.*(?:orange|raspberry|strawberry|cherry)", None),  # Skip fruit check for chocolate
    # Flavored products (toothpaste, drinks, etc.) - fruit name is flavor not content
    (r"(?:toothpaste|mouthwash|lip balm).*(?:watermelon|strawberry|grape|cherry|orange)", None),
    (r"(?:watermelon|strawberry|grape|cherry).*(?:flavor|toothpaste|mouthwash)", None),
    # Juice is a beverage, not fruit
    (r"juice", None),  # Skip fruit checks for juice products
    # Baby food pouches with fruit/veggie ingredients
    (r"baby food", None),
    (r"organic.*pouch", None),
    # Nut butters are not dairy
    (r"peanut\s*butter", "butter"),
    (r"almond\s*butter", "butter"),
    (r"cashew\s*butter", "butter"),
    (r"sunflower\s*butter", "butter"),
    (r"sun\s*butter", "butter"),
    # Flavored yogurt - fruit name is flavor, yogurt is dairy
    (r"yogurt|yoghurt", None),  # Skip fruit checks for yogurt products
    # Kitchenware with fruit names
    (r"spoons?|knife|fork|utensil", None),  # Skip fruit checks for utensils
    # Diaper cream/rash products can be Personal Care
    (r"diaper\s*(rash|cream)", "diaper"),
    # Cheese-flavored products are not dairy
    (r"cheese\s*puff", "cheese"),
    (r"cheddar\s*(bunnie|cracker|puff|snack)", "cheddar"),
    (r"cheese\s*pizza", "cheese"),  # Pizza with cheese is pizza, not dairy
    # Avocado oil/dressing is not fruit
    (r"avocado\s*(oil|dressing|marinade|mayo)", "avocado"),
    # Shea butter is not dairy (personal care)
    (r"shea\s*butter", "butter"),
    (r"cocoa\s*butter", "butter"),
    (r"body\s*butter", "butter"),
    # Fruit-flavored beverages are beverages
    (r"(hydration|electrolyte|liquid\s*i\.?v).*peach", "peach"),
    (r"(hydration|electrolyte|liquid\s*i\.?v).*lemon", "lemon"),
    # Garlic in cheese/dressing is fine
    (r"garlic.*cheese|cheese.*garlic", "garlic"),
    (r"boursin", "garlic"),  # Boursin is garlic cheese, garlic is not the category
    # Garlic as ingredient in other products
    (r"garlic\s*(bread|butter|sauce|oil|powder|salt|knot)", "garlic"),
    (r"roasted\s*garlic", "garlic"),
    (r"(bread|roll|bun|knot).*garlic", "garlic"),
    # Oatmeal in baked goods/bars is snacks, not grains
    (r"oatmeal\s*(cookie|bar|muffin|cake)", "oatmeal"),
    (r"(cookie|bar|muffin).*oat", "oatmeal"),
    # Beef broth is Pantry, not Meat
    (r"beef\s*(broth|stock)", "beef"),
    # Minced/roasted garlic is Pantry
    (r"(minced|roasted|crushed)\s*garlic", "garlic"),
    # Cheese/butter in product names that aren't dairy
    (r"cheese\s*dressing", "cheese"),
    (r"blue\s*cheese\s*dip", "cheese"),
    (r"crouton", "butter"),  # Butter garlic croutons
    (r"crouton", "garlic"),  # Garlic croutons are snacks, not vegetables
    (r"peanut\s*butter", "butter"),
    # Apple cider vinegar is not apples
    (r"apple\s*cider\s*vinegar", "apple"),
    (r"apple\s*cider", "apple"),
    # Avocado in smoothies/drinks is acceptable as beverage
    (r"(smoothie|drink|beverage).*avocado", "avocado"),
    (r"avocado.*(smoothie|drink)", "avocado"),
    # Banana in cosmetics/sunscreen brand names - not actual bananas
    (r"banana\s*bright", "banana"),  # Ole Henriksen Banana Bright Eye Crème
    (r"banana\s*boat", "banana"),  # Banana Boat sunscreen
    # GoGo squeeZ fruit snacks are snacks, not fruit
    (r"gogo\s*squeez", "banana"),
    (r"gogo\s*squeez", "apple"),
    # Marinara/pasta sauce is Pantry, not Pasta & Rices
    (r"marinara\s*sauce", "pasta"),
    (r"pasta\s*sauce", "pasta"),
    # Sichuan peppercorns recipe mentions tofu but it's a spice
    (r"sichuan\s*peppercorn", "tofu"),
    (r"szechuan\s*peppercorn", "tofu"),
    # Cheese tortellini is pasta, not dairy
    (r"tortellini", "cheese"),
    (r"ravioli", "cheese"),
    # Cauliflower/veggie snacks are snacks, not vegetables
    (r"cauliflower\s*(stalk|chip|puff|cracker)", "cauliflower"),
    (r"from the ground up", "cauliflower"),
    # Butter dish is kitchenware, not dairy
    (r"butter\s*dish", "butter"),
    # Chili crunch/oil with garlic is a condiment, not vegetables
    (r"chili\s*crunch", "garlic"),
    (r"chili\s*oil", "garlic"),
]


def is_false_positive(item: str, keyword: str) -> bool:
    """Check if this keyword match is a known false positive."""
    item_lower = item.lower()
    for pattern, kw in FALSE_POSITIVE_PATTERNS:
        if kw is None or kw == keyword:
            if re.search(pattern, item_lower):
                return True
    return False


KEYWORD_RULES = {
    # Meat keywords - should NEVER be Apples, Fruit, Beverages, etc.
    "Meat": [
        "bacon", "chicken breast", "chicken thigh", "chicken nugget",
        "beef", "pork", "turkey", "sausage", "ham steak", "sliced ham",
        "pepperoni", "salami", "prosciutto", "pancetta", "lamb", "veal",
        "ground beef", "ground turkey", "meatball",
        # Note: broth/stock is now Pantry, not Meat
    ],
    # Pantry keywords - broth, stock, shelf-stable items
    "Pantry": [
        "chicken broth", "beef broth", "chicken stock", "beef stock",
        "bone broth", "vegetable broth", "vegetable stock",
    ],
    # Plant Protein
    "Plant Protein": [
        "tofu", "extra firm tofu", "firm tofu", "silken tofu", "tempeh", "seitan",
    ],
    # Pasta & Rices (YNAB category name)
    "Pasta & Rices": [
        "pasta", "spaghetti", "penne", "linguine", "fettuccine",
        "rice", "brown rice", "white rice", "jasmine rice",
        "quinoa", "couscous", "farro", "barley", "oats", "oatmeal",
    ],
    # Dairy keywords - yogurt, milk, butter, cream (NOT cheese)
    "Dairy": [
        "yogurt", "greek yogurt", "whole milk", "2% milk", "skim milk",
        "butter", "sour cream", "heavy cream",
    ],
    # Cheese keywords - dedicated category
    "Cheese": [
        "cheese", "cream cheese", "cottage cheese", "ricotta",
        "mozzarella", "cheddar", "parmesan", "feta", "brie",
        "gouda", "provolone", "swiss cheese", "babybel", "gorgonzola",
    ],
    # Vegetables keywords - be specific
    "Vegetables": [
        "broccoli florets", "organic broccoli", "frozen broccoli",
        "baby spinach", "organic spinach", "frozen spinach",
        "kale", "romaine lettuce", "romaine hearts", "arugula", "celery",
        "cucumber", "english cucumber", "bell pepper", "green pepper", "red pepper",
        "onion", "garlic", "zucchini", "squash", "cauliflower",
        "asparagus", "brussels sprout", "cabbage",
        "green peas", "frozen peas", "green beans",
        "frozen vegetables", "mixed vegetables",
    ],
    # Bananas
    "Bananas": [
        "banana", "organic banana",
    ],
    # Fruit keywords - specific varieties
    "Fruit": [
        "mango", "pineapple", "watermelon", "cantaloupe", "honeydew",
        "avocado", "pear", "peach", "nectarine", "plum", "apricot",
        "grapes", "kiwi", "papaya", "guava",
        "navel orange", "mandarin orange", "tangerine", "clementine",
        "grapefruit",
    ],
    # Berries - specific
    "Berries": [
        "strawberries", "organic strawberries",
        "raspberries", "organic raspberries",
        "blueberries", "organic blueberries",
        "blackberries", "organic blackberries",
        "cranberries",
    ],
    # Apples - very specific to avoid "Applegate"
    "Apples": [
        "granny smith apple", "honeycrisp apple", "fuji apple", "gala apple",
        "pink lady apple", "golden delicious apple", "red delicious apple",
        "organic apple",
    ],
    # Beans
    "Beans": [
        "black beans", "kidney beans", "pinto beans", "garbanzo beans",
        "chickpeas", "lentils", "refried beans", "cannellini beans",
    ],
    # Coffee
    "Coffee": [
        "coffee beans", "ground coffee", "whole bean coffee",
        "peet's coffee", "starbucks coffee",
    ],
    # Diapers & Wipes
    "Diapers & Wipes": [
        "diaper", "diapers", "baby wipes", "diaper pail", "diaper genie",
        "munchkin pail", "ubbi refill", "diaper cream", "diaper rash",
    ],
}

# Keywords that should NEVER map to certain categories (negative rules)
NEGATIVE_RULES = {
    "Apples": [
        "applegate",  # Applegate is a meat brand, not apples
    ],
    "Beverages": [
        "broth", "stock", "bone broth",  # These are Pantry, not Beverages
    ],
    "Frozen": [
        "broccoli", "peas", "spinach", "vegetables", "blueberries", "sausage",  # Should be their actual categories
    ],
    "Canned Items": [
        "black beans", "kidney beans", "pinto beans", "garbanzo beans", "chickpeas",  # Should be Beans
    ],
    "Dairy": [
        "breastmilk", "oat milk", "almond milk", "coconut milk", "soy milk",
    ],
}


def load_golden_set(filepath: str = "data/golden_set.csv") -> list[dict]:
    """Load golden set of known-correct categorizations."""
    golden = []
    if not os.path.exists(filepath):
        return golden

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = row.get("item", "").strip()
            if item and not item.startswith("#"):
                golden.append({
                    "item": item,
                    "expected": row.get("expected_category", "").strip(),
                    "notes": row.get("notes", "").strip(),
                })
    return golden


def load_category_cache(cache_dir: str = "data/processed/chase-amazon") -> dict:
    """Load the current category cache."""
    cache_path = os.path.join(cache_dir, "category_cache.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            return json.load(f)
    return {}


def normalize_item_name(name: str) -> str:
    """Normalize item name for matching (first 50 chars, lowercase)."""
    return name[:50].lower().strip()


def check_keyword_rules(item: str, category: str) -> list[str]:
    """Check if an item violates keyword rules. Returns list of issues."""
    issues = []

    # Strip emoji from category for comparison
    cat_stripped = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF]+\s*', '', category)

    # Check if item matches a known brand - if so, trust the brand's category
    brand_cat = get_brand_category(item)
    if brand_cat:
        brand_cat_stripped = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF]+\s*', '', brand_cat)
        # If categorized correctly for the brand, skip all keyword checks
        if cat_stripped.lower() == brand_cat_stripped.lower():
            return []
        # If brand category doesn't match, that's a real issue
        # But don't flag - brands can have multiple product types

    # Check positive rules - if item contains keyword, should be in that category
    for expected_cat, keywords in KEYWORD_RULES.items():
        for keyword in keywords:
            # Use word boundary matching to avoid false positives
            if word_boundary_match(keyword, item):
                # Skip if this is a known false positive
                if is_false_positive(item, keyword.split()[0]):  # Check first word of keyword
                    continue

                # Skip if item is from a known brand with a different expected category
                # (e.g., Cheez-It contains "cheese" but is correctly a Snack)
                if brand_cat:
                    continue

                expected_stripped = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF]+\s*', '', expected_cat)

                # Check if category matches expected (including subcategories like "Fruit (avocado)")
                cat_matches = (
                    cat_stripped.lower() == expected_stripped.lower() or
                    cat_stripped.lower().startswith(expected_stripped.lower() + " ") or
                    cat_stripped.lower().startswith(expected_stripped.lower() + "(")
                )

                if not cat_matches:
                    # Check if it's an acceptable alternative (e.g., Carrots for carrots instead of Vegetables)
                    acceptable_subs = {
                        "Vegetables": ["Carrots", "Kale", "Bakery", "Pantry"],  # Garlic bread, minced garlic
                        "Fruit": ["Apples", "Bananas", "Berries", "Vegetables"],  # Avocado sometimes in Vegetables
                        "Apples": ["Fruit"],  # Apples in Fruit is acceptable
                        "Berries": ["Fruit"],  # Berries as Fruit acceptable
                        "Meat": ["Meats", "Chicken", "Beef", "Seafood", "Pantry"],  # Broth in Pantry
                        "Dairy": ["Cheese", "Bakery"],  # Butter in bakery items
                        "Cheese": ["Dairy"],  # Cheese/Dairy overlap acceptable
                        "Pasta & Rices": ["Snacks"],  # Oatmeal bars in Snacks only
                        # Beans must be Beans, not Pantry
                        "Coffee": ["Beverages"],  # Coffee in Beverages acceptable
                    }
                    is_acceptable = False
                    if expected_cat in acceptable_subs:
                        if cat_stripped in acceptable_subs[expected_cat]:
                            is_acceptable = True

                    # Check if category is a catch-all that covers this specific type
                    for catch_all, covers in CATCH_ALL_CATEGORIES.items():
                        if category == catch_all and expected_cat in covers:
                            is_acceptable = True
                            break

                    if not is_acceptable:
                        issues.append(f"Contains '{keyword}' but categorized as '{category}' (expected '{expected_cat}')")
                break  # Only report first matching keyword

    # Check negative rules - if item contains keyword, should NOT be in that category
    for forbidden_cat, keywords in NEGATIVE_RULES.items():
        cat_stripped = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF]+\s*', '', category)
        if cat_stripped.lower() == forbidden_cat.lower():
            for keyword in keywords:
                if word_boundary_match(keyword, item):
                    issues.append(f"Contains '{keyword}' but incorrectly categorized as '{category}'")
                    break

    return issues


def evaluate_golden_set(category_cache: dict, golden_set: list[dict]) -> dict:
    """Test categorizations against golden set."""
    results = {
        "total": len(golden_set),
        "matched": 0,
        "mismatched": 0,
        "missing": 0,
        "errors": [],
    }

    for item in golden_set:
        item_name = item["item"]
        expected = item["expected"]
        key = normalize_item_name(item_name)

        if key not in category_cache:
            results["missing"] += 1
            results["errors"].append({
                "item": item_name,
                "expected": expected,
                "actual": "(not in cache)",
                "notes": item.get("notes", ""),
            })
        else:
            actual = category_cache[key]
            # Strip emoji for comparison
            actual_stripped = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF]+\s*', '', actual)
            expected_stripped = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF]+\s*', '', expected)

            if actual_stripped.lower() == expected_stripped.lower():
                results["matched"] += 1
            else:
                results["mismatched"] += 1
                results["errors"].append({
                    "item": item_name,
                    "expected": expected,
                    "actual": actual,
                    "notes": item.get("notes", ""),
                })

    return results


def evaluate_processed_file(filepath: str) -> dict:
    """Evaluate a processed JSON file for categorization issues."""
    with open(filepath, "r") as f:
        data = json.load(f)

    # Handle both formats: list of transactions or dict with "transactions" key
    if isinstance(data, dict):
        transactions = data.get("transactions", [])
    else:
        transactions = data

    results = {
        "file": filepath,
        "total_transactions": len(transactions),
        "total_items": 0,
        "keyword_violations": [],
        "category_distribution": defaultdict(int),
        "samples_by_category": defaultdict(list),
    }

    for txn in transactions:
        for split in txn.get("splits", []):
            category = split.get("category", "Unknown")
            for item in split.get("items", []):
                # Items can be strings or dicts with "name" key
                if isinstance(item, str):
                    item_name = item
                else:
                    item_name = item.get("name", "")
                if not item_name:
                    continue

                results["total_items"] += 1
                results["category_distribution"][category] += 1

                # Store sample (up to 10 per category)
                if len(results["samples_by_category"][category]) < 10:
                    results["samples_by_category"][category].append(item_name)

                # Check keyword rules
                issues = check_keyword_rules(item_name, category)
                if issues:
                    results["keyword_violations"].append({
                        "item": item_name,
                        "category": category,
                        "issues": issues,
                        "order_id": txn.get("memo", ""),
                    })

    return results


def print_report(golden_results: dict, file_results: list[dict]):
    """Print evaluation report."""
    print("\n" + "=" * 70)
    print("CATEGORIZATION EVALUATION REPORT")
    print("=" * 70)

    # Golden set results
    if golden_results["total"] > 0:
        print("\n## GOLDEN SET ACCURACY")
        print("-" * 40)
        accuracy = golden_results["matched"] / golden_results["total"] * 100
        print(f"Total items:  {golden_results['total']}")
        print(f"Matched:      {golden_results['matched']} ({accuracy:.1f}%)")
        print(f"Mismatched:   {golden_results['mismatched']}")
        print(f"Missing:      {golden_results['missing']}")

        if golden_results["errors"]:
            print("\nErrors:")
            for err in golden_results["errors"][:20]:  # Show first 20
                print(f"  - {err['item'][:50]}")
                print(f"    Expected: {err['expected']}, Got: {err['actual']}")
                if err.get("notes"):
                    print(f"    Note: {err['notes']}")

    # File results
    for result in file_results:
        print(f"\n## FILE: {result['file']}")
        print("-" * 40)
        print(f"Transactions: {result['total_transactions']}")
        print(f"Total items:  {result['total_items']}")

        # Keyword violations
        violations = result["keyword_violations"]
        if violations:
            print(f"\n### KEYWORD VIOLATIONS ({len(violations)} issues)")
            for v in violations[:30]:  # Show first 30
                print(f"  - {v['item'][:60]}")
                print(f"    Category: {v['category']}")
                for issue in v['issues']:
                    print(f"    Issue: {issue}")
        else:
            print("\n### KEYWORD VIOLATIONS: None found!")

        # Category distribution
        print("\n### CATEGORY DISTRIBUTION")
        dist = sorted(result["category_distribution"].items(), key=lambda x: -x[1])
        for cat, count in dist[:25]:  # Top 25 categories
            print(f"  {count:4d}  {cat}")

        # Random samples per category
        print("\n### RANDOM SAMPLES (5 per category)")
        for cat, samples in sorted(result["samples_by_category"].items()):
            print(f"\n  {cat}:")
            random_samples = random.sample(samples, min(5, len(samples)))
            for s in random_samples:
                print(f"    - {s[:70]}")

    print("\n" + "=" * 70)
    print("END OF REPORT")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Evaluate categorization quality")
    parser.add_argument("files", nargs="*", help="JSON files to evaluate")
    parser.add_argument("--all", action="store_true", help="Evaluate all processed JSON files")
    parser.add_argument("--golden-only", action="store_true", help="Only run golden set test")
    parser.add_argument("--cache-dir", default="data/processed/chase-amazon", help="Category cache directory")
    args = parser.parse_args()

    # Load category cache
    category_cache = load_category_cache(args.cache_dir)
    print(f"Loaded {len(category_cache)} items from category cache")

    # Load and evaluate golden set
    golden_set = load_golden_set()
    print(f"Loaded {len(golden_set)} items from golden set")
    golden_results = evaluate_golden_set(category_cache, golden_set)

    if args.golden_only:
        print_report(golden_results, [])
        return

    # Find files to evaluate
    files_to_eval = []
    if args.all:
        cache_dir = Path(args.cache_dir)
        files_to_eval = list(cache_dir.glob("*-all.json"))
    elif args.files:
        files_to_eval = [Path(f) for f in args.files]

    # Evaluate each file
    file_results = []
    for filepath in files_to_eval:
        if filepath.exists():
            print(f"Evaluating {filepath}...")
            result = evaluate_processed_file(str(filepath))
            file_results.append(result)

    # Print report
    print_report(golden_results, file_results)

    # Summary for CI/automated checks
    total_violations = sum(len(r["keyword_violations"]) for r in file_results)
    if golden_results["mismatched"] > 0 or total_violations > 0:
        print(f"\n⚠️  ISSUES FOUND: {golden_results['mismatched']} golden set errors, {total_violations} keyword violations")
        return 1
    else:
        print("\n✓ All checks passed!")
        return 0


if __name__ == "__main__":
    exit(main())
