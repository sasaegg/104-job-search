# 104人力銀行爬蟲 網頁介面
# 執行後會自動開啟瀏覽器 http://127.0.0.1:5104
import io
import re
import os
import sys
import uuid
import datetime
import threading
import webbrowser
from collections import deque
from flask import Flask, jsonify, request, send_file, abort
from crawler import Crawler, GetCategory, FILTER_OPTIONS, KeywordsOf, ToDataFrame, CsvFileName
from storage import Storage, DuplicateName
from watcher import WatchRun, BatchRun
from lifecycle import ClientWatchdog

PORT = 5104
# PyInstaller打包後 靜態檔案位於暫存解壓目錄
BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'), static_url_path='/static')
storage = Storage()

_categoryCache = {}
_jobs = {}
_lock = threading.Lock()


def Category(name):
    if name not in _categoryCache:
        _categoryCache[name] = GetCategory(name)
    return _categoryCache[name]


def ClampPage(value):
    return max(1, min(int(value or 5), 150))


@app.get('/')
def Index():
    return app.send_static_file('index.html')


@app.get('/api/options')
def Options():
    try:
        return jsonify({
            'filters': {k: [{'value': v, 'label': l} for v, l in opts] for k, opts in FILTER_OPTIONS.items()},
            'area': Category('Area'),
            'indust': Category('Indust'),
        })
    except Exception as e:
        return jsonify({'error': '無法取得104分類資料: ' + str(e)}), 502


# ---------- 爬蟲執行 (一般搜尋與追蹤共用進度輪詢) ----------
def StartCrawl(makeCrawler):
    # makeCrawler(log) 回傳 (crawler, target, extra) 同一時間只允許一個爬蟲
    with _lock:
        if any(j['crawler'].status in ('pending', 'running') for j in _jobs.values()):
            return jsonify({'error': '已有爬蟲正在執行 請先停止或等待完成'}), 409
        logs = deque(maxlen=200)

        def Log(msg):
            logs.append(datetime.datetime.now().strftime('%H:%M:%S') + ' ' + msg)

        crawler, target, extra = makeCrawler(Log)
        jobId = uuid.uuid4().hex[:8]
        thread = threading.Thread(target=target, daemon=True)
        _jobs[jobId] = {'crawler': crawler, 'logs': logs, 'thread': thread, **extra}
        thread.start()
    return jsonify({'id': jobId, **{k: v for k, v in extra.items() if k == 'runId'}})


@app.post('/api/jobs')
def StartJob():
    body = request.get_json(force=True)

    def Make(log):
        crawler = Crawler(body.get('filters', {}), maxPage=ClampPage(body.get('maxPage')),
                          fetchDetail=bool(body.get('fetchDetail', True)), log=log,
                          onRow=lambda row, added: storage.RefreshFavorite(row),
                          skipJobNos=storage.HiddenJobNos())
        return crawler, crawler.run, {}
    return StartCrawl(Make)


def GetJob(jobId):
    job = _jobs.get(jobId)
    if job is None:
        abort(404)
    return job


@app.get('/api/jobs/<jobId>')
def JobStatus(jobId):
    job = GetJob(jobId)
    batch = job.get('batch')
    # 全部執行: 進度與結果取自目前執行中的追蹤 狀態取自整批
    watchRun = batch.current if batch else job.get('watchRun')
    crawler = watchRun.crawler if batch and watchRun else (None if batch else job['crawler'])
    since = int(request.args.get('since', 0))
    # 全部執行換到下一個追蹤時 前端還拿著上一個追蹤的筆數 從頭回傳
    runParam = request.args.get('run', '')
    if runParam and watchRun and runParam != str(watchRun.runId):
        since = 0
    status = batch.status if batch else crawler.status
    result = {
        'status': status,
        'message': crawler.message if crawler else '',
        'keywords': crawler.keywords if crawler else [''],
        'keywordIndex': crawler.keywordIndex if crawler else 0,
        'keyword': crawler.keyword if crawler else '',
        'page': crawler.page if crawler else 0,
        'maxPage': crawler.maxPage if crawler else 1,
        'lastPage': crawler.lastPage if crawler else None,
        'total': crawler.total if crawler else None,
        'count': len(crawler.rows) if crawler else 0,
        'skipped': crawler.skipped if crawler else 0,
        'logs': list(job['logs'])[-30:],
        'rows': crawler.rows[since:] if crawler else [],
        'runId': watchRun.runId if watchRun else None,
        'watchId': watchRun.watch['id'] if watchRun else None,
        'newCount': watchRun.newCount if watchRun else None,
    }
    if batch:
        newTotal = sum(r['newCount'] for r in batch.results)
        result['batch'] = {'index': batch.index, 'total': len(batch.results), 'results': batch.results,
                           'name': watchRun.watch['name'] if watchRun else ''}
        if status not in ('pending', 'running'):
            result['message'] = str(len(batch.results)) + ' 個追蹤，共新增 ' + str(newTotal) + ' 筆'
    return jsonify(result)


@app.post('/api/jobs/<jobId>/stop')
def StopJob(jobId):
    GetJob(jobId)['crawler'].stop()
    return jsonify({'ok': True})


@app.get('/api/jobs/<jobId>/csv')
def DownloadCsv(jobId):
    crawler = GetJob(jobId)['crawler']
    return SendCsv(crawler.to_dataframe(rows=WithoutHidden(crawler.rows)), CsvFileName(crawler.keywords))


def WithoutHidden(rows):
    # 爬完之後才隱藏的職缺 下載時也排除
    hidden = storage.HiddenJobNos()
    return [r for r in rows if r.get('jobNo') not in hidden]


def SendCsv(dataFrame, fileName):
    buffer = io.BytesIO()
    dataFrame.to_csv(buffer, encoding='utf-8-sig', index=False)
    buffer.seek(0)
    return send_file(buffer, mimetype='text/csv', as_attachment=True, download_name=fileName)


# ---------- 追蹤 ----------
def WatchFromBody():
    body = request.get_json(force=True)
    name = (body.get('name') or '').strip()
    return name, body.get('filters', {}), ClampPage(body.get('maxPage')), bool(body.get('fetchDetail', True))


def GetWatchOr404(watchId):
    watch = storage.GetWatch(watchId)
    if watch is None:
        abort(404)
    return watch


@app.get('/api/watches')
def ListWatches():
    return jsonify(storage.ListWatches())


@app.post('/api/watches')
def CreateWatch():
    name, filters, maxPage, fetchDetail = WatchFromBody()
    if not name:
        return jsonify({'error': '請輸入追蹤名稱'}), 400
    try:
        watchId = storage.CreateWatch(name, filters, maxPage, fetchDetail)
    except DuplicateName as e:
        return jsonify({'error': str(e)}), 409
    return jsonify(storage.GetWatch(watchId))


@app.put('/api/watches/<int:watchId>')
def UpdateWatch(watchId):
    GetWatchOr404(watchId)
    name, filters, maxPage, fetchDetail = WatchFromBody()
    if not name:
        return jsonify({'error': '請輸入追蹤名稱'}), 400
    try:
        storage.UpdateWatch(watchId, name, filters, maxPage, fetchDetail)
    except DuplicateName as e:
        return jsonify({'error': str(e)}), 409
    return jsonify(storage.GetWatch(watchId))


@app.delete('/api/watches/<int:watchId>')
def DeleteWatch(watchId):
    GetWatchOr404(watchId)
    def RunningWatchId(j):
        run = j['batch'].current if j.get('batch') else j.get('watchRun')
        return run.watch['id'] if run and j['crawler'].status == 'running' else None
    if any(RunningWatchId(j) == watchId for j in _jobs.values()):
        return jsonify({'error': '此追蹤正在執行 請先停止'}), 409
    storage.DeleteWatch(watchId)
    return jsonify({'ok': True})


@app.post('/api/watches/<int:watchId>/run')
def RunWatch(watchId):
    watch = GetWatchOr404(watchId)

    def Make(log):
        watchRun = WatchRun(storage, watch, log=log)
        return watchRun.crawler, watchRun.execute, {'watchRun': watchRun, 'runId': watchRun.runId}
    return StartCrawl(Make)


@app.post('/api/watches/run-all')
def RunAllWatches():
    # 依追蹤清單順序(與畫面相同) 依序執行全部追蹤
    watches = storage.ListWatches()
    if not watches:
        return jsonify({'error': '還沒有任何追蹤'}), 400

    def Make(log):
        batch = BatchRun(storage, watches, log=log)
        return batch, batch.execute, {'batch': batch}
    return StartCrawl(Make)


@app.get('/api/watches/<int:watchId>/runs')
def ListRuns(watchId):
    GetWatchOr404(watchId)
    return jsonify(storage.ListRuns(watchId))


def GetRunOr404(runId):
    run = storage.GetRun(runId)
    if run is None:
        abort(404)
    return run


@app.get('/api/runs/<int:runId>')
def GetRun(runId):
    return jsonify(GetRunOr404(runId))


@app.get('/api/runs/<int:runId>/csv')
def DownloadRunCsv(runId):
    run = GetRunOr404(runId)
    watch = GetWatchOr404(run['watchId'])
    keywords = KeywordsOf(watch['filters'])
    dataFrame = ToDataFrame(WithoutHidden(run['rows']), keywords, watch['maxPage'], extraColumns=['isNew'],
                            searchTime=run['startedAt'])
    return SendCsv(dataFrame, CsvFileName([watch['name']], '追蹤結果'))


# ---------- 隱藏職缺 ----------
@app.get('/api/hidden')
def ListHidden():
    return jsonify(storage.ListHidden())


@app.post('/api/hidden')
def HideJob():
    body = request.get_json(force=True)
    jobNo = str(body.get('jobNo') or '').strip()
    if not jobNo:
        return jsonify({'error': '缺少職缺編號'}), 400
    if jobNo.startswith(storage.EXTERNAL_PREFIX):
        # 隱藏是讓爬蟲略過104職缺 外部職缺請直接取消最愛
        return jsonify({'error': '外部職缺不能隱藏，請直接取消最愛'}), 400
    # 若原本在最愛 回傳被移出的內容 供前端復原
    removed = storage.HideJob(jobNo, body.get('title', ''), body.get('company', ''), body.get('url', ''))
    return jsonify({'ok': True, 'removedFavorite': removed})


@app.delete('/api/hidden/<jobNo>')
def UnhideJob(jobNo):
    storage.UnhideJob(jobNo)
    return jsonify({'ok': True})


# ---------- 最愛職缺 ----------
@app.get('/api/favorites')
def ListFavorites():
    return jsonify(storage.ListFavorites())


@app.post('/api/favorites')
def AddFavorite():
    row = request.get_json(force=True)
    if not str(row.get('jobNo') or '').strip():
        return jsonify({'error': '缺少職缺編號'}), 400
    # 隱藏與最愛互斥 收藏時一併取消隱藏
    storage.UnhideJob(row['jobNo'])
    storage.AddFavorite(row)
    return jsonify({'ok': True})


@app.delete('/api/favorites/<jobNo>')
def RemoveFavorite(jobNo):
    # 回傳被移出的完整內容(含群組與歷程) 供前端復原
    return jsonify({'ok': True, 'removed': storage.RemoveFavorite(jobNo)})


@app.post('/api/favorites/restore')
def RestoreFavorite():
    bundle = request.get_json(force=True)
    if not bundle or not bundle.get('jobNo') or not isinstance(bundle.get('data'), dict):
        return jsonify({'error': '復原資料不完整'}), 400
    storage.RestoreFavorite(bundle)
    return jsonify({'ok': True})


@app.put('/api/favorites/<jobNo>/group')
def SetFavoriteGroup(jobNo):
    groupId = request.get_json(force=True).get('groupId')
    if groupId is not None and not any(g['id'] == groupId for g in storage.ListItems('groups')):
        return jsonify({'error': '找不到這個群組'}), 404
    if not storage.SetFavoriteGroup(jobNo, groupId):
        return jsonify({'error': '這個職缺不在最愛中'}), 404
    return jsonify({'ok': True})


@app.post('/api/favorites/<jobNo>/events')
def AddEvent(jobNo):
    body = request.get_json(force=True)
    date = str(body.get('date') or '')
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        return jsonify({'error': '日期格式錯誤'}), 400
    try:
        eventId = storage.AddEvent(jobNo, body.get('stageId'), date, str(body.get('note') or ''))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, 'id': eventId})


@app.delete('/api/events/<int:eventId>')
def DeleteEvent(eventId):
    storage.DeleteEvent(eventId)
    return jsonify({'ok': True})


def FavoritesCsvRows():
    # 匯出用: 加上群組 目前階段 階段日期 完整歷程
    groups = {g['id']: g['name'] for g in storage.ListItems('groups')}
    rows = list()
    for r in storage.ListFavorites():
        current = r['current']
        history = '；'.join(e['date'][5:].replace('-', '/') + ' ' + e['stageName'] +
                           ('（' + e['note'] + '）' if e['note'] else '') for e in r['events'])
        rows.append({**r, 'group': groups.get(r['groupId'], ''), 'stage': current['stageName'] if current else '未投遞',
                     'stageDate': current['date'] if current else '', 'history': history,
                     'source': '外部' if r.get('source') == 'external' else '104', 'note': r.get('note', '')})
    return rows


@app.get('/api/favorites/csv')
def DownloadFavoritesCsv():
    rows = FavoritesCsvRows()
    keywords = sorted({k for r in rows for k in (r.get('matchedKeywords') or '').split(', ') if k})
    dataFrame = ToDataFrame(rows, keywords, '', extraColumns=['source', 'note', 'group', 'stage', 'stageDate',
                                                               'history', 'favoritedAt'])
    return SendCsv(dataFrame, CsvFileName(['最愛'], '收藏清單'))


# ---------- 外部職缺 ----------
def ExternalFieldsFromBody():
    # 回傳 (fields, error)
    body = request.get_json(force=True) or {}
    fields = {
        'jobDetailUrl': str(body.get('url') or '').strip(),
        'jobTitles': str(body.get('title') or '').strip(),
        'jobCompanyName': str(body.get('company') or '').strip(),
        'jobLocation': str(body.get('location') or '').strip(),
        'jobSalary': str(body.get('salary') or '').strip(),
        'note': str(body.get('note') or '').strip(),
    }
    if not re.match(r'^https?://[^\s/]+\.[^\s]+$', fields['jobDetailUrl'], re.I):
        return fields, '網址格式不正確，請以 http:// 或 https:// 開頭'
    if not fields['jobTitles']:
        return fields, '請輸入職稱'
    if not fields['jobCompanyName']:
        return fields, '請輸入公司'
    for key, limit in (('jobDetailUrl', 1000), ('jobTitles', 200), ('jobCompanyName', 200),
                       ('jobLocation', 100), ('jobSalary', 100), ('note', 500)):
        fields[key] = fields[key][:limit]
    return fields, None


@app.post('/api/favorites/external')
def AddExternalFavorite():
    fields, error = ExternalFieldsFromBody()
    if error:
        return jsonify({'error': error}), 400
    if storage.FindFavoriteByUrl(fields['jobDetailUrl']):
        return jsonify({'error': '這個職缺已經在最愛中'}), 409
    groupId = (request.get_json(force=True) or {}).get('groupId')
    if groupId is not None and not any(g['id'] == groupId for g in storage.ListItems('groups')):
        return jsonify({'error': '找不到這個群組'}), 404
    return jsonify({'ok': True, 'jobNo': storage.AddExternalFavorite(fields, groupId)})


@app.put('/api/favorites/external/<jobNo>')
def UpdateExternalFavorite(jobNo):
    if not any(f['jobNo'] == jobNo and f.get('source') == 'external' for f in storage.ListFavorites()):
        return jsonify({'error': '找不到這個外部職缺'}), 404
    fields, error = ExternalFieldsFromBody()
    if error:
        return jsonify({'error': error}), 400
    if storage.FindFavoriteByUrl(fields['jobDetailUrl'], excludeJobNo=jobNo):
        return jsonify({'error': '這個網址已經是另一個最愛職缺'}), 409
    if not storage.UpdateExternalFavorite(jobNo, fields):
        return jsonify({'error': '找不到這個外部職缺'}), 404
    return jsonify({'ok': True})


# ---------- 自訂清單: 群組 (groups) / 應徵階段 (stages) ----------
def ItemKindOr404(kind):
    if kind not in ('groups', 'stages'):
        abort(404)
    return kind


@app.get('/api/lists/<kind>')
def ListItems(kind):
    return jsonify(storage.ListItems(ItemKindOr404(kind)))


@app.post('/api/lists/<kind>')
def CreateItem(kind):
    name = str(request.get_json(force=True).get('name') or '').strip()
    if not name:
        return jsonify({'error': '請輸入名稱'}), 400
    try:
        itemId = storage.CreateItem(ItemKindOr404(kind), name)
    except DuplicateName as e:
        return jsonify({'error': str(e)}), 409
    return jsonify({'ok': True, 'id': itemId})


@app.put('/api/lists/<kind>/<int:itemId>')
def RenameItem(kind, itemId):
    name = str(request.get_json(force=True).get('name') or '').strip()
    if not name:
        return jsonify({'error': '請輸入名稱'}), 400
    try:
        if not storage.RenameItem(ItemKindOr404(kind), itemId, name):
            abort(404)
    except DuplicateName as e:
        return jsonify({'error': str(e)}), 409
    return jsonify({'ok': True})


@app.delete('/api/lists/<kind>/<int:itemId>')
def DeleteItem(kind, itemId):
    storage.DeleteItem(ItemKindOr404(kind), itemId)
    return jsonify({'ok': True})


@app.post('/api/lists/<kind>/<int:itemId>/move')
def MoveItem(kind, itemId):
    direction = int(request.get_json(force=True).get('direction') or 0)
    storage.MoveItem(ItemKindOr404(kind), itemId, direction)
    return jsonify({'ok': True})


# ---------- 網頁全部關閉時自動結束 ----------
watchdog = None


@app.post('/api/heartbeat')
def Heartbeat():
    clientId = str((request.get_json(silent=True) or {}).get('clientId') or '')
    if watchdog and clientId:
        watchdog.heartbeat(clientId)
    return jsonify({'ok': True})


@app.post('/api/bye')
def Bye():
    # 由navigator.sendBeacon送出 用query string傳clientId
    clientId = request.args.get('client', '')
    if watchdog and clientId:
        watchdog.bye(clientId)
    return ('', 204)


def Shutdown():
    # 爬蟲執行中: 跟按「停止」一樣 等它把目前進度寫進資料庫(最多10秒)再結束
    running = [j for j in _jobs.values() if j['crawler'].status in ('pending', 'running')]
    print('網頁已全部關閉' + ('，停止執行中的爬蟲…' if running else '') + ' 程式結束')
    for job in running:
        job['crawler'].stop('網頁關閉時停止')
    for job in running:
        job['thread'].join(timeout=10)
    os._exit(0)


def PortInUse(port):
    # Windows上第二個程式仍能綁同一個埠且不報錯 請求會被舊程式接走 所以啟動前先檢查
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def Main(argv):
    # 參數: --no-browser 不自動開瀏覽器 / --keep-alive 網頁關閉後不自動結束 / --port N
    global watchdog
    port = int(argv[argv.index('--port') + 1]) if '--port' in argv else PORT
    url = 'http://127.0.0.1:' + str(port)
    # 必須在MarkInterrupted之前檢查 否則會把另一個程式正在跑的追蹤誤標為中斷
    if PortInUse(port):
        print('104爬蟲已經在執行中 (' + url + ')，可能是另一個還開著的視窗。')
        print('請先關閉那個視窗再重新開啟；已為你開啟瀏覽器連到正在執行的那一個。')
        if '--no-browser' not in argv:
            webbrowser.open(url)
        sys.exit(1)
    storage.MarkInterrupted()
    if '--keep-alive' not in argv:
        watchdog = ClientWatchdog(Shutdown).start()
    print('104爬蟲介面已啟動: ' + url)
    print('關閉網頁後此視窗會自動結束' if watchdog else '關閉此視窗即結束程式')
    if '--no-browser' not in argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host='127.0.0.1', port=port, debug=False)


if __name__ == '__main__':
    Main(sys.argv)
