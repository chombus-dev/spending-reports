# Monarch Spending Report

Generates a single-file HTML spending report from [Monarch Money](https://www.monarchmoney.com) CSV exports.

No dependencies beyond Python 3 — just a browser to view the output.

---

## Setup

**1. Clone or download this repo**

**2. Export your transactions from Monarch**

Go to **Transactions → Export** in Monarch and save the CSV into a `Transactions/` folder in this directory. You can export multiple months and drop them all in — duplicates are handled automatically.

**3. Configure categories**

Copy the example config and edit it to match your Monarch category names:

```bash
cp config.example.json config.json
```

Open `config.json` and update:

- `income_categories` — categories Monarch uses for income (e.g. `"Paychecks"`, `"Interest"`)
- `exclude_categories` — categories to ignore entirely (e.g. `"Transfer"`, `"Credit Card Payment"`)
- `essential_categories` — non-discretionary spending (used to calculate discretionary spend)
- `flag_exempt_categories` — large transactions in these categories won't be flagged
- `income_source_map` — map merchant names (lowercase) to friendly labels in the income chart
- `secondary_member` — if you track a household member separately (e.g. a parent), set this to the tag or account prefix Monarch uses for them. Set to `null` if not applicable.
- `flag_threshold` — transactions above this amount get flagged (default: `2000`)

---

## Running

```bash
python3 generate.py
```

Output is written to `Output/spending-report-YYYY.html`. Open it in any browser.

### Options

| Flag | Description | Default |
|---|---|---|
| `--input DIR` | Folder containing Monarch CSV exports | `Transactions/` |
| `--file F [F ...]` | One or more specific CSV files (overrides `--input`) | — |
| `--output PATH` | Output HTML path | `Output/spending-report-YYYY.html` |
| `--year YYYY` | Filter to a specific year | all years in CSVs |
| `--config PATH` | Config file | `config.json` |
| `--template PATH` | HTML template | `template.html` |

### Examples

```bash
# Full report from all CSVs in Transactions/
python3 generate.py

# Just one file
python3 generate.py --file Transactions/march.csv

# Filter to 2025 only
python3 generate.py --year 2025

# Custom output path
python3 generate.py --output ~/Desktop/report.html
```

---

## Running tests

```bash
python3 test_generate.py
```
