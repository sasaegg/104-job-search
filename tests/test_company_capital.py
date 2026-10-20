import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from company import CapitalFromData, FillCompanyCapital, ParseCapital
from storage import Storage


class CompanyCapitalTests(unittest.TestCase):
    def test_units_and_missing_values(self):
        for text, expected in [('1億5000萬元', 150000000), ('新台幣1.5億元', 150000000),
                               ('2,000,000元', 2000000), ('300萬', 3000000),
                               ('0', 0), ('暫不提供', None), ('100萬美元', None),
                               ('', None), (None, None), (True, None)]:
            with self.subTest(text=text):
                self.assertEqual(ParseCapital(text), expected)
        self.assertEqual(CapitalFromData({'data': {'custInfo': {'capital': '2億元'}}}), 200000000)

    def test_lookup_cached_across_runs_and_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'history.db')
            store = Storage(path)
            row = {'jobNo': '1', 'jobCompanyName': '公司',
                   'jobCompanyUrl': 'https://www.104.com.tw/company/abc?jobsource=test'}
            response = Mock()
            # Shape and unit verified against the current public company API.
            response.json.return_value = {'data': {'custNo': 'abc', 'capital': '5億'}}
            with patch('company.requests.get', return_value=response) as get:
                FillCompanyCapital(row, store)
                FillCompanyCapital(dict(row), Storage(path))
                self.assertEqual(get.call_count, 1)
                self.assertEqual(get.call_args.args[0], 'https://www.104.com.tw/api/companies/abc/content')
            self.assertEqual(row['jobCompanyCapital'], 500000000)
            watch = store.CreateWatch('test', {}, 1, False)
            run = store.StartRun(watch)
            store.RecordRow(run, watch, row, True)
            self.assertEqual(store.GetRun(run)['rows'][0]['jobCompanyCapital'], 500000000)
            row['jobCompanyCapital'] = None
            store.RecordRow(run, watch, row, False)
            self.assertEqual(store.GetRun(run)['rows'][0]['jobCompanyCapital'], 500000000)

    def test_failure_is_deduplicated_but_retried_next_run(self):
        store = Mock()
        store.GetCompanyCapital.return_value = None
        row = {'jobCompanyUrl': 'https://www.104.com.tw/company/abc'}
        with patch('company.requests.get', side_effect=requests.HTTPError('403')) as get:
            missing = set()
            FillCompanyCapital(row, store, log=Mock(), missing=missing)
            FillCompanyCapital(row, store, log=Mock(), missing=missing)
            self.assertEqual(get.call_count, 1)
            FillCompanyCapital(row, store, log=Mock(), missing=set())
            self.assertEqual(get.call_count, 2)
        self.assertIsNone(row['jobCompanyCapital'])
        store.SetCompanyCapital.assert_not_called()

    def test_legacy_failure_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(str(Path(directory) / 'history.db'))
            store.SetCompanyCapital('abc', None)
            self.assertIsNone(store.GetCompanyCapital('abc'))
            store.SetCompanyCapital('abc', 0)
            self.assertEqual(store.GetCompanyCapital('abc'), {'amount': 0})


if __name__ == '__main__':
    unittest.main()
