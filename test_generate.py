#!/usr/bin/env python3
"""Tests for generate.py"""

import unittest
from generate import (
    load_config, is_secondary, is_income_row, is_expense_row,
    income_source_label, compute_kpi, compute_categories,
    compute_flags, compute_income, compute_top_merchants,
    load_transactions, build_data, DEFAULT_CONFIG,
)
import csv, json, tempfile
from pathlib import Path


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_cfg(**overrides):
    cfg = load_config('/nonexistent')  # triggers defaults
    cfg.update(overrides)
    return cfg


def make_row(date='2026-01-15', merchant='Amazon', category='Shopping',
             account='Checking', amount=-50.0, tags='', secondary=False):
    return {
        'Date': date, 'Merchant': merchant, 'Category': category,
        'Account': account, 'Tags': tags,
        '_amount': amount, '_month': date[:7], '_secondary': secondary,
    }


# ── Config loading ─────────────────────────────────────────────────────────────

class TestLoadConfig(unittest.TestCase):

    def test_defaults_when_file_missing(self):
        cfg = load_config('/nonexistent/path.json')
        self.assertIn('Paychecks', cfg['income_categories'])
        self.assertIn('Transfer', cfg['exclude_categories'])
        self.assertIsNone(cfg['secondary_member'])
        self.assertEqual(cfg['flag_threshold'], 2000)

    def test_file_overrides_defaults(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({'flag_threshold': 500, 'secondary_member': 'Mom'}, f)
            path = f.name
        cfg = load_config(path)
        self.assertEqual(cfg['flag_threshold'], 500)
        self.assertEqual(cfg['secondary_member'], 'Mom')
        # defaults still present for keys not overridden
        self.assertIn('Transfer', cfg['exclude_categories'])

    def test_lists_converted_to_sets(self):
        cfg = load_config('/nonexistent')
        self.assertIsInstance(cfg['income_categories'], set)
        self.assertIsInstance(cfg['exclude_categories'], set)
        self.assertIsInstance(cfg['essential_categories'], set)
        self.assertIsInstance(cfg['flag_exempt_categories'], set)


# ── Row classification ────────────────────────────────────────────────────────

class TestRowClassification(unittest.TestCase):

    def setUp(self):
        self.cfg = make_cfg(secondary_member='Jolee')

    def test_is_secondary_by_tag(self):
        row = make_row(tags='Jolee')
        self.assertTrue(is_secondary(row, self.cfg))

    def test_is_secondary_by_account_prefix(self):
        row = make_row(account='Jolee Checking')
        self.assertTrue(is_secondary(row, self.cfg))

    def test_not_secondary(self):
        row = make_row(tags='', account='My Checking')
        self.assertFalse(is_secondary(row, self.cfg))

    def test_secondary_disabled_when_none(self):
        cfg = make_cfg(secondary_member=None)
        row = make_row(tags='Jolee', account='Jolee Checking')
        self.assertFalse(is_secondary(row, cfg))

    def test_is_income_row(self):
        cfg = make_cfg()
        row = make_row(category='Paychecks', amount=5000.0)
        self.assertTrue(is_income_row(row, cfg))

    def test_negative_income_not_counted(self):
        cfg = make_cfg()
        row = make_row(category='Paychecks', amount=-50.0)
        self.assertFalse(is_income_row(row, cfg))

    def test_is_expense_row(self):
        cfg = make_cfg()
        row = make_row(category='Shopping', amount=-50.0)
        self.assertTrue(is_expense_row(row, cfg))

    def test_excluded_category_not_expense(self):
        cfg = make_cfg()
        row = make_row(category='Transfer', amount=-500.0)
        self.assertFalse(is_expense_row(row, cfg))

    def test_positive_amount_not_expense(self):
        cfg = make_cfg()
        row = make_row(category='Shopping', amount=50.0)
        self.assertFalse(is_expense_row(row, cfg))


# ── Income source labelling ───────────────────────────────────────────────────

class TestIncomeSourceLabel(unittest.TestCase):

    def test_mapped_merchant(self):
        cfg = make_cfg(income_source_map={'acme corp': 'Salary'})
        row = make_row(merchant='Acme Corp', secondary=False)
        self.assertEqual(income_source_label(row, cfg), 'Salary')

    def test_unmapped_primary(self):
        cfg = make_cfg(secondary_member='Mom', income_source_map={})
        row = make_row(merchant='Unknown Co', secondary=False)
        self.assertEqual(income_source_label(row, cfg), 'Other Income')

    def test_unmapped_secondary(self):
        cfg = make_cfg(secondary_member='Mom', income_source_map={})
        row = make_row(merchant='Unknown Co', secondary=True)
        self.assertEqual(income_source_label(row, cfg), 'Mom Other Income')


# ── KPI computation ───────────────────────────────────────────────────────────

class TestComputeKPI(unittest.TestCase):

    def setUp(self):
        self.cfg = make_cfg()

    def test_basic_totals(self):
        rows = [
            make_row(category='Paychecks', amount=3000.0),
            make_row(category='Shopping',  amount=-200.0),
            make_row(category='Restaurants & Bars', amount=-100.0),
        ]
        kpi = compute_kpi(rows, self.cfg)
        self.assertAlmostEqual(kpi['total_income'], 3000.0)
        self.assertAlmostEqual(kpi['total_spend'],   300.0)
        self.assertAlmostEqual(kpi['net_savings'],  2700.0)

    def test_excludes_transfers(self):
        rows = [
            make_row(category='Shopping', amount=-100.0),
            make_row(category='Transfer', amount=-500.0),
        ]
        kpi = compute_kpi(rows, self.cfg)
        self.assertAlmostEqual(kpi['total_spend'], 100.0)

    def test_mom_delta(self):
        curr = [make_row(category='Shopping', amount=-200.0)]
        prev = [make_row(category='Shopping', amount=-100.0)]
        kpi = compute_kpi(curr, self.cfg, prev_rows=prev)
        self.assertAlmostEqual(kpi['delta_spend'], 100.0)

    def test_secondary_spend_tracked(self):
        cfg = make_cfg(secondary_member='Jolee')
        rows = [
            make_row(category='Shopping', amount=-100.0, secondary=False),
            make_row(category='Shopping', amount=-50.0,  secondary=True),
        ]
        kpi = compute_kpi(rows, cfg)
        self.assertAlmostEqual(kpi['total_spend'], 150.0)
        self.assertAlmostEqual(kpi['hh_spend'],    100.0)
        self.assertAlmostEqual(kpi['secondary_spend'], 50.0)


# ── Flags ─────────────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def test_flags_large_transaction(self):
        cfg = make_cfg(flag_threshold=1000)
        rows = [make_row(category='Shopping', amount=-1500.0)]
        flags = compute_flags(rows, cfg)
        self.assertEqual(len(flags), 1)
        self.assertIn('1,500', flags[0]['note'])

    def test_exempt_category_not_flagged(self):
        cfg = make_cfg(flag_threshold=1000)
        rows = [make_row(category='Mortgage & Rent', amount=-2500.0)]
        flags = compute_flags(rows, cfg)
        self.assertEqual(len(flags), 0)

    def test_below_threshold_not_flagged(self):
        cfg = make_cfg(flag_threshold=1000)
        rows = [make_row(category='Shopping', amount=-500.0)]
        flags = compute_flags(rows, cfg)
        self.assertEqual(len(flags), 0)

    def test_capped_at_five(self):
        cfg = make_cfg(flag_threshold=100)
        rows = [make_row(category='Shopping', amount=-float(200 + i)) for i in range(10)]
        flags = compute_flags(rows, cfg)
        self.assertLessEqual(len(flags), 5)


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDeduplication(unittest.TestCase):

    def test_duplicate_rows_collapsed(self):
        with tempfile.TemporaryDirectory() as d:
            row = 'Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags,Owner,Business Entity\n'
            row += '2026-01-10,Amazon,Shopping,Checking,AMAZON,,-50.00,,Shared,\n'
            # same row in two files
            for name in ('a.csv', 'b.csv'):
                Path(d, name).write_text(row)
            cfg = make_cfg()
            txns = load_transactions(d, cfg)
        self.assertEqual(len(txns), 1)

    def test_distinct_rows_both_kept(self):
        with tempfile.TemporaryDirectory() as d:
            header = 'Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags,Owner,Business Entity\n'
            Path(d, 'a.csv').write_text(header + '2026-01-10,Amazon,Shopping,Checking,AMAZON,,-50.00,,Shared,\n')
            Path(d, 'b.csv').write_text(header + '2026-01-11,Uber,Transport,Checking,UBER,,-20.00,,Shared,\n')
            cfg = make_cfg()
            txns = load_transactions(d, cfg)
        self.assertEqual(len(txns), 2)


# ── build_data smoke test ─────────────────────────────────────────────────────

class TestBuildData(unittest.TestCase):

    def _make_txns(self):
        cfg = make_cfg()
        rows = [
            make_row(date='2026-01-10', category='Paychecks',        amount=3000.0),
            make_row(date='2026-01-15', category='Shopping',          amount=-200.0),
            make_row(date='2026-01-20', category='Restaurants & Bars',amount=-80.0),
            make_row(date='2026-02-05', category='Paychecks',         amount=3000.0),
            make_row(date='2026-02-10', category='Shopping',          amount=-150.0),
        ]
        return rows, cfg

    def test_months_detected(self):
        rows, cfg = self._make_txns()
        data = build_data(rows, cfg)
        self.assertIn('2026-01', data['months'])
        self.assertIn('2026-02', data['months'])

    def test_all_keys_present(self):
        rows, cfg = self._make_txns()
        data = build_data(rows, cfg)
        for key in ('kpi', 'categories', 'sankey', 'flags', 'income',
                    'transactions', 'top_merchants', 'sparkline_spend'):
            self.assertIn(key, data)

    def test_transactions_split_by_secondary(self):
        cfg = make_cfg(secondary_member='Mom')
        rows = [
            make_row(date='2026-01-10', category='Shopping', amount=-100.0, secondary=False),
            make_row(date='2026-01-11', category='Shopping', amount=-50.0,  secondary=True),
        ]
        data = build_data(rows, cfg)
        self.assertEqual(len(data['transactions']['household']), 1)
        self.assertEqual(len(data['transactions']['secondary']), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
