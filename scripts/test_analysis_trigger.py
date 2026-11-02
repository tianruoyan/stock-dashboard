import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from check_analysis_trigger import check, SLOTS
from intraday_recovery import TZ


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.put('config/cn-market-calendar.json', dict(verification_state='verified', valid_from='2026-01-01', valid_to='2026-12-31', holidays=['2026-10-01']))

    def put(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data))

    def at(self, value):
        return check(self.root, datetime.fromisoformat(value).replace(tzinfo=TZ))

    def ready(self):
        self.put('data/premarket.json', dict(timestamp='2026-11-02T08:30:00+08:00', summary='test', strategy='test'))
        self.put('data/automation-health.json', dict(timestamp='2026-11-02T08:30:00+08:00', processes=[dict(id='premarket', status='ok')]))
        self.put('logs/publisher-status.json', dict(state='ok'))

    def test_closed_days_and_empty_slots(self):
        for t in ['2026-11-01T09:00', '2026-10-01T09:00', '2026-11-02T08:00', '2026-11-02T16:00', '2026-11-02T12:00']:
            self.assertEqual(self.at(t)['state'], 'skip', t)
        self.assertEqual(len(SLOTS), 18)

    def test_unknown_calendar_is_not_a_holiday(self):
        self.assertEqual(self.at('2027-01-04T09:00')['state'], 'needs_review')
        (self.root / 'config/cn-market-calendar.json').unlink()
        self.assertEqual(self.at('2026-11-02T09:00')['state'], 'needs_review')

    def test_missing_stale_and_future_evidence(self):
        self.assertEqual(self.at('2026-11-02T08:35')['state'], 'needs_review')
        self.ready()
        self.assertEqual(self.at('2026-11-02T08:35')['state'], 'skip')
        for stamp in ['2026-10-30T08:30:00+08:00', '2026-11-02T09:00:00+08:00']:
            self.put('data/premarket.json', dict(timestamp=stamp, summary='test', strategy='test'))
            self.assertEqual(self.at('2026-11-02T08:35')['state'], 'needs_review')

    def test_publication_failure_is_not_silenced(self):
        self.ready()
        self.put('logs/publisher-status.json', dict(state='failed'))
        self.assertEqual(self.at('2026-11-02T08:35')['state'], 'needs_review')

    def test_fresh_quotes_do_not_replace_current_analysis(self):
        self.ready()
        self.put('data/intraday.json', dict(timestamp='2026-11-02T10:00:00+08:00',
                 analysis_time='2026-11-02T09:30:00+08:00', summary='old analysis',
                 indices=[dict(quote_time='2026-11-02T10:00:00+08:00')]))
        self.put('data/automation-health.json', dict(timestamp='2026-11-02T10:00:00+08:00',
                 processes=[dict(id='intraday', status='ok')]))
        result = self.at('2026-11-02T10:01')
        self.assertEqual(result['state'], 'needs_review')
        self.assertTrue(any('10:00' in issue for issue in result['issues']))

    def test_evening_requires_p0_field(self):
        self.ready()
        self.put('data/evening-sentiment.json', dict(timestamp='2026-11-02T20:00:00+08:00', news=[]))
        result = self.at('2026-11-02T20:05')
        self.assertIn('missing_fields:p0_alerts', result['issues'])

    def test_reads_do_not_mutate_inputs(self):
        self.ready()
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.at('2026-11-02T08:35')
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()
