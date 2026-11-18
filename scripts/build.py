#!/usr/bin/env python3
"""Build per-state postcode JSON files from the data.gov.my Postcode Dataset.

Source:  https://data.gov.my/data-catalogue/poskod
Owner:   Malaysian Communications and Multimedia Commission (MCMC)
License: CC BY 4.0

Output (data/states/<state-slug>.json):

    {
      "state": "Johor",
      "cities": [
        { "city": "Ayer Hitam", "postcodes": ["86100", "86107"] }
      ]
    }

Usage:
    python3 scripts/build.py                  # all states
    python3 scripts/build.py --state johor    # one or more states, by slug
    python3 scripts/build.py --refresh        # re-download the source CSV
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

CSV_URL = "https://storage.data.gov.my/dictionaries/postcodes.csv"
ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / ".cache" / "postcodes.csv"
OUT_DIR = ROOT / "data" / "states"
POSTCODE_RE = re.compile(r"\d{5}")

# state -> city -> {postcodes}
Tree = dict[str, dict[str, set[str]]]


def clean(text: str | None) -> str:
    """Collapse internal whitespace and trim."""
    return " ".join((text or "").split())


def slugify(name: str) -> str:
    """'W.P. Kuala Lumpur' -> 'wp-kuala-lumpur', 'Negeri Sembilan' -> 'negeri-sembilan'."""
    name = name.casefold().replace(".", "")
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def fetch_csv(refresh: bool) -> Path:
    if CACHE_FILE.exists() and not refresh:
        return CACHE_FILE
    print(f"Downloading {CSV_URL}", file=sys.stderr)
    request = urllib.request.Request(CSV_URL, headers={"User-Agent": "postcode-builder/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except urllib.error.URLError as exc:
        sys.exit(f"Download failed: {exc}")
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_bytes(data)
    return CACHE_FILE


def load(path: Path) -> tuple[Tree, list[str]]:
    tree: Tree = defaultdict(lambda: defaultdict(set))
    warnings: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"state", "city", "postcode"} - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"Source CSV is missing column(s): {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            state, city, postcode = (clean(row[k]) for k in ("state", "city", "postcode"))
            if not state or not city or not POSTCODE_RE.fullmatch(postcode):
                warnings.append(f"line {line}: skipped invalid row {dict(row)}")
                continue
            tree[state][city].add(postcode)
    return tree, warnings


def build_state(state: str, cities: dict[str, set[str]]) -> dict:
    return {
        "state": state,
        "cities": [
            {"city": city, "postcodes": sorted(cities[city])}
            for city in sorted(cities, key=str.casefold)
        ],
    }


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state", nargs="+", metavar="SLUG",
                        help="only build these states, e.g. johor wp-kuala-lumpur")
    parser.add_argument("--refresh", action="store_true", help="re-download the source CSV")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tree, warnings = load(fetch_csv(args.refresh))
    states = {slugify(name): name for name in tree}

    selected = args.state or sorted(states)
    unknown = sorted(set(selected) - states.keys())
    if unknown:
        sys.exit(f"Unknown state(s): {', '.join(unknown)}\nValid: {', '.join(sorted(states))}")

    for slug in selected:
        name = states[slug]
        out = OUT_DIR / f"{slug}.json"
        data = build_state(name, tree[name])
        write_json(out, data)
        total = sum(len(c["postcodes"]) for c in data["cities"])
        print(f"{name:<20} {len(data['cities']):>3} cities {total:>5} postcodes  -> "
              f"{out.relative_to(ROOT)}")

    for warning in warnings:
        print(f"WARN {warning}", file=sys.stderr)


if __name__ == "__main__":
    main()
