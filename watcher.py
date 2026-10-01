# 執行追蹤: 串接 Crawler 與 Storage
# 供 app.py (網頁介面) 使用
from crawler import Crawler


class WatchRun:
    # 建立後呼叫 execute() 執行 (可在背景執行緒) crawler 屬性可用於查詢進度與停止
    def __init__(self, storage, watch, log=print):
        self.storage = storage
        self.watch = watch
        self.newCount = 0
        self.runId = storage.StartRun(watch['id'])
        self.crawler = Crawler(watch['filters'], maxPage=watch['maxPage'], fetchDetail=watch['fetchDetail'],
                               log=log, onRow=self._onRow, skipJobNos=storage.HiddenJobNos())

    def _onRow(self, row, added):
        self.storage.RefreshFavorite(row)
        isNew = self.storage.RecordRow(self.runId, self.watch['id'], row, added)
        if added:
            row['isNew'] = isNew
            self.newCount += int(isNew)

    def execute(self):
        try:
            self.crawler.run()
        finally:
            # crawler.run()已攔截爬蟲錯誤 此處確保資料庫錯誤等意外時也會結束紀錄
            status = self.crawler.status if self.crawler.status != 'running' else 'error'
            self.storage.FinishRun(self.runId, status, self.crawler.message)
        return self


class BatchRun:
    # 依序執行多個追蹤 (全部執行)
    # 對外介面與Crawler相同 (status / stop) 停止與關閉網頁時的處理可直接沿用
    # 停止: 目前的追蹤停在當下進度 後面的不再執行 / 單一追蹤出錯: 記錄後繼續下一個
    def __init__(self, storage, watches, log=print):
        self.storage = storage
        self.watchIds = [w['id'] for w in watches]
        self.log = log
        self.index = 0
        self.current = None  # 目前執行中的 WatchRun
        self.results = [{'watchId': w['id'], 'name': w['name'], 'runId': None, 'status': 'pending',
                         'totalCount': 0, 'newCount': 0, 'message': ''} for w in watches]
        self.status = 'pending'  # pending / running / done / stopped
        self._stop = False
        self._stopReason = '手動停止'

    def stop(self, reason='手動停止'):
        self._stopReason = reason
        self._stop = True
        current = self.current
        if current is not None:
            current.crawler.stop(reason)

    def execute(self):
        self.status = 'running'
        total = len(self.watchIds)
        for index, watchId in enumerate(self.watchIds):
            if self._stop:
                break
            self.index = index
            result = self.results[index]
            try:
                # 執行前重新讀取 執行期間被刪除或修改的追蹤以最新狀態為準
                watch = self.storage.GetWatch(watchId)
                if watch is None:
                    result['status'] = 'deleted'
                    continue
                result['name'] = watch['name']
                self.log('全部執行 ' + str(index + 1) + '/' + str(total) + '：' + watch['name'])
                run = WatchRun(self.storage, watch, log=self.log)
                self.current = run
                if self._stop:  # 建立期間剛好按了停止
                    run.crawler.stop(self._stopReason)
                result['runId'] = run.runId
                run.execute()
                saved = self.storage.ListRuns(watchId)[0]
                result.update(status=saved['status'], totalCount=saved['totalCount'],
                              newCount=saved['newCount'], message=saved['message'] or '')
            except Exception as e:
                result.update(status='error', message=str(e))
                self.log('「' + result['name'] + '」發生錯誤: ' + str(e))
        self.status = 'stopped' if self._stop else 'done'
        return self
