import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sources import html_candidates, feed_candidates, normalize, to_issue, load_issues
from monitor import read_state, run, authorized_pdf_link, download_pdf

FIX = Path(__file__).parent / 'fixtures'

class MetadataTests(unittest.TestCase):
    def test_html_parse_and_filter(self):
        html = (FIX/'magazinelib.html').read_text(encoding='utf-8')
        result = normalize(html_candidates(html), 'asia')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].key, '2026-10-24:asia')

    def test_other_editions(self):
        html = (FIX/'magazinelib.html').read_text(encoding='utf-8')
        items = normalize(html_candidates(html), 'all')
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0].date, '2026-10-31')
        self.assertEqual({i.edition for i in items}, {'asia','uk','usa','middle-east-africa'})

    def test_rss_parse(self):
        content = (FIX/'magazinelib.xml').read_text(encoding='utf-8')
        result = normalize(feed_candidates(content), 'asia')
        self.assertEqual(len(result), 1)

    def test_bad_link_and_bad_date(self):
        self.assertIsNone(to_issue('The Economist Asia Edition – 60 October 2026','https://magazinelib.com/all/the-economist-asia-2026/'))
        self.assertIsNone(to_issue('The Economist Asia Edition – 24 October 2026','https://evil.example/all/the-economist-asia-edition-24-october-2026/'))

    def test_authorized_url_template(self):
        issue = load_issues('asia', fixture=str(FIX/'magazinelib.html'))[0][0]
        with patch.dict(os.environ, {'PDF_URL_TEMPLATE': 'https://licensed.example.com/{date}/{edition}.pdf'}, clear=True):
            self.assertEqual(authorized_pdf_link(issue, {}), 'https://licensed.example.com/2026-10-24/asia.pdf')

    def test_authorized_mapping(self):
        issue = load_issues('asia', fixture=str(FIX/'magazinelib.html'))[0][0]
        self.assertEqual(authorized_pdf_link(issue, {'2026-10-24:asia': 'https://publisher.example/test.pdf'}), 'https://publisher.example/test.pdf')


class StateTests(unittest.TestCase):
    def test_first_and_second_run_no_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)/'state.json'
            with patch.dict(os.environ, {'PDF_URL_MAP_JSON': ''}, clear=True):
                r1 = run('asia',str(FIX/'magazinelib.html'),no_notify=True,state_path=state)
                r2 = run('asia',str(FIX/'magazinelib.html'),no_notify=True,state_path=state)
            self.assertEqual((r1,r2),(0,0))
            self.assertEqual(len(read_state(state)['seen']),1)
            self.assertFalse(read_state(state)['seen']['2026-10-24:asia']['initial_baseline'])

    def test_missing_source_never_marks_seen(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)/'state.json'
            with patch.dict(os.environ, {'PDF_URL_MAP_JSON': ''}, clear=True):
                with self.assertRaises(RuntimeError):
                    run('asia',str(FIX/'empty.html'),no_notify=True,state_path=state)
            self.assertFalse(state.exists())

    def test_invalid_json_fails_before_changes(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)/'state.json'
            with patch.dict(os.environ, {'PDF_URL_MAP_JSON':'not-json'}, clear=True):
                with self.assertRaises(json.JSONDecodeError):
                    run('asia',str(FIX/'magazinelib.html'),no_notify=True,state_path=state)
            self.assertFalse(state.exists())


    def test_download_bad_content_rejected(self):
        from io import BytesIO
        issue = load_issues('asia', fixture=str(FIX/'magazinelib.html'))[0][0]
        class FakeResponse:
            def __init__(self): self.stream = BytesIO(b'<html>Login required</html>')
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def geturl(self): return 'https://licensed.example.com/issue.pdf'
            def read(self,n): return self.stream.read(n)
        with tempfile.TemporaryDirectory() as d:
            with patch('monitor.urlopen', return_value=FakeResponse()):
                with self.assertRaisesRegex(ValueError, 'not a valid-looking PDF'):
                    download_pdf('https://licensed.example.com/issue.pdf',issue,Path(d))
            self.assertFalse(list(Path(d).glob('*.pdf')))

    def test_download_good_pdf_and_hash(self):
        from io import BytesIO
        from hashlib import sha256
        issue = load_issues('asia', fixture=str(FIX/'magazinelib.html'))[0][0]
        pdf = b'%PDF-1.7\n' + b'example licensed test document bytes'
        class FakeResponse:
            def __init__(self): self.stream = BytesIO(pdf)
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def geturl(self): return 'https://licensed.example.com/issue.pdf'
            def read(self,n): return self.stream.read(n)
        with tempfile.TemporaryDirectory() as d:
            with patch('monitor.urlopen', return_value=FakeResponse()):
                name, digest = download_pdf('https://licensed.example.com/issue.pdf',issue,Path(d))
            self.assertEqual(digest,sha256(pdf).hexdigest())
            self.assertEqual((Path(d)/name).read_bytes(),pdf)

    def test_failed_download_stays_retryable(self):
        issue = load_issues('asia', fixture=str(FIX/'magazinelib.html'))[0][0]
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)/'seen.json'
            with patch.dict(os.environ, {'PDF_URL_MAP_JSON': json.dumps({issue.key:'https://licensed.example.com/issue.pdf'})}, clear=True):
                with patch('monitor.download_pdf', side_effect=ValueError('site unavailable')):
                    code = run('asia',str(FIX/'magazinelib.html'),no_notify=True,state_path=state)
                self.assertEqual(code,2)
                self.assertEqual(read_state(state)['seen'][issue.key]['pdf_status'],'failed')
                with patch('monitor.download_pdf', return_value=('file.pdf','valid-sha')):
                    code = run('asia',str(FIX/'magazinelib.html'),no_notify=True,state_path=state)
                self.assertEqual(code,0)
                self.assertEqual(read_state(state)['seen'][issue.key]['pdf_status'],'downloaded')

if __name__ == '__main__':
    unittest.main()
