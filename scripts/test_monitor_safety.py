import functools
import http.client
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import build_automation_health as health
import build_decision_feed as feed
from local_http_guard import LocalHTTPGuard


class GuardHandler(LocalHTTPGuard, SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class MonitorSafetyTests(unittest.TestCase):
    def test_old_weekday_watch_cannot_be_current_opportunity(self):
        files={'opportunity-watch.json':{'items':[
            {'theme':'旧线索','source_reason':'周二等待触发'},
            {'theme':'当日线索','source_reason':'周四等待触发'}]}}
        titles=[row['title'] for row in feed.build_opportunities(files,'2026-09-10')]
        self.assertNotIn('待触发：旧线索',titles)
        self.assertIn('待触发：当日线索',titles)

    def test_current_file_is_not_current_analysis(self):
        spec = next(s for s in health.EXPECTED if s['id'] == 'intraday')
        now = datetime(2026, 9, 10, 14, 30, tzinfo=health.TZ)
        for data in [
            {'timestamp': '2026-09-10T09:30:00+08:00', 'market_time': '2026-09-10T14:29:00+08:00'},
            {'timestamp': '2026-09-10T14:01:00+08:00', 'market_time': '2026-09-10T09:30:00+08:00'},
            {'timestamp': '2026-09-10T14:01:00+08:00'},
            {'timestamp': '2026-09-10T15:00:00+08:00', 'market_time': '2026-09-10T15:00:00+08:00'},
        ]:
            with self.subTest(data=data), patch.object(health, 'load_json', return_value=data):
                self.assertEqual(health.next_session_row(spec, now, '2026-09-10')['status'], 'overdue')

    def test_lunch_does_not_age_valid_morning_checkpoint(self):
        spec = next(s for s in health.EXPECTED if s['id'] == 'intraday')
        data = {'timestamp': '2026-09-10T11:32:00+08:00', 'market_time': '2026-09-10T11:30:00+08:00'}
        with patch.object(health, 'load_json', return_value=data):
            self.assertEqual(health.next_session_row(spec, datetime(2026,9,10,12,45,tzinfo=health.TZ), '2026-09-10')['status'], 'ready')

    def test_morning_file_does_not_complete_evening(self):
        spec = next(s for s in health.EXPECTED if s['id'] == 'evening')
        with patch.object(health, 'load_json', return_value={'timestamp':'2026-09-10T07:30:00+08:00'}):
            self.assertEqual(health.next_session_row(spec, datetime(2026,9,10,21,45,tzinfo=health.TZ), '2026-09-10')['status'], 'overdue')

    def test_private_paths_origins_and_symlinks_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root/'index.html').write_text('public')
            (root/'.v2_private').mkdir()
            (root/'.v2_private/portfolio.json').write_text('private-fixture')
            (root/'escape').symlink_to(outside, target_is_directory=True)
            (Path(outside)/'secret').write_text('outside-fixture')
            srv=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(GuardHandler,directory=str(root)))
            thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
            try:
                for method,path,headers,expected in [
                    ('GET','/index.html',{},200),
                    ('GET','/.v2_private/portfolio.json',{},403),
                    ('HEAD','/%2ev2_private/portfolio.json',{},403),
                    ('GET','/escape/secret',{},403),
                    ('POST','/_save-config',{'Origin':'https://example.invalid','Content-Type':'application/json'},403),
                    ('GET','/_health',{'Host':'rebind.invalid'},403),
                ]:
                    conn=http.client.HTTPConnection('127.0.0.1',srv.server_port)
                    conn.request(method,path,headers=headers)
                    response=conn.getresponse();body=response.read();conn.close()
                    self.assertEqual(response.status,expected,(method,path))
                    self.assertNotIn(b'private-fixture',body)
            finally:
                srv.shutdown();srv.server_close();thread.join()
