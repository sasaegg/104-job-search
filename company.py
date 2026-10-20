"""Company capital lookup. Amounts are stored in TWD; missing values stay None."""
import re
import threading
from decimal import Decimal
from urllib.parse import urlsplit

import requests

from crawler import USER_AGENT

_lookup_lock = threading.Lock()


def ParseCapital(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).replace(',', '').replace(' ', '').strip()
    text = re.sub(r'^(新[臺台]幣|NT\$|TWD)', '', text, flags=re.I)
    text = re.sub(r'(元|圓)(整)?$', '', text)
    if not re.fullmatch(r'(?:\d+(?:\.\d+)?[億萬千百]?)+', text):
        return None
    units = {'億': 100000000, '萬': 10000, '千': 1000, '百': 100, '': 1}
    return int(sum(Decimal(number) * units[unit]
                   for number, unit in re.findall(r'(\d+(?:\.\d+)?)([億萬千百]?)', text)))


def CapitalFromData(data):
    if not isinstance(data, dict):
        return None
    for key in ('capitalDesc', 'capital'):
        amount = ParseCapital(data.get(key))
        if amount is not None:
            return amount
    for key in ('data', 'custInfo', 'company', 'companyInfo'):
        amount = CapitalFromData(data.get(key))
        if amount is not None:
            return amount
    return None


def FillCompanyCapital(row, storage, log=print, pause=lambda: None, missing=None):
    url = urlsplit(row.get('jobCompanyUrl') or '')
    match = re.fullmatch(r'/company/([a-zA-Z0-9]+)/?', url.path)
    if url.hostname != 'www.104.com.tw' or not match:
        row['jobCompanyCapital'] = None
        return
    companyId = match[1]
    # Serialize cache misses across concurrent watches so one company is fetched once.
    with _lookup_lock:
        cached = storage.GetCompanyCapital(companyId)
        if cached is not None:
            row['jobCompanyCapital'] = cached['amount']
            return
        if missing is not None and companyId in missing:
            row['jobCompanyCapital'] = None
            return
        amount = None
        try:
            response = requests.get('https://www.104.com.tw/api/companies/' + companyId + '/content',
                                    headers={'User-Agent': USER_AGENT,
                                             'Referer': 'https://www.104.com.tw/company/' + companyId}, timeout=20)
            response.raise_for_status()
            amount = CapitalFromData(response.json())
        except (requests.RequestException, ValueError) as error:
            log('無法取得「' + row.get('jobCompanyName', '') + '」資本額，保留職缺：' + str(error))
        # Only successful amounts belong in the persistent cache. A failed lookup
        # must be retried on the next run, even if an older version cached NULL.
        if amount is not None:
            storage.SetCompanyCapital(companyId, amount)
        elif missing is not None:
            missing.add(companyId)
        row['jobCompanyCapital'] = amount
        pause()
