#!/usr/bin/env python3
"""
Unified CLI tool for converting bank statements to YNAB CSV format.

Supports multiple banks and file formats:
- Chase checking account PDFs
- Chase Amazon Prime Visa credit card PDFs
- Generic CSV files

Usage:
    python3 bank_to_ynab.py chase-checking data/2023*.pdf -o output.csv
    python3 bank_to_ynab.py amazon-card data/amazon/*.pdf -o output.csv
    python3 bank_to_ynab.py csv data/statements.csv -o output.csv --year 2024
"""

import sys
import argparse
import glob
from converters import (
    ChaseCheckingConverter,
    ChaseAmazonConverter,
    CSVConverter,
)


def main():
    parser = argparse.ArgumentParser(
        description='Convert bank statements to YNAB CSV format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert Chase checking PDFs for 2023
  %(prog)s chase-checking data/2023*.pdf -o ynab_chase_2023.csv

  # Convert Amazon credit card PDFs (all years)
  %(prog)s amazon-card data/amazon/*.pdf -o ynab_amazon_all.csv

  # Convert Amazon credit card PDFs (2024 only)
  %(prog)s amazon-card data/amazon/*.pdf -o ynab_amazon_2024.csv --year 2024

  # Convert CSV download
  %(prog)s csv data/chase_download.csv -o ynab_import.csv

Supported converter types:
  chase-checking    Chase checking account PDFs
  amazon-card       Chase Amazon Prime Visa credit card PDFs
  csv               Generic CSV files (auto-detects common formats)
        """
    )

    parser.add_argument(
        'converter_type',
        choices=['chase-checking', 'amazon-card', 'csv'],
        help='Type of bank statement converter to use'
    )

    parser.add_argument(
        'input_files',
        nargs='+',
        help='Input file(s) to convert (supports glob patterns like data/*.pdf)'
    )

    parser.add_argument(
        '-o', '--output',
        required=True,
        help='Output YNAB CSV file path'
    )

    parser.add_argument(
        '--year',
        type=int,
        help='Filter transactions to specific year (optional)'
    )

    parser.add_argument(
        '--date-format',
        default='%m/%d/%Y',
        help='Date format for CSV files (default: %%m/%%d/%%Y)'
    )

    args = parser.parse_args()

    # Expand glob patterns
    all_files = []
    for pattern in args.input_files:
        expanded = glob.glob(pattern)
        if expanded:
            all_files.extend(expanded)
        else:
            # Not a glob pattern, use as-is
            all_files.append(pattern)

    if not all_files:
        print(f"ERROR: No files found matching the input patterns")
        sys.exit(1)

    # Select appropriate converter
    if args.converter_type == 'chase-checking':
        converter = ChaseCheckingConverter()
        converter_name = 'Chase Checking'
    elif args.converter_type == 'amazon-card':
        converter = ChaseAmazonConverter()
        converter_name = 'Chase Amazon Prime Visa'
    elif args.converter_type == 'csv':
        converter = CSVConverter(date_format=args.date_format)
        converter_name = 'CSV Import'
    else:
        print(f"ERROR: Unknown converter type: {args.converter_type}")
        sys.exit(1)

    # Print header
    print("=" * 80)
    print(f"{converter_name} → YNAB CSV Converter")
    print("=" * 80)
    print(f"\nFound {len(all_files)} file(s):")
    for f in all_files:
        print(f"  - {f.split('/')[-1]}")

    # Convert files
    print(f"\n{'=' * 80}")
    print("Converting...")
    print("=" * 80)

    try:
        count = converter.convert(all_files, args.output, year=args.year)

        print(f"\n{'=' * 80}")
        print("✓ Conversion complete!")
        print("=" * 80)
        print(f"\nSummary:")
        print(f"  Transactions converted: {count}")
        if args.year:
            print(f"  Year filter: {args.year}")
        print(f"  Output file: {args.output}")
        print(f"\nYou can now import this CSV file into YNAB:")
        print(f"  1. Go to your YNAB account")
        print(f"  2. Select the appropriate account")
        print(f"  3. Click 'Import' and select: {args.output}")
        print("=" * 80)

    except Exception as e:
        print(f"\nERROR: Conversion failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
