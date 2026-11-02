#!/usr/bin/env python3
"""Read-only, bounded preflight for the existing Codex analysis heartbeat."""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from intraday_recovery import TZ, is_trading_day, parse_datetime
from build_automation_health import EXPECTED, evidence_issue, timestamp_coverage

ROOT = Path(__file__).resolve().parents[1]
SLOTS = {
    '08:30': 'premarket', '09:00': 'premarket',
    '09:30': 'intraday', '10:00': 'intraday', '10:30': 'intraday',
    '11:00': 'intraday', '11:30': 'midday', '13:00': 'intraday',
    '13:30': 'intraday', '14:00': 'intraday', '14:30': 'intraday',
    '15:00': 'intraday', '15:30': 'topics', '16:30': 'postmarket',
    '20:00': 'evening', '20:30': 'evening', '21:00': 'final', '21:30': 'final',
}
REQUIRED = {
    'premarket': ['summary', 'strategy'], 'intraday': ['summary'],
    'midday': ['morning_snapshot', 'morning_review', 'afternoon_watch', 'risk'],
    'postmarket': ['review', 'hotspots', 'next_day_watch', 'closing_auction_patch'],
    'evening': ['news', 'p0_alerts'], 'topics': ['topics'],
}


def read(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'{path.name}: expected object')
    return value


def check(root, now):
    now = now.astimezone(TZ)
    result = {'state': 'needs_review', 'time': now.isoformat(), 'issues': []}
    try:
        calendar = read(root / 'config/cn-market-calendar.json')
        day = now.date().isoformat()
        if (calendar.get('verification_state') != 'verified' or
                not calendar.get('valid_from', '') <= day <= calendar.get('valid_to', '')):
            raise ValueError('calendar_unverified_or_expired')
        if not is_trading_day(root, now):
            return dict(result, state='skip', reason='non_trading_day')
        eligible = [(now.replace(hour=int(slot[:2]), minute=int(slot[3:]), second=0, microsecond=0), stage)
                    for slot, stage in SLOTS.items()]
        eligible = [(at, stage) for at, stage in eligible if timedelta(0) <= now-at < timedelta(minutes=25)]
        if not eligible:
            return dict(result, state='skip', reason='outside_checkpoint_window')
        at, stage = max(eligible)
        result.update(stage=stage, checkpoint=at.isoformat())
        specs = [s for s in EXPECTED if s['id'] == ('evening' if stage == 'final' else stage)]
        for spec in specs:
            data = read(root / 'data' / spec['file'])
            issue = evidence_issue(spec, data, now, day)
            if issue:
                result['issues'].append(issue)
            # The producer runs at this checkpoint, not the preceding half hour.
            if stage == 'intraday':
                issue = timestamp_coverage(data.get('analysis_time') or data.get('timestamp'), at, now, '分析')['reason']
                if issue:
                    result['issues'].append(issue)
            missing = [key for key in REQUIRED[spec['id']] if key not in data]
            if missing:
                result['issues'].append('missing_fields:' + ','.join(missing))
            if data.get('source_status') == 'invalidated':
                result['issues'].append('source_invalidated')
        health = read(root / 'data/automation-health.json')
        stamp = parse_datetime(health.get('timestamp'))
        if not stamp or not timedelta(0) <= now-stamp <= timedelta(minutes=35):
            result['issues'].append('automation_health_stale_or_future')
        relevant = {stage, 'alerts'} if stage == 'intraday' else {stage}
        for row in health.get('processes', []):
            if stage == 'final' or row.get('id') in relevant:
                if row.get('status') in {'late', 'missing', 'invalidated'}:
                    result['issues'].append('health:' + str(row.get('id')) + ':' + str(row.get('failure_type')))
        if not isinstance(health.get('processes'), list) or not health['processes']:
            result['issues'].append('automation_health_processes_missing')
        # Publication failures must not be hidden by a fresh analysis file.
        publisher = read(root / 'logs/publisher-status.json')
        if publisher.get('state') != 'ok':
            result['issues'].append('publisher:' + str(publisher.get('state')))
        if (root / '.publish-pending').exists():
            result['issues'].append('publication_pending')
        if stage == 'final':
            for filename in ['build-report.json', 'runtime-smoke-report.json']:
                report = read(root / 'data' / filename)
                if report.get('status') not in {'ok', 'passed', 'degraded'}:
                    result['issues'].append(filename + ':' + str(report.get('status')))
        result['issues'] = list(dict.fromkeys(result['issues']))
        if not result['issues']:
            result.update(state='skip', reason='checkpoint_evidence_ready')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result['issues'].append(str(exc))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--now', help='ISO timestamp for deterministic verification')
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(TZ)
    if now is None:
        parser.error('invalid --now')
    print(json.dumps(check(args.root, now), ensure_ascii=False))
