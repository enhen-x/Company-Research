#!/usr/bin/env python3
"""Generate available_fields.json from TushareClient's endpoint field lists.

Scans tushare_collector.py for all _safe_call invocations, extracts the
endpoint name and requested fields, and writes a summary JSON file.

Usage:
    python3 scripts/generate_available_fields.py
    python3 scripts/generate_available_fields.py --output output/available_fields.json
"""

import argparse
import json
import os
import re
import sys


def extract_fields_from_source(source_path: str) -> dict:
    """Parse tushare_collector.py to extract endpoint -> fields mappings."""
    with open(source_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Match patterns like: _safe_call("endpoint_name", ..., fields="f1,f2,f3")
    pattern = r'_safe_call\(\s*"(\w+)"[^)]*fields\s*=\s*"([^"]+)"'
    matches = re.findall(pattern, content)

    endpoints = {}
    for endpoint, fields_str in matches:
        fields = [f.strip() for f in fields_str.split(",")]
        if endpoint not in endpoints:
            endpoints[endpoint] = set()
        endpoints[endpoint].update(fields)

    # Convert sets to sorted lists for JSON serialization
    return {ep: sorted(list(fields)) for ep, fields in sorted(endpoints.items())}


def main():
    parser = argparse.ArgumentParser(description="Generate available_fields.json")
    parser.add_argument("--output", default="output/available_fields.json",
                        help="Output JSON path (default: output/available_fields.json)")
    args = parser.parse_args()

    # Find tushare_collector.py relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_path = os.path.join(script_dir, "tushare_collector.py")

    if not os.path.exists(source_path):
        print(f"Error: {source_path} not found", file=sys.stderr)
        sys.exit(1)

    endpoints = extract_fields_from_source(source_path)

    # Ensure output directory exists
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(endpoints, f, ensure_ascii=False, indent=2)

    print(f"Generated {args.output} with {len(endpoints)} endpoints")
    for ep, fields in endpoints.items():
        print(f"  {ep}: {len(fields)} fields")


if __name__ == "__main__":
    main()
