#!/usr/bin/env python3
"""
Monarch CSV → Household Spending Report HTML

Usage:
  python generate.py
  python generate.py --input Monarch/ --output spending-report-2026.html
  python generate.py --template template.html --config config.json
"""

import csv, json, argparse, calendar
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date, timedelta

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    'income_categories':      ['Paychecks', 'Other Income', 'Interest'],
    'exclude_categories':     ['Transfer', 'Credit Card Payment'],
    'essential_categories':   ['Mortgage & Rent', 'Retirement', 'Taxes', 'Insurance',
                               'Medical', 'Internet & Cable', 'Phone', 'Education', 'Financial Fees'],
    'flag_exempt_categories': ['Mortgage & Rent', 'Retirement', 'Taxes', 'Transfer',
                               'Credit Card Payment', 'Education'],
    'income_source_map':      {},
    # If set, transactions tagged/accounted with this string are treated as a
    # secondary household member (e.g. a parent). Set to null to disable.
    'secondary_member':       None,
    'flag_threshold':         2000,
}


def load_config(path='config.json'):
    cfg = dict(DEFAULT_CONFIG)
    p = Path(path)
    if p.exists():
        with open(p) as f:
            cfg.update(json.load(f))
    # Normalise lists → sets for O(1) lookup
    cfg['income_categories']      = set(cfg['income_categories'])
    cfg['exclude_categories']     = set(cfg['exclude_categories'])
    cfg['essential_categories']   = set(cfg['essential_categories'])
    cfg['flag_exempt_categories'] = set(cfg['flag_exempt_categories'])
    return cfg


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_secondary(row, cfg):
    sm = cfg['secondary_member']
    if not sm:
        return False
    return sm in row.get('Tags', '') or row.get('Account', '').startswith(sm)


def is_income_row(row, cfg):
    return row['Category'] in cfg['income_categories'] and row['_amount'] > 0


def is_expense_row(row, cfg):
    return row['Category'] not in cfg['exclude_categories'] and row['_amount'] < 0


def income_source_label(row, cfg):
    key = row['Merchant'].lower().strip()
    if key in cfg['income_source_map']:
        return cfg['income_source_map'][key]
    sm = cfg['secondary_member']
    return f'{sm} Other Income' if (sm and row['_secondary']) else 'Other Income'


# ── Loading ───────────────────────────────────────────────────────────────────

def load_transactions(input_dir, cfg, files=None):
    """Load CSVs from input_dir (or explicit file list), deduplicate, and attach computed fields."""
    rows = []
    sources = [Path(f) for f in files] if files else sorted(Path(input_dir).glob('*.csv'))
    for f in sources:
        with open(f, newline='', encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                rows.append(r)

    seen = set()
    unique = []
    for r in rows:
        key = (r['Date'], r['Merchant'], r['Amount'], r['Account'], r['Category'])
        if key not in seen:
            seen.add(key)
            r['_amount']    = float(r['Amount'])
            r['_month']     = r['Date'][:7]
            r['_secondary'] = is_secondary(r, cfg)
            unique.append(r)

    return sorted(unique, key=lambda r: r['Date'], reverse=True)


# ── Aggregation ───────────────────────────────────────────────────────────────

def compute_kpi(rows, cfg, prev_rows=None):
    expenses  = [r for r in rows if is_expense_row(r, cfg)]
    incomes   = [r for r in rows if is_income_row(r, cfg)]
    sec_exp   = [r for r in expenses if r['_secondary']]
    disc_exp  = [r for r in expenses if r['Category'] not in cfg['essential_categories']]

    total_spend  = -sum(r['_amount'] for r in expenses)
    hh_spend     = -sum(r['_amount'] for r in expenses if not r['_secondary'])
    sec_spend    = -sum(r['_amount'] for r in sec_exp)
    disc_spend   = -sum(r['_amount'] for r in disc_exp)
    total_income = sum(r['_amount'] for r in incomes)
    net_savings  = total_income - total_spend

    delta_spend = delta_income = 0
    if prev_rows:
        prev_spend  = -sum(r['_amount'] for r in prev_rows if is_expense_row(r, cfg))
        prev_income =  sum(r['_amount'] for r in prev_rows if is_income_row(r, cfg))
        if prev_spend  > 0: delta_spend  = round((total_spend  - prev_spend)  / prev_spend  * 100, 1)
        if prev_income > 0: delta_income = round((total_income - prev_income) / prev_income * 100, 1)

    return {
        'total_spend':  round(total_spend,  2),
        'hh_spend':     round(hh_spend,     2),
        'disc_spend':   round(disc_spend,   2),
        'total_income': round(total_income, 2),
        'net_savings':  round(net_savings,  2),
        'secondary_spend': round(sec_spend, 2),
        'delta_spend':  delta_spend,
        'delta_income': delta_income,
    }


def compute_categories(rows, cfg, top_n=15):
    totals = defaultdict(float)
    for r in rows:
        if is_expense_row(r, cfg):
            totals[r['Category']] -= r['_amount']
    return [{'name': k, 'amount': round(v, 2)}
            for k, v in sorted(totals.items(), key=lambda x: -x[1])[:top_n]]


def compute_sparklines(txns, cfg, months):
    """Weekly spend and income totals across the report period."""
    year0, mon0 = map(int, months[0].split('-'))
    year1, mon1 = map(int, months[-1].split('-'))
    start = date(year0, mon0, 1)
    end   = date(year1, mon1, calendar.monthrange(year1, mon1)[1])

    weeks = []
    d = start
    while d <= end:
        iso = d.isocalendar()
        w = f"{iso[0]}-W{iso[1]:02d}"
        if w not in weeks:
            weeks.append(w)
        d += timedelta(days=7)

    spend_by_week  = defaultdict(float)
    income_by_week = defaultdict(float)
    for r in txns:
        try:
            dt = datetime.strptime(r['Date'], '%Y-%m-%d').date()
        except ValueError:
            continue
        iso = dt.isocalendar()
        w = f"{iso[0]}-W{iso[1]:02d}"
        if is_expense_row(r, cfg):
            spend_by_week[w]  -= r['_amount']
        elif is_income_row(r, cfg):
            income_by_week[w] += r['_amount']

    return (
        [round(spend_by_week.get(w, 0), 2)  for w in weeks],
        [round(income_by_week.get(w, 0), 2) for w in weeks],
        weeks,
    )


def compute_sankey(txns, cfg):
    income_by_source = defaultdict(float)
    for r in txns:
        if is_income_row(r, cfg):
            income_by_source[income_source_label(r, cfg)] += r['_amount']

    cat_totals = defaultdict(float)
    for r in txns:
        if is_expense_row(r, cfg):
            cat_totals[r['Category']] -= r['_amount']

    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:10]
    other = sum(v for k, v in cat_totals.items() if k not in dict(top_cats))
    if other > 0:
        top_cats.append(('Other', other))

    income_sources = sorted(income_by_source, key=lambda s: -income_by_source[s])
    expense_cats   = [k for k, _ in top_cats]
    nodes = income_sources + ['Total Income'] + expense_cats
    idx   = {n: i for i, n in enumerate(nodes)}
    ti    = idx['Total Income']

    links = []
    for src in income_sources:
        links.append({'source': idx[src], 'target': ti, 'value': round(income_by_source[src], 2)})
    for cat, amt in top_cats:
        links.append({'source': ti, 'target': idx[cat], 'value': round(amt, 2)})

    return {'nodes': [{'name': n} for n in nodes], 'links': links}


def compute_top_merchants(rows, cfg, top_n=5):
    by_merchant = defaultdict(lambda: {'amount': 0.0, 'count': 0})
    for r in rows:
        if is_expense_row(r, cfg):
            by_merchant[r['Merchant']]['amount'] -= r['_amount']
            by_merchant[r['Merchant']]['count']  += 1
    return [{'name': k, 'amount': round(v['amount'], 2), 'count': v['count']}
            for k, v in sorted(by_merchant.items(), key=lambda x: -x[1]['amount'])[:top_n]]


def compute_secondary_summary(rows, cfg, prev_rows=None):
    secondary = [r for r in rows if r['_secondary'] and is_expense_row(r, cfg)]
    total = -sum(r['_amount'] for r in secondary)

    cat_totals = defaultdict(float)
    for r in secondary:
        cat_totals[r['Category']] -= r['_amount']
    top_cats = [{'name': k, 'amount': round(v, 2)}
                for k, v in sorted(cat_totals.items(), key=lambda x: -x[1])[:5]]

    mom = 0
    if prev_rows:
        prev_total = -sum(r['_amount'] for r in prev_rows if r['_secondary'] and is_expense_row(r, cfg))
        if prev_total > 0:
            mom = round((total - prev_total) / prev_total * 100, 1)

    return {'total': round(total, 2), 'mom': mom, 'top_cats': top_cats}


def compute_flags(rows, cfg):
    flags = []
    for r in rows:
        if is_expense_row(r, cfg) and r['Category'] not in cfg['flag_exempt_categories']:
            amt = -r['_amount']
            if amt >= cfg['flag_threshold']:
                flags.append({
                    'note':     f'Large transaction: ${amt:,.0f}',
                    'merchant': r['Merchant'],
                    'date':     r['Date'],
                    'category': r['Category'],
                })
    flags.sort(key=lambda f: float(f['note'].split('$')[1].replace(',', '')), reverse=True)
    return flags[:5]


def compute_income(rows, cfg):
    by_source = defaultdict(float)
    for r in rows:
        if is_income_row(r, cfg):
            by_source[income_source_label(r, cfg)] += r['_amount']
    total = sum(by_source.values())
    sources = [{'name': k, 'amount': round(v, 2)}
               for k, v in sorted(by_source.items(), key=lambda x: -x[1])]
    return {'total': round(total, 2), 'sources': sources}


def format_txns(rows, cfg):
    out = []
    for r in rows:
        if r['Category'] in cfg['exclude_categories']:
            continue
        out.append({
            'date':     r['Date'],
            'merchant': r['Merchant'],
            'category': r['Category'],
            'account':  r['Account'],
            'amount':   round(r['_amount'], 2),
        })
    return out


# ── Build full DATA object ────────────────────────────────────────────────────

def build_data(txns, cfg):
    months       = sorted(set(r['_month'] for r in txns))
    month_labels = {m: datetime.strptime(m, '%Y-%m').strftime('%b %Y') for m in months}
    by_month     = defaultdict(list)
    for r in txns:
        by_month[r['_month']].append(r)

    kpi = {'all': compute_kpi(txns, cfg)}
    for i, m in enumerate(months):
        kpi[m] = compute_kpi(by_month[m], cfg, by_month[months[i-1]] if i > 0 else None)

    categories = {'all': compute_categories(txns, cfg)}
    for m in months:
        categories[m] = compute_categories(by_month[m], cfg)

    spend_sparkline, income_sparkline, weeks = compute_sparklines(txns, cfg, months)

    top_merchants = {'all': compute_top_merchants(txns, cfg)}
    for m in months:
        top_merchants[m] = compute_top_merchants(by_month[m], cfg)

    secondary_summary = {'all': compute_secondary_summary(txns, cfg)}
    for i, m in enumerate(months):
        secondary_summary[m] = compute_secondary_summary(by_month[m], cfg, by_month[months[i-1]] if i > 0 else None)

    income = {'all': compute_income(txns, cfg)}
    for m in months:
        income[m] = compute_income(by_month[m], cfg)

    month_totals = {'all': kpi['all']['total_spend']}
    for m in months:
        month_totals[m] = kpi[m]['total_spend']

    last_updated = datetime.strptime(max(r['Date'] for r in txns), '%Y-%m-%d').strftime('%b %d, %Y')

    return {
        'year':              months[0].split('-')[0],
        'months':            months,
        'month_labels':      month_labels,
        'last_updated':      last_updated,
        'kpi':               kpi,
        'sparkline_spend':   spend_sparkline,
        'sparkline_income':  income_sparkline,
        'sparkline_weeks':   weeks,
        'sankey':            compute_sankey(txns, cfg),
        'categories':        categories,
        'top_merchants':     top_merchants,
        'secondary_summary':     secondary_summary,
        'flags':             compute_flags(txns, cfg),
        'income':            income,
        'transactions': {
            'household': format_txns([r for r in txns if not r['_secondary']], cfg),
            'secondary': format_txns([r for r in txns if r['_secondary']], cfg),
        },
        'month_totals':      month_totals,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate spending report from Monarch CSVs')
    parser.add_argument('--input',    default='Transactions',  help='Directory with CSV exports (default: Transactions/)')
    parser.add_argument('--file',     nargs='+',               help='One or more CSV files (overrides --input)')
    parser.add_argument('--template', default='template.html', help='HTML template file (default: template.html)')
    parser.add_argument('--output',   default=None,            help='Output HTML path (default: spending-report-YYYY.html)')
    parser.add_argument('--year',     default=None,            help='Filter to a specific year, e.g. 2026')
    parser.add_argument('--config',   default='config.json',   help='Config file (default: config.json)')
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.file:
        missing = [f for f in args.file if not Path(f).exists()]
        if missing:
            print(f'Error: file(s) not found: {", ".join(missing)}')
            return 1
        print(f'Loading {len(args.file)} file(s)...')
        txns = load_transactions(None, cfg, files=args.file)
    else:
        print(f'Loading from {args.input}/')
        if not Path(args.input).exists():
            print(f'Error: input directory "{args.input}" not found')
            return 1
        txns = load_transactions(args.input, cfg)
    if args.year:
        txns = [r for r in txns if r['Date'].startswith(args.year)]
        print(f'  {len(txns)} transactions in {args.year}')
    else:
        print(f'  {len(txns)} unique transactions')

    if not txns:
        print('Error: no transactions found — check your input directory and --year filter')
        return 1

    print('Building report data...')
    data = build_data(txns, cfg)
    year   = data['year']
    months = data['months']
    print(f'  {year}, {len(months)} months: {", ".join(data["month_labels"][m] for m in months)}')

    template_path = Path(args.template)
    if not template_path.exists():
        print(f'Error: template not found at {template_path}')
        return 1

    output = Path(args.output) if args.output else Path('Output') / f'spending-report-{year}.html'
    output.parent.mkdir(parents=True, exist_ok=True)
    data_json = json.dumps(data, separators=(',', ':'))
    html = template_path.read_text().replace('/*SPENDING_DATA*/', data_json)
    output.write_text(html)
    print(f'Written → {output}')
    return 0


if __name__ == '__main__':
    exit(main())
