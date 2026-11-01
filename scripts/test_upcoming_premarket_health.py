"""Advance plans are pending, not missing Friday output or Monday readiness."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import build_automation_health as health


class UpcomingPremarketHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'config').mkdir()
        self.calendar = self.root / 'config/cn-market-calendar.json'
        self.calendar.write_text(json.dumps({'market': 'CN', 'verification_state': 'verified',
            'valid_from': '2026-01-01', 'valid_to': '2026-12-31', 'weekend_days': [5, 6], 'holidays': []}))
        self.spec = next(s for s in health.EXPECTED if s['id'] == 'premarket')
        self.data = {'date': '2026-11-02', 'trade_date': '2026-11-02',
                     'timestamp': '2026-11-01T22:06:26+08:00',
                     'analysis_time': '2026-11-01T22:06:26+08:00',
                     'status': 'premarket_plan_pending_auction'}

    def now(self, value):
        return datetime.fromisoformat(value + '+08:00')

    def rows(self, when, data=None):
        data = copy.deepcopy(self.data if data is None else data)
        path = self.root / 'data/premarket.json'
        path.write_text(json.dumps(data))
        original = path.read_bytes()
        now = self.now(when)
        with patch.object(health, 'ROOT', self.root), patch.object(health, 'DATA_DIR', self.root / 'data'):
            current, target = health.calendar_dates(now)
            result = (health.check_expected(self.spec, now, current, {}, {}),
                      health.next_session_row(self.spec, now, target))
        self.assertEqual(path.read_bytes(), original)
        return result

    def test_plan_pending_across_midnight_until_checkpoint(self):
        for when in ['2026-11-01T23:42:00', '2026-11-02T00:00:00', '2026-11-02T08:29:59']:
            with self.subTest(when=when):
                current, upcoming = self.rows(when)
                self.assertEqual((current['status'], upcoming['status']), ('waiting', 'pending'))
                for row in (current, upcoming):
                    self.assertEqual(row['deadline'], '2026-11-02T08:35:00+08:00')
                    self.assertEqual(row['analysis_coverage']['status'], 'pending')
                    self.assertEqual(row['analysis_coverage']['timestamp'], self.data['analysis_time'])
                    self.assertIn('竞价确认', row['reason'])
                    self.assertEqual(row['target_trade_date'], '2026-11-02')

    def test_morning_checkpoint_is_not_satisfied_by_overnight_plan(self):
        for when, expected in [('2026-11-02T08:30:00', ('waiting', 'pending')),
                               ('2026-11-02T08:35:00', ('late', 'overdue')),
                               ('2026-11-02T09:25:00', ('late', 'overdue'))]:
            current, upcoming = self.rows(when)
            self.assertEqual((current['status'], upcoming['status']), expected)
            self.assertEqual(current['analysis_coverage']['status'], 'stale')

    def test_actual_morning_analysis_still_becomes_ready(self):
        data = {**self.data, 'timestamp': '2026-11-02T08:30:00+08:00',
                'analysis_time': '2026-11-02T08:30:00+08:00', 'status': 'premarket_analysis'}
        current, upcoming = self.rows('2026-11-02T08:35:00', data)
        self.assertEqual((current['status'], upcoming['status']), ('ok', 'ready'))

    def test_invalid_or_redated_plans_do_not_get_exception(self):
        changes = [{'trade_date': None}, {'date': '2026-11-03'}, {'trade_date': '2026-11-03'},
                   {'status': 'unknown'}, {'source_status': 'invalidated'},
                   {'timestamp': 'bad'}, {'timestamp': '2026-11-02T01:00:00+08:00'},
                   {'analysis_time': None}, {'analysis_time': 'bad'},
                   {'analysis_time': '2026-11-02T01:00:00+08:00'},
                   {'analysis_time': '2026-10-29T22:00:00+08:00'},
                   {'analysis_time': '2026-11-01T23:00:00+08:00'}]
        for update in changes:
            with self.subTest(update=update):
                current, upcoming = self.rows('2026-11-01T23:42:00', {**self.data, **update})
                self.assertNotIn('target_trade_date', current)
                self.assertNotEqual(current['analysis_coverage']['status'], 'pending')
                self.assertNotEqual(upcoming['status'], 'ready')

    def test_calendar_failure_cannot_approve_plan(self):
        with patch.object(health, 'calendar_dates', side_effect=ValueError('calendar_unverified_or_outside_coverage')):
            self.assertIsNone(health.upcoming_premarket_row(self.spec, self.data, self.now('2026-11-01T23:42:00')))

    def test_degraded_source_quality_is_preserved(self):
        for state in ['degraded', 'degraded_partial']:
            for row in self.rows('2026-11-01T23:42:00', {**self.data, 'source_status': state}):
                self.assertEqual(row['data_status'], 'degraded')

    def test_other_processes_never_use_plan_exception(self):
        for spec in health.EXPECTED:
            if spec['id'] != 'premarket':
                self.assertIsNone(health.upcoming_premarket_row(spec, self.data, self.now('2026-11-01T23:42:00')))

    def test_wrong_next_session_target_not_reclassified(self):
        path = self.root / 'data/premarket.json'
        path.write_text(json.dumps(self.data))
        with patch.object(health, 'ROOT', self.root), patch.object(health, 'DATA_DIR', self.root / 'data'):
            row = health.next_session_row(self.spec, self.now('2026-11-01T23:42:00'), '2026-11-03')
        self.assertNotIn('target_trade_date', row)

    def test_verified_holiday_selects_actual_next_session(self):
        cal = json.loads(self.calendar.read_text())
        cal['holidays'] = ['2026-11-02']
        self.calendar.write_text(json.dumps(cal))
        current, _ = self.rows('2026-11-01T23:42:00')
        self.assertNotIn('target_trade_date', current)
        current, upcoming = self.rows('2026-11-01T23:42:00', {**self.data, 'date': '2026-11-03', 'trade_date': '2026-11-03'})
        self.assertEqual(current['target_trade_date'], '2026-11-03')
        self.assertEqual(upcoming['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
