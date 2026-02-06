"""
Patterns that indicate private/customer-specific data.

Used to validate that skills, documentation, and committed files
don't contain private information that should stay local.
"""

import re
from typing import List, Tuple

# Patterns that indicate private data - should NOT appear in shared files
PRIVATE_DATA_PATTERNS = [
    # UUIDs (account IDs, budget IDs)
    (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "UUID (possible account/budget ID)"),

    # Credit card last 4 digits in specific contexts
    (r"(?:card|account|ending)\s*(?:in|#|:)?\s*\d{4}", "Card/account number reference"),

    # Large specific dollar amounts (likely real transactions)
    (r"\$\d{2,},\d{3}\.\d{2}", "Large specific dollar amount"),

    # Real company names as payees (add your employers, etc.)
    # These should be configured per-project in CLAUDE.md or .env

    # Email addresses
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "Email address"),

    # Phone numbers
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "Phone number"),

    # Street addresses (number + street name pattern)
    (r"\b\d+\s+[A-Z][a-z]+\s+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard)\b", "Street address"),

    # SSN pattern
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN pattern"),

    # Specific date + large amount (likely real transaction)
    (r"20\d{2}-\d{2}-\d{2}.*\$\d{1,},\d{3}", "Dated transaction with large amount"),
]

# Paths that should be checked for private data
PATHS_TO_CHECK = [
    ".claude/skills/",
    "docs/",
    "README.md",
    "CLAUDE.md",
]

# Paths that are allowed to contain private data (local config)
EXEMPT_PATHS = [
    ".env",
    ".claude/settings.local.json",
    "data/",
    "config.py",  # Local config with account IDs
]


def check_for_private_data(content: str, filename: str = "") -> List[Tuple[str, str, str]]:
    """
    Check content for private data patterns.

    Args:
        content: Text content to check
        filename: Optional filename for context

    Returns:
        List of (matched_text, pattern_description, line_context) tuples
    """
    findings = []

    for pattern, description in PRIVATE_DATA_PATTERNS:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            # Get line context
            start = content.rfind('\n', 0, match.start()) + 1
            end = content.find('\n', match.end())
            if end == -1:
                end = len(content)
            line = content[start:end].strip()

            findings.append((match.group(), description, line))

    return findings


def should_check_path(filepath: str) -> bool:
    """Determine if a file path should be checked for private data."""
    # Skip exempt paths
    for exempt in EXEMPT_PATHS:
        if filepath.startswith(exempt) or filepath.endswith(exempt):
            return False

    # Check paths that should be validated
    for check_path in PATHS_TO_CHECK:
        if filepath.startswith(check_path) or filepath.endswith(check_path):
            return True

    return False


def validate_file(filepath: str, content: str) -> Tuple[bool, List[str]]:
    """
    Validate a file for private data.

    Returns:
        (is_valid, list_of_warnings)
    """
    if not should_check_path(filepath):
        return True, []

    findings = check_for_private_data(content, filepath)

    if not findings:
        return True, []

    warnings = []
    for matched, description, line in findings:
        warnings.append(f"  - {description}: '{matched}' in: {line[:60]}...")

    return False, warnings


# For use as a standalone validator
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python private_data_patterns.py <file1> [file2] ...")
        sys.exit(1)

    has_errors = False

    for filepath in sys.argv[1:]:
        try:
            with open(filepath, 'r') as f:
                content = f.read()

            is_valid, warnings = validate_file(filepath, content)

            if not is_valid:
                print(f"\n⚠️  Private data found in {filepath}:")
                for warning in warnings:
                    print(warning)
                has_errors = True
        except Exception as e:
            print(f"Error reading {filepath}: {e}")

    if has_errors:
        print("\n❌ Private data check failed")
        sys.exit(1)
    else:
        print("✓ No private data patterns found")
        sys.exit(0)
