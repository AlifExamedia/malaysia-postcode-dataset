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
    python3 scripts/export.py sql --linked              # states, cities, postcodes tables

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


def write_sql_linked(rows: list[Row], out, dialect: str, prefix: str,
                     states: list[str] | None) -> None:
    """Write three linked tables: states <- cities <- postcodes.

    Postcodes link to both their city (city_id) and their state (state_id).

    Same update rules as write_sql: ids never change or get reused, new rows
    get new ids, and rows removed from the source stay with active = FALSE.
    The rows are first loaded into a temporary table, then copied into the
    three tables from there.
    """
    q = "`" if dialect == "mysql" else '"'

    def name(table: str) -> str:
        full = prefix + table
        return f"{q}{full.replace(q, q * 2)}{q}"

    st, ci, pc, tmp = name("states"), name("cities"), name("postcodes"), name("import_tmp")
    begin = "START TRANSACTION;" if dialect == "mysql" else "BEGIN;"

    def upsert(key: str) -> str:
        if dialect == "mysql":
            return "ON DUPLICATE KEY UPDATE active = TRUE"
        return f"ON CONFLICT ({key}) DO UPDATE SET active = TRUE"

    def index(table: str, column: str) -> str:
        if dialect == "mysql":  # MySQL has no CREATE INDEX IF NOT EXISTS; index is inline
            return ""
        idx = name(f"{table}_{column}_idx")
        return f"CREATE INDEX IF NOT EXISTS {idx} ON {name(table)} ({column});\n"

    mysql_index = lambda column: f",\n  INDEX ({column})" if dialect == "mysql" else ""

    out.write(f"-- Malaysia postcodes, linked tables ({dialect})\n")
    out.write(f"-- Source: {SOURCE}\n")
    out.write(f"-- Generated: {date.today().isoformat()}, {len(rows)} postcode rows\n")
    out.write("-- Safe to run again: existing ids never change.\n\n")

    out.write(
        f"CREATE TABLE IF NOT EXISTS {st} (\n"
        f"  {ID_COLUMN[dialect]},\n"
        f"  name VARCHAR(100) NOT NULL,\n"
        f"  active BOOLEAN NOT NULL DEFAULT TRUE,\n"
        f"  UNIQUE (name)\n"
        f");\n\n"
        f"CREATE TABLE IF NOT EXISTS {ci} (\n"
        f"  {ID_COLUMN[dialect]},\n"
        f"  state_id INTEGER{' UNSIGNED' if dialect == 'mysql' else ''} NOT NULL,\n"
        f"  name VARCHAR(100) NOT NULL,\n"
        f"  active BOOLEAN NOT NULL DEFAULT TRUE,\n"
        f"  UNIQUE (state_id, name),\n"
        f"  FOREIGN KEY (state_id) REFERENCES {st} (id)\n"
        f");\n\n"
        f"CREATE TABLE IF NOT EXISTS {pc} (\n"
        f"  {ID_COLUMN[dialect]},\n"
        f"  state_id INTEGER{' UNSIGNED' if dialect == 'mysql' else ''} NOT NULL,\n"
        f"  city_id INTEGER{' UNSIGNED' if dialect == 'mysql' else ''} NOT NULL,\n"
        f"  postcode CHAR(5) NOT NULL,\n"
        f"  active BOOLEAN NOT NULL DEFAULT TRUE,\n"
        f"  UNIQUE (city_id, postcode),\n"
        f"  FOREIGN KEY (state_id) REFERENCES {st} (id),\n"
        f"  FOREIGN KEY (city_id) REFERENCES {ci} (id){mysql_index('postcode')}\n"
        f");\n"
        f"{index('postcodes', 'postcode')}"
        f"{index('postcodes', 'state_id')}\n"
    )

    # Temporary table with the new data
    out.write(f"CREATE TEMPORARY TABLE {tmp} (\n"
              f"  state VARCHAR(100) NOT NULL,\n"
              f"  city VARCHAR(100) NOT NULL,\n"
              f"  postcode CHAR(5) NOT NULL\n"
              f");\n\n")
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        values = ",\n".join(
            "  (" + ", ".join(sql_string(v, dialect) for v in row) + ")" for row in batch
        )
        out.write(f"INSERT INTO {tmp} (state, city, postcode) VALUES\n{values};\n\n")

    out.write(f"{begin}\n\n")

    # 1. Mark existing rows inactive (only the exported states, if --state is used)
    state_filter = ""
    if states:
        names = sorted({row[0] for row in rows})
        state_filter = "name IN (" + ", ".join(sql_string(n, dialect) for n in names) + ")"
    where_state = f" WHERE {state_filter}" if state_filter else ""
    out.write(f"UPDATE {st} SET active = FALSE{where_state};\n")
    if state_filter:
        out.write(f"UPDATE {ci} SET active = FALSE WHERE state_id IN "
                  f"(SELECT id FROM {st} WHERE {state_filter});\n")
        out.write(f"UPDATE {pc} SET active = FALSE WHERE state_id IN "
                  f"(SELECT id FROM {st} WHERE {state_filter});\n\n")
    else:
        out.write(f"UPDATE {ci} SET active = FALSE;\n")
        out.write(f"UPDATE {pc} SET active = FALSE;\n\n")

    # 2. Add new rows and mark current rows active again. "WHERE TRUE" is
    #    needed by SQLite before ON CONFLICT in an INSERT ... SELECT.
    out.write(f"INSERT INTO {st} (name, active)\n"
              f"SELECT DISTINCT t.state, TRUE FROM {tmp} t WHERE TRUE\n"
              f"{upsert('name')};\n\n")
    out.write(f"INSERT INTO {ci} (state_id, name, active)\n"
              f"SELECT DISTINCT s.id, t.city, TRUE FROM {tmp} t\n"
              f"JOIN {st} s ON s.name = t.state WHERE TRUE\n"
              f"{upsert('state_id, name')};\n\n")
    # state_id always comes from the same state as the city, so the two links agree.
    out.write(f"INSERT INTO {pc} (state_id, city_id, postcode, active)\n"
              f"SELECT s.id, c.id, t.postcode, TRUE FROM {tmp} t\n"
              f"JOIN {st} s ON s.name = t.state\n"
              f"JOIN {ci} c ON c.state_id = s.id AND c.name = t.city WHERE TRUE\n"
              f"{upsert('city_id, postcode')};\n\n")
    out.write("COMMIT;\n\n")
    out.write(f"DROP TABLE {tmp};\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("format", choices=["csv", "sql"], help="output format")
    parser.add_argument("--dialect", choices=["mysql", "postgres", "sqlite"], default="mysql",
                        help="SQL database type (default: mysql)")
    parser.add_argument("--table", default="postcodes",
                        help="SQL table name (default: postcodes; not used with --linked)")
    parser.add_argument("--linked", action="store_true",
                        help="SQL only: create three linked tables (states, cities, postcodes) "
                             "instead of one table")
    parser.add_argument("--prefix", default="",
                        help="with --linked: text added before each table name, e.g. my_")
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
        elif args.linked:
            write_sql_linked(rows, out, args.dialect, args.prefix, args.state)
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
