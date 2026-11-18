#!/usr/bin/env python3
"""Export the postcode JSON files in data/states/ to CSV or SQL.

Every output row is one (state, city, postcode). A postcode can appear more
than once if it covers more than one city.

Usage:
    python3 scripts/export.py csv                       # -> postcodes.csv
    python3 scripts/export.py sql                       # -> postcodes.sql (MySQL)
    python3 scripts/export.py sql --dialect postgres    # PostgreSQL
    python3 scripts/export.py sql --dialect sqlite      # SQLite
    python3 scripts/export.py csv --state johor selangor
    python3 scripts/export.py sql --table my_postcodes --output db/postcodes.sql

The SQL file creates the table (with an auto-increment id) if it does not
exist, then updates it inside one transaction. Running it again later is how
you update your database. Existing rows keep their id, new rows get a new id,
and rows removed from the source are kept with active = FALSE.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATES_DIR = ROOT / "data" / "states"
SOURCE = "https://data.gov.my/data-catalogue/poskod (MCMC, CC BY 4.0)"
BATCH_SIZE = 500

Row = tuple[str, str, str]  # (state, city, postcode)


def load_rows(slugs: list[str] | None) -> list[Row]:
    files = sorted(STATES_DIR.glob("*.json"))
    if not files:
        sys.exit(f"No JSON files found in {STATES_DIR.relative_to(ROOT)}. "
                 "Run: python3 scripts/build.py")
    available = {f.stem: f for f in files}
    if slugs:
        unknown = sorted(set(slugs) - available.keys())
        if unknown:
            sys.exit(f"Unknown state(s): {', '.join(unknown)}\n"
                     f"Available: {', '.join(sorted(available))}")
        files = [available[s] for s in sorted(set(slugs))]

    rows: list[Row] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for city in data["cities"]:
            for postcode in city["postcodes"]:
                rows.append((data["state"], city["city"], postcode))
    rows.sort(key=lambda r: (r[0].casefold(), r[1].casefold(), r[2]))
    return rows


def write_csv(rows: list[Row], out) -> None:
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["state", "city", "postcode"])
    writer.writerows(rows)


def sql_string(value: str, dialect: str) -> str:
    if dialect == "mysql":
        value = value.replace("\\", "\\\\")
    return "'" + value.replace("'", "''") + "'"


ID_COLUMN = {
    "mysql": "id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY",
    "postgres": "id SERIAL PRIMARY KEY",
    "sqlite": "id INTEGER PRIMARY KEY AUTOINCREMENT",
}


def write_sql(rows: list[Row], out, dialect: str, table: str, states: list[str] | None) -> None:
    """Write an update script that never changes or reuses an existing row's id.

    1. Mark rows as inactive (all rows, or only the exported states).
    2. Insert each current row. If it already exists, keep its id and mark it
       active again. New rows get a new id.
    Rows that are no longer in the source stay in the table with active = FALSE,
    so anything that links to their id keeps working.
    """
    q = "`" if dialect == "mysql" else '"'
    t = f"{q}{table.replace(q, q * 2)}{q}"
    begin = "START TRANSACTION;" if dialect == "mysql" else "BEGIN;"
    if dialect == "mysql":
        on_conflict = "ON DUPLICATE KEY UPDATE active = TRUE"
    else:
        on_conflict = "ON CONFLICT (state, city, postcode) DO UPDATE SET active = TRUE"

    out.write(f"-- Malaysia postcodes ({dialect})\n")
    out.write(f"-- Source: {SOURCE}\n")
    out.write(f"-- Generated: {date.today().isoformat()}, {len(rows)} rows\n")
    out.write("-- Safe to run again: existing ids never change.\n\n")
    out.write(
        f"CREATE TABLE IF NOT EXISTS {t} (\n"
        f"  {ID_COLUMN[dialect]},\n"
        f"  state VARCHAR(100) NOT NULL,\n"
        f"  city VARCHAR(100) NOT NULL,\n"
        f"  postcode CHAR(5) NOT NULL,\n"
        f"  active BOOLEAN NOT NULL DEFAULT TRUE,\n"
        f"  UNIQUE (state, city, postcode)\n"
        f");\n\n"
    )
    out.write(f"{begin}\n\n")
    where = ""
    if states:
        names = sorted({row[0] for row in rows})
        where = " WHERE state IN (" + ", ".join(sql_string(n, dialect) for n in names) + ")"
    out.write(f"UPDATE {t} SET active = FALSE{where};\n\n")
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        values = ",\n".join(
            "  (" + ", ".join(sql_string(v, dialect) for v in row) + ", TRUE)" for row in batch
        )
        out.write(f"INSERT INTO {t} (state, city, postcode, active) VALUES\n{values}\n"
                  f"{on_conflict};\n\n")
    out.write("COMMIT;\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("format", choices=["csv", "sql"], help="output format")
    parser.add_argument("--dialect", choices=["mysql", "postgres", "sqlite"], default="mysql",
                        help="SQL database type (default: mysql)")
    parser.add_argument("--table", default="postcodes",
                        help="SQL table name (default: postcodes)")
    parser.add_argument("--state", nargs="+", metavar="SLUG",
                        help="only export these states, e.g. johor wp-kuala-lumpur")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="output file (default: postcodes.csv / postcodes.sql; "
                             "use - for the terminal)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_rows(args.state)
    output = args.output or f"postcodes.{args.format}"

    def write(out) -> None:
        if args.format == "csv":
            write_csv(rows, out)
        else:
            write_sql(rows, out, args.dialect, args.table, args.state)

    if output == "-":
        write(sys.stdout)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as out:
        write(out)
    print(f"Wrote {len(rows)} rows -> {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
