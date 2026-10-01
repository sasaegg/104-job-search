# 104人力銀行爬蟲核心
# 供 app.py (網頁介面) 與 watcher.py (追蹤) 使用
import time
import datetime
import requests
import pandas as pd

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' + \
             '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
SEARCH_URL = 'https://www.104.com.tw/jobs/search/api/jobs'
DETAIL_URL = 'https://www.104.com.tw/job/ajax/content/'
CATEGORY_URL = 'https://static.104.com.tw/category-tool/json/{}.json'

# 篩選選項 (代碼取自104搜尋頁前端程式)
FILTER_OPTIONS = {
    'ro': [(0, '全部'), (1, '全職'), (2, '兼職'), (3, '高階'), (4, '派遣')],
    'isnew': [(0, '本日最新'), (3, '三日內'), (7, '一週內'), (14, '二週內'), (30, '一個月內')],
    'jobexp': [(1, '1年以下'), (3, '1-3年'), (5, '3-5年'), (10, '5-10年'), (99, '10年以上')],
    's9': [(1, '日班'), (2, '晚班'), (4, '大夜班'), (8, '假日班')],
    's5': [(0, '不需輪班'), (256, '輪班')],
    'edu': [(4, '大學以上'), (5, '碩士以上'), (6, '博士以上')],
    'zone': [(16, '上市上櫃'), (5, '外商一般'), (4, '外商資訊')],
    'order': [(15, '符合度'), (16, '最近更新')],
}

# 104 isnew只接受這幾個值 自訂天數時取不小於它的最小值 再依appearDate自行過濾
ISNEW_ALLOWED = [0, 3, 7, 14, 30]

EDU_NAME = {1: '高中以下', 2: '高中', 3: '專科', 4: '大學', 5: '碩士', 6: '博士'}
SALARY_TYPE = {10: '待遇面議', 20: '論件計酬', 30: '時薪', 40: '日薪', 50: '月薪', 60: '年薪', 70: '部分工時(月薪)'}
SALARY_UNLIMITED = 9999999

COLUMNS = ['jobNo', 'matchedKeywords', 'jobAnnounceDate', 'jobTitles', 'jobCompanyName', 'jobCompanyUrl', 'jobCompanyIndustry',
           'jobContent', 'jobCategory', 'jobSalary', 'jobLocation', 'jobRqYear', 'jobRqEducation',
           'jobRqDepartment', 'jobSpecialty', 'jobOthers', 'jobDetailUrl']


def GetCategory(name):
    # 取得104分類代碼樹 name: Area(地區) / Indust(產業)
    response = requests.get(CATEGORY_URL.format(name), headers={'User-Agent': USER_AGENT}, timeout=20)
    response.raise_for_status()
    return response.json()


class RequestRejected(Exception):
    # 104拒絕請求(參數錯誤等4xx) 重試也不會成功
    pass


# 確認是否有正常連線 (404代表職務不存在 視為成功 交由呼叫端判斷)
def CheckConnect(url, headers, params=None):
    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
    except Exception as e:
        return None, str(e)
    if 400 <= response.status_code < 500 and response.status_code not in (404, 429):
        raise RequestRejected('104拒絕請求 HTTP ' + str(response.status_code) + ': ' + response.text[:200])
    if response.status_code not in (200, 404):
        return None, 'HTTP狀態碼: ' + str(response.status_code)
    return response, None


def KeywordsOf(filters):
    # 取得關鍵字清單 相容舊版單一keyword字串 去除空白與重複 未填時回傳['']代表不帶關鍵字
    keywords = filters.get('keywords')
    if keywords is None:
        keywords = [filters.get('keyword') or '']
    result = list()
    for kw in keywords:
        kw = str(kw).strip()
        if kw and kw not in result:
            result.append(kw)
    return result or ['']


def BuildSearchParams(filters, page, keyword=''):
    # 將篩選條件轉為104搜尋API參數 多選值以逗號串接
    params = {'order': filters.get('order', 15), 'asc': 0, 'page': page, 'pagesize': 20}
    # 空字串keyword會被104拒絕(400) 未填時不送
    if keyword:
        params['keyword'] = keyword
    if filters.get('ro'):
        params['ro'] = filters['ro']
    if filters.get('newDays'):
        isnew = next((v for v in ISNEW_ALLOWED if v >= int(filters['newDays'])), None)
        if isnew is not None:
            params['isnew'] = isnew
    elif filters.get('isnew') not in (None, ''):
        params['isnew'] = filters['isnew']
    if filters.get('s5') not in (None, ''):
        params['s5'] = filters['s5']
    if filters.get('wktm'):
        params['wktm'] = 1
    if filters.get('oneClass'):
        params['label'] = 'one_class'
    # 學歷門檻: 104只能篩「接受該學歷」 先縮小範圍 再由FilterByEdu篩最低要求
    if filters.get('edu'):
        params['edu'] = ','.join(str(i) for i in range(int(filters['edu']), 7))
    for key in ('area', 'jobexp', 's9', 'indcat', 'zone'):
        if filters.get(key):
            params[key] = ','.join(str(v) for v in filters[key])
    return params


def PassEduFilter(job, minEdu):
    # 職缺最低學歷要求需達門檻 (學歷不拘=接受所有學歷 視為未達門檻)
    if not minEdu:
        return True
    optionEdu = job.get('optionEdu') or []
    return bool(optionEdu) and min(optionEdu) >= int(minEdu)


def NewDaysCutoff(newDays):
    # N天內(含今天) 例如1=只有今天 回傳最早可接受的appearDate字串 YYYYMMDD
    if not newDays:
        return None
    return (datetime.date.today() - datetime.timedelta(days=int(newDays) - 1)).strftime('%Y%m%d')


def FormatSalary(salaryType, low, high):
    if salaryType == 10 or (not low and not high):
        return '待遇面議'
    prefix = SALARY_TYPE.get(salaryType, '')
    if high >= SALARY_UNLIMITED:
        return prefix + '{:,}元以上'.format(low)
    if low == high:
        return prefix + '{:,}元'.format(low)
    return prefix + '{:,}~{:,}元'.format(low, high)


def FormatEdu(optionEdu):
    if not optionEdu or len(optionEdu) == 6:
        return '不拘'
    return '、'.join(EDU_NAME[i] for i in sorted(optionEdu) if i in EDU_NAME)


def FormatPeriod(period):
    # period: 0=不拘 其餘為 N+1 代表 N年以上
    return '不拘' if not period else str(period - 1) + '年以上'


def RowFromSearch(job):
    # 僅用搜尋列表資訊組成一筆資料
    return {
        'jobNo': str(job.get('jobNo', '')),
        'matchedKeywords': '',
        'jobAnnounceDate': job.get('appearDate', ''),
        'jobTitles': job.get('jobName', ''),
        'jobCompanyName': job.get('custName', ''),
        'jobCompanyUrl': job['link'].get('cust', ''),
        'jobCompanyIndustry': job.get('coIndustryDesc', ''),
        'jobContent': job.get('description', ''),
        'jobCategory': '',
        'jobSalary': FormatSalary(job.get('s10'), job.get('salaryLow', 0), job.get('salaryHigh', 0)),
        'jobLocation': job.get('jobAddrNoDesc', ''),
        'jobRqYear': FormatPeriod(job.get('period', 0)),
        'jobRqEducation': FormatEdu(job.get('optionEdu')),
        'jobRqDepartment': ','.join(job.get('major') or []),
        'jobSpecialty': '',
        'jobOthers': '',
        'jobDetailUrl': job['link'].get('job', ''),
    }


def FillDetail(row, data):
    # 以詳細頁資訊補齊欄位
    row['jobContent'] = data['jobDetail']['jobDescription']
    row['jobCategory'] = ','.join([elem['description'] for elem in data['jobDetail']['jobCategory']])
    row['jobSalary'] = data['jobDetail']['salary']
    row['jobRqYear'] = data['condition']['workExp']
    row['jobRqEducation'] = data['condition']['edu']
    row['jobRqDepartment'] = ','.join(data['condition']['major'])
    # 擅長工具 (新版另有技能欄位 一併納入)
    row['jobSpecialty'] = ','.join([elem['description'] for elem in
                                    data['condition']['specialty'] + data['condition']['skill']])
    row['jobOthers'] = data['condition']['other']


class Crawler:
    # 可在背景執行緒中執行 透過屬性回報進度 呼叫stop()可中止
    # onRow(row, added): 每新增一筆(added=True) 或既有職缺被另一個關鍵字搜到(added=False)時呼叫
    # skipJobNos: 使用者隱藏的jobNo 直接略過 (不抓詳細資料 不回呼onRow)
    def __init__(self, filters, maxPage=10, fetchDetail=True, detailDelay=3, pageDelay=1, log=print, onRow=None,
                 skipJobNos=None):
        self.filters = filters
        self.skipJobNos = set(skipJobNos or [])
        self.keywords = KeywordsOf(filters)
        self.maxPage = maxPage
        self.fetchDetail = fetchDetail
        self.detailDelay = detailDelay
        self.pageDelay = pageDelay
        self.log = log
        self.onRow = onRow
        self.rows = list()
        self._byJobNo = dict()
        self.keywordIndex = 0
        self.keyword = ''
        self.page = 0
        self.lastPage = None
        self.total = None
        self.skipped = 0
        self.endReasons = list()
        self.status = 'pending'  # pending / running / done / stopped / error
        self.message = ''
        self._stop = False
        self._stopReason = '手動停止'

    def stop(self, reason='手動停止'):
        self._stopReason = reason
        self._stop = True

    def _sleep(self, seconds):
        # 可被stop()中斷的等待
        end = time.time() + seconds
        while not self._stop and time.time() < end:
            time.sleep(0.2)

    def _get(self, url, headers, params=None):
        # 失敗時重試 若累計5次仍失敗則回傳None
        for tryNums in range(5):
            response, error = CheckConnect(url, headers, params)
            if response is not None:
                return response
            self.log('下載失敗(' + error + ') 程式暫停120秒')
            self._sleep(120)
            if self._stop:
                return None
        self.log('下載失敗次數累積5次')
        return None

    def _label(self):
        # 多關鍵字時 訊息前綴目前關鍵字
        return '「' + self.keyword + '」' if len(self.keywords) > 1 else ''

    def run(self):
        self.status = 'running'
        try:
            for index, keyword in enumerate(self.keywords):
                if self._stop:
                    break
                self.keywordIndex = index
                self.keyword = keyword
                self.page = 0
                self.lastPage = None
                self.total = None
                self._runKeyword(keyword)
            if self._stop:
                self.status = 'stopped'
                self.endReasons.append('在' + self._label() + '第' + str(self.page) + '頁' + self._stopReason)
            else:
                self.status = 'done'
            self.message = '；'.join(self.endReasons)
        except Exception as e:
            self.status = 'error'
            self.message = self._label() + str(e)
            self.log('發生錯誤: ' + self.message)
        return self.rows

    def _end(self, reason):
        # 記錄結束原因 顯示於介面狀態列
        reason = (self.keyword + '：' if len(self.keywords) > 1 else '') + reason
        self.endReasons.append(reason)
        self.log(reason)

    def _addJob(self, job, keyword):
        # 以jobNo去重 重複職缺只累加符合關鍵字 不重抓詳細資料
        jobNo = str(job.get('jobNo', ''))
        existing = self._byJobNo.get(jobNo)
        if existing is not None:
            matched = existing['matchedKeywords'].split(', ') if existing['matchedKeywords'] else []
            if keyword and keyword not in matched:
                existing['matchedKeywords'] = ', '.join(matched + [keyword])
                if self.onRow:
                    self.onRow(existing, False)
            return

        row = RowFromSearch(job)
        row['matchedKeywords'] = keyword
        if self.fetchDetail:
            # 詳細資訊需透過額外的ajax爬取 (需帶Referer)
            jobCode = row['jobDetailUrl'].rstrip('/').split('/')[-1]
            detailHeaders = {'User-Agent': USER_AGENT, 'Referer': row['jobDetailUrl']}
            response = self._get(DETAIL_URL + jobCode, detailHeaders)
            # 判斷是否有error: 職務不存在 或下載失敗 則只保留搜尋頁的資訊
            detail = response.json() if response is not None else {'error': True}
            if not detail.get('error'):
                FillDetail(row, detail['data'])
            # 暫停秒數避免爬太快
            self._sleep(self.detailDelay)
        self._byJobNo[jobNo] = row
        self.rows.append(row)
        if self.onRow:
            self.onRow(row, True)

    def _runKeyword(self, keyword):
        searchHeaders = {'User-Agent': USER_AGENT, 'Referer': 'https://www.104.com.tw/jobs/search/'}
        minEdu = self.filters.get('edu')
        cutoff = NewDaysCutoff(self.filters.get('newDays'))
        sortByDate = int(self.filters.get('order', 15)) == 16

        for page in range(1, self.maxPage + 1):
            if self._stop:
                return
            self.page = page

            response = self._get(SEARCH_URL, searchHeaders, BuildSearchParams(self.filters, page, keyword))
            if response is None:
                self._end('搜尋頁下載失敗')
                return
            result = response.json()
            jobList = result.get('data') or []
            pagination = result['metadata']['pagination']
            self.lastPage = pagination['lastPage']
            self.total = pagination['total']

            # 確認是否已查詢到底
            if not jobList:
                self._end('第' + str(page) + '頁已無職缺 搜尋結果已到底')
                return

            for i, job in enumerate(jobList):
                if self._stop:
                    return
                # appearDate空值為104廣告職缺 與搜尋職缺較不相關 直接略過
                # 更新日期超過自訂天數 或學歷不符 也略過
                appearDate = job.get('appearDate')
                tooOld = cutoff and appearDate and appearDate < cutoff
                hidden = str(job.get('jobNo', '')) in self.skipJobNos
                if hidden or not appearDate or tooOld or not PassEduFilter(job, minEdu):
                    self.skipped += 1
                    continue
                if self.fetchDetail and str(job.get('jobNo', '')) not in self._byJobNo:
                    self.log(self._label() + '第' + str(page) + '/' + str(self.lastPage) + '頁 ' +
                             str(i + 1) + '/' + str(len(jobList)) + ' ' + job.get('jobName', ''))
                self._addJob(job, keyword)

            if not self.fetchDetail:
                self.log(self._label() + '第' + str(page) + '/' + str(self.lastPage) + '頁完成 累計' +
                         str(len(self.rows)) + '筆')
            if page >= self.lastPage:
                self._end('104符合條件的職缺只有' + str(self.lastPage) + '頁 已全部爬完')
                return
            # 依最近更新排序時 整頁都超過天數 代表後面也不會有符合的職缺
            dates = [j['appearDate'] for j in jobList if j.get('appearDate')]
            if cutoff and sortByDate and dates and max(dates) < cutoff:
                self._end('第' + str(page) + '頁之後的職缺都超過' + str(self.filters['newDays']) + '天 提前結束')
                return
            self._sleep(self.pageDelay)
        self._end('已爬完設定的' + str(self.maxPage) + '頁')

    def to_dataframe(self, rows=None, extraColumns=None):
        return ToDataFrame(self.rows if rows is None else rows, self.keywords, self.maxPage, extraColumns)


def ToDataFrame(rows, keywords, maxPage, extraColumns=None, searchTime=None):
    # 輸出CSV用 extraColumns: 額外欄位名稱(例如isNew) 需已存在於rows中
    outputDf = pd.DataFrame(rows, columns=COLUMNS + (extraColumns or []))
    # 加入本次搜尋資訊
    outputDf.insert(0, 'maxPage', maxPage, True)
    outputDf.insert(0, 'keyword', ', '.join(k for k in keywords if k), True)
    outputDf.insert(0, 'searchTime', searchTime or datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), True)
    return outputDf


def CsvFileName(keywords, suffix='爬蟲搜尋結果'):
    # 例: 20260925093000104人力銀行_數據分析_BI_爬蟲搜尋結果.csv
    name = '_'.join(k for k in keywords if k)[:40] or '全部'
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, '')
    return datetime.datetime.now().strftime('%Y%m%d%H%M%S') + '104人力銀行_' + name + '_' + suffix + '.csv'
