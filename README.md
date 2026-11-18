# malaysia-postcode-dataset

A list of Malaysian postcodes, grouped by state and city, in JSON format.

## Data source

The data comes from the **Postcode Dataset** on the Malaysian government's open data portal:

- Website: https://data.gov.my/data-catalogue/poskod
- Owner: Malaysian Communications and Multimedia Commission (MCMC)
- Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

**Last updated:** 18 November 2026

This is the date the data was last taken from the source. The source may add or change postcodes after this date. If it does, we will update the data here and change this date.

## Files

Each state has its own file in `data/states/`, for example `data/states/johor.json`.

Each file looks like this:

```json
{
  "state": "Johor",
  "cities": [
    { "city": "Ayer Hitam", "postcodes": ["86100", "86107"] }
  ]
}
```

## Requirements

You only need **Python 3.10 or newer**. No extra packages are needed.

## Scripts

There are two scripts in the `scripts/` folder:

| Script | What it does |
| --- | --- |
| `build.py` | Downloads the latest postcode list from data.gov.my, cleans it, and saves one JSON file per state in `data/states/`. |
| `export.py` | Reads the JSON files in `data/states/` and turns them into a CSV file or an SQL file for your database. |

They work in this order:

```
data.gov.my  →  build.py  →  data/states/*.json  →  export.py  →  postcodes.csv / postcodes.sql
```

The JSON files are already included in this repository. If you only want CSV or SQL, you can just run `export.py`. Run `build.py` only when you want the newest data from data.gov.my (see [Keep your data up to date](#keep-your-data-up-to-date)).

## Convert to CSV or SQL

Use `scripts/export.py` to turn the JSON files into one CSV or SQL file. Each row has three columns: `state`, `city` and `postcode`.

**CSV**

```bash
python3 scripts/export.py csv
```

This creates `postcodes.csv`.

**SQL**

```bash
python3 scripts/export.py sql                      # MySQL / MariaDB
python3 scripts/export.py sql --dialect postgres   # PostgreSQL
python3 scripts/export.py sql --dialect sqlite     # SQLite
```

This creates `postcodes.sql`. Then import it into your database, for example:

```bash
mysql -u root -p your_database < postcodes.sql
psql your_database < postcodes.sql
sqlite3 your_database.db < postcodes.sql
```

The first time you import it, it creates a table called `postcodes`:

| Column | Description |
| --- | --- |
| `id` | A number for each row. It never changes, so you can safely link other tables to it. |
| `state` | State name, for example `Johor` |
| `city` | City name, for example `Ayer Hitam` |
| `postcode` | 5-digit postcode, for example `86100` |
| `active` | `TRUE` if the postcode is in the latest data, `FALSE` if it was removed from the source |

You can import the same file again at any time. It does not delete or change your existing rows:

- Postcodes you already have keep the **same `id`**.
- New postcodes are added with a **new `id`**.
- Postcodes that were removed from the source are **not deleted**. They stay in the table with `active = FALSE`, so any record that links to them still works.

Everything is done in one step (a transaction), so if something goes wrong, your old data stays as it was.

To show only current postcodes in your app, for example in a dropdown, filter by `active`:

```sql
SELECT id, state, city, postcode FROM postcodes WHERE active = TRUE;
```

> **Note:** The `id` numbers are created by your own database. Your `id` for a postcode may be different from someone else's. Do not copy `id` numbers between different databases.

**Linked tables (states, cities, postcodes)**

If you want separate tables that are linked together, add `--linked`:

```bash
python3 scripts/export.py sql --linked
```

This creates three tables:

| Table | Columns | Linked to |
| --- | --- | --- |
| `states` | `id`, `name`, `active` | |
| `cities` | `id`, `state_id`, `name`, `active` | `state_id` → `states.id` |
| `postcodes` | `id`, `state_id`, `city_id`, `postcode`, `active` | `state_id` → `states.id`, `city_id` → `cities.id` |

Each city belongs to a state. Each postcode belongs to a city and also to a state, so you can link a postcode straight to its state. The import always fills in `state_id` and `city_id` together, so they always agree.

Show each postcode with its city and state:

```sql
SELECT p.id, p.postcode, c.name AS city, s.name AS state
FROM postcodes p
JOIN cities c ON c.id = p.city_id
JOIN states s ON s.id = p.state_id
WHERE p.active = TRUE;
```

Show all postcodes in one state:

```sql
SELECT p.postcode
FROM postcodes p
JOIN states s ON s.id = p.state_id
WHERE s.name = 'Johor' AND p.active = TRUE;
```

> **Note:** If you change these tables by hand, make sure `state_id` on a postcode is the same as the `state_id` of its city.

The update rules are the same as above: `id` numbers never change, new rows get new `id` numbers, and removed rows stay with `active = FALSE`.

If you already have tables with these names, use `--prefix` to change them. For example, `--prefix my_` creates `my_states`, `my_cities` and `my_postcodes`.

**More options**

| Option | What it does | Example |
| --- | --- | --- |
| `--state` | Export only some states | `--state johor selangor` |
| `--table` | Use a different table name | `--table my_postcodes` |
| `--linked` | Create three linked tables instead of one | `--linked` |
| `--prefix` | With `--linked`, add text before each table name | `--prefix my_` |
| `--output` | Save to a different file | `--output exports/postcodes.csv` |

The state names are the file names in `data/states/`, without `.json`.

## Keep your data up to date

The data here may be older than the source. You can download the latest data yourself at any time.

1. Get the latest version of this repository:

   ```bash
   git pull
   ```

2. Download the newest data from data.gov.my and rebuild the JSON files:

   ```bash
   python3 scripts/build.py --refresh
   ```

3. Export again and import into your database:

   ```bash
   python3 scripts/export.py sql
   mysql -u root -p your_database < postcodes.sql
   ```

You can run these steps whenever you like, for example once a month. Each time, new postcodes are added and your existing `id` numbers stay the same.

If you only want some states, use `--state` on both scripts, for example `python3 scripts/build.py --refresh --state johor`.

### For maintainers

When you update the data in this repository, also change the **Last updated** date at the top of this file.

## Licence

The postcode data belongs to MCMC and is shared under the CC BY 4.0 licence. If you use it, please give credit to MCMC and data.gov.my.

The other files in this repository are under the MIT License. See [LICENSE](LICENSE).
