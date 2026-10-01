# 追蹤清單與搜尋紀錄 (SQLite)
# 「新增」= 該追蹤過去所有執行中都沒出現過的jobNo
import os
import sys
import json
import sqlite3
import datetime

SCHEMA = '''
CREATE TABLE IF NOT EXISTS watches (
  id           INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  filters      TEXT NOT NULL,
  max_page     INTEGER NOT NULL,
  fetch_detail INTEGER NOT NULL,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id          INTEGER PRIMARY KEY,
  watch_id    INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  status      TEXT NOT NULL,
  message     TEXT,
  total_count INTEGER NOT NULL DEFAULT 0,
  new_count   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_jobs (
  run_id  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  job_no  TEXT NOT NULL,
  is_new  INTEGER NOT NULL,
  data    TEXT NOT NULL,
  PRIMARY KEY (run_id, job_no)
);
CREATE TABLE IF NOT EXISTS seen_jobs (
  watch_id     INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
  job_no       TEXT NOT NULL,
  first_run_id INTEGER NOT NULL,
  first_seen   TEXT NOT NULL,
  PRIMARY KEY (watch_id, job_no)
);
CREATE INDEX IF NOT EXISTS idx_runs_watch ON runs(watch_id);
CREATE TABLE IF NOT EXISTS favorite_jobs (
  job_no       TEXT PRIMARY KEY,
  data         TEXT NOT NULL,
  favorited_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fav_groups (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_stages (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_events (
  id         INTEGER PRIMARY KEY,
  job_no     TEXT NOT NULL REFERENCES favorite_jobs(job_no) ON DELETE CASCADE,
  stage_id   INTEGER REFERENCES app_stages(id) ON DELETE SET NULL,
  stage_name TEXT NOT NULL,
  event_date TEXT NOT NULL,
  note       TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON app_events(job_no);
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hidden_jobs (
  job_no    TEXT PRIMARY KEY,
  title     TEXT NOT NULL,
  company   TEXT NOT NULL,
  url       TEXT NOT NULL,
  hidden_at TEXT NOT NULL
);
'''


DEFAULT_STAGES = ['已投遞', '面試中', '錄取', '未錄取']
# 自訂清單 (群組/應徵階段) 對應的資料表 與使用到它的欄位
LIST_TABLES = {
    'groups': ('fav_groups', 'favorite_jobs', 'group_id', '群組'),
    'stages': ('app_stages', 'app_events', 'stage_id', '階段'),
}


class DuplicateName(Exception):
    pass


def DefaultPath():
    # 打包成exe時放在exe旁 不放在暫存解壓目錄
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'data', 'history.db')


def Now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


class Storage:
    # 每次操作開新連線 可在爬蟲執行緒與網頁執行緒中共用
    def __init__(self, path=None):
        self.path = path or DefaultPath()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._run(lambda db: db.executescript(SCHEMA))
        self._run(self._migrate)

    @staticmethod
    def _migrate(db):
        # 舊資料庫的favorite_jobs沒有group_id 補上 (現有最愛=未分組)
        columns = {r['name'] for r in db.execute('PRAGMA table_info(favorite_jobs)')}
        if 'group_id' not in columns:
            db.execute('ALTER TABLE favorite_jobs ADD COLUMN group_id INTEGER '
                       'REFERENCES fav_groups(id) ON DELETE SET NULL')
        # 預設應徵階段只在第一次建立 之後使用者刪光也不會再冒出來
        if db.execute("SELECT 1 FROM meta WHERE key = 'stages_seeded'").fetchone() is None:
            for order, name in enumerate(DEFAULT_STAGES):
                db.execute('INSERT OR IGNORE INTO app_stages (name, sort_order) VALUES (?, ?)', (name, order))
            db.execute("INSERT INTO meta (key, value) VALUES ('stages_seeded', '1')")

    def MarkInterrupted(self):
        # 程式啟動時呼叫: 上次程式被關閉時仍在執行的紀錄 標記為中斷
        return self._run(lambda db: db.execute(
            "UPDATE runs SET status = 'error', message = '程式中斷', finished_at = ? WHERE status = 'running'",
            (Now(),)).rowcount)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        return db

    def _run(self, fn):
        # 執行並提交交易後關閉連線
        db = self._connect()
        try:
            with db:
                return fn(db)
        finally:
            db.close()

    # ---------- 追蹤 ----------
    @staticmethod
    def _watchDict(row):
        return {
            'id': row['id'],
            'name': row['name'],
            'filters': json.loads(row['filters']),
            'maxPage': row['max_page'],
            'fetchDetail': bool(row['fetch_detail']),
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at'],
        }

    def CreateWatch(self, name, filters, maxPage, fetchDetail):
        name = name.strip()
        try:
            return self._run(lambda db: db.execute(
                'INSERT INTO watches (name, filters, max_page, fetch_detail, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (name, json.dumps(filters, ensure_ascii=False), maxPage, int(fetchDetail), Now(), Now())).lastrowid)
        except sqlite3.IntegrityError:
            raise DuplicateName('已有名為「' + name + '」的追蹤')

    def UpdateWatch(self, watchId, name, filters, maxPage, fetchDetail):
        name = name.strip()
        try:
            return self._run(lambda db: db.execute(
                'UPDATE watches SET name = ?, filters = ?, max_page = ?, fetch_detail = ?, updated_at = ? '
                'WHERE id = ?',
                (name, json.dumps(filters, ensure_ascii=False), maxPage, int(fetchDetail), Now(), watchId)).rowcount)
        except sqlite3.IntegrityError:
            raise DuplicateName('已有名為「' + name + '」的追蹤')

    def DeleteWatch(self, watchId):
        return self._run(lambda db: db.execute('DELETE FROM watches WHERE id = ?', (watchId,)).rowcount)

    def GetWatch(self, watchId):
        row = self._run(lambda db: db.execute('SELECT * FROM watches WHERE id = ?', (watchId,)).fetchone())
        return self._watchDict(row) if row else None

    def GetWatchByName(self, name):
        row = self._run(lambda db: db.execute('SELECT * FROM watches WHERE name = ?', (name.strip(),)).fetchone())
        return self._watchDict(row) if row else None

    def ListWatches(self):
        # 附上最後一次執行摘要
        def Query(db):
            result = list()
            # 同一秒建立/更新的追蹤 以較新建立的在前 (畫面與「全部執行」使用同一順序)
            for row in db.execute('SELECT * FROM watches ORDER BY updated_at DESC, id DESC'):
                watch = self._watchDict(row)
                last = db.execute('SELECT * FROM runs WHERE watch_id = ? ORDER BY id DESC LIMIT 1',
                                  (row['id'],)).fetchone()
                watch['lastRun'] = self._runDict(last) if last else None
                result.append(watch)
            return result
        return self._run(Query)

    # ---------- 執行紀錄 ----------
    @staticmethod
    def _runDict(row):
        return {
            'id': row['id'],
            'watchId': row['watch_id'],
            'startedAt': row['started_at'],
            'finishedAt': row['finished_at'],
            'status': row['status'],
            'message': row['message'],
            'totalCount': row['total_count'],
            'newCount': row['new_count'],
        }

    def StartRun(self, watchId):
        return self._run(lambda db: db.execute(
            "INSERT INTO runs (watch_id, started_at, status) VALUES (?, ?, 'running')",
            (watchId, Now())).lastrowid)

    def RecordRow(self, runId, watchId, row, added):
        # added=True: 新取得的職缺 判斷是否新增並寫入 added=False: 只更新資料(例如符合關鍵字增加)
        # 回傳該筆是否為新增
        jobNo = row['jobNo']
        data = json.dumps({k: v for k, v in row.items() if k != 'isNew'}, ensure_ascii=False)

        def Write(db):
            if not added:
                db.execute('UPDATE run_jobs SET data = ? WHERE run_id = ? AND job_no = ?', (data, runId, jobNo))
                found = db.execute('SELECT is_new FROM run_jobs WHERE run_id = ? AND job_no = ?',
                                   (runId, jobNo)).fetchone()
                return bool(found and found['is_new'])
            isNew = db.execute('INSERT OR IGNORE INTO seen_jobs (watch_id, job_no, first_run_id, first_seen) '
                               'VALUES (?, ?, ?, ?)', (watchId, jobNo, runId, Now())).rowcount == 1
            db.execute('INSERT OR REPLACE INTO run_jobs (run_id, job_no, is_new, data) VALUES (?, ?, ?, ?)',
                       (runId, jobNo, int(isNew), data))
            return isNew
        return self._run(Write)

    def FinishRun(self, runId, status, message):
        def Write(db):
            counts = db.execute('SELECT COUNT(*) AS total, COALESCE(SUM(is_new), 0) AS new FROM run_jobs '
                                'WHERE run_id = ?', (runId,)).fetchone()
            db.execute('UPDATE runs SET status = ?, message = ?, finished_at = ?, total_count = ?, new_count = ? '
                       'WHERE id = ?', (status, message, Now(), counts['total'], counts['new'], runId))
        self._run(Write)

    def ListRuns(self, watchId):
        rows = self._run(lambda db: db.execute('SELECT * FROM runs WHERE watch_id = ? ORDER BY id DESC',
                                               (watchId,)).fetchall())
        return [self._runDict(r) for r in rows]

    def GetRun(self, runId):
        # 回傳執行紀錄與結果 新增的排最前 每筆含isNew
        def Query(db):
            run = db.execute('SELECT * FROM runs WHERE id = ?', (runId,)).fetchone()
            if run is None:
                return None
            result = self._runDict(run)
            first = db.execute('SELECT MIN(id) AS id FROM runs WHERE watch_id = ?', (run['watch_id'],)).fetchone()
            result['isFirstRun'] = first['id'] == runId
            jobs = list()
            for r in db.execute('SELECT is_new, data FROM run_jobs WHERE run_id = ? ORDER BY is_new DESC, rowid',
                                (runId,)):
                row = json.loads(r['data'])
                row['isNew'] = bool(r['is_new'])
                jobs.append(row)
            result['rows'] = jobs
            return result
        return self._run(Query)

    # ---------- 隱藏職缺 (全域 一般搜尋與所有追蹤都不再顯示) ----------
    def HideJob(self, jobNo, title='', company='', url=''):
        # 隱藏與最愛互斥: 同一交易內加入隱藏並移出最愛 回傳被移出的最愛(供復原) 不在最愛時回傳None
        def Write(db):
            removed = self._removeFavorite(db, str(jobNo))
            db.execute(
                'INSERT OR REPLACE INTO hidden_jobs (job_no, title, company, url, hidden_at) VALUES (?, ?, ?, ?, ?)',
                (str(jobNo), title, company, url, Now()))
            return removed
        return self._run(Write)

    def UnhideJob(self, jobNo):
        return self._run(lambda db: db.execute('DELETE FROM hidden_jobs WHERE job_no = ?', (str(jobNo),)).rowcount)

    def ListHidden(self):
        rows = self._run(lambda db: db.execute('SELECT * FROM hidden_jobs ORDER BY hidden_at DESC').fetchall())
        return [{'jobNo': r['job_no'], 'title': r['title'], 'company': r['company'], 'url': r['url'],
                 'hiddenAt': r['hidden_at']} for r in rows]

    def HiddenJobNos(self):
        return {r['job_no'] for r in self._run(lambda db: db.execute('SELECT job_no FROM hidden_jobs').fetchall())}

    # ---------- 最愛職缺 (全域 保存收藏當下的完整資料) ----------
    # 資料欄位以外的資訊 (群組/歷程等) 不寫進data
    FAVORITE_EXTRA_KEYS = ('isNew', 'favoritedAt', 'groupId', 'events', 'current')

    @classmethod
    def _favoriteData(cls, row):
        return {k: v for k, v in row.items() if k not in cls.FAVORITE_EXTRA_KEYS}

    def AddFavorite(self, row):
        # 已收藏時只更新資料 保留原收藏時間、群組與歷程
        # (不可用INSERT OR REPLACE: REPLACE會先刪除舊列 連帶刪掉應徵歷程)
        jobNo = str(row['jobNo'])
        data = json.dumps(self._favoriteData(row), ensure_ascii=False)

        def Write(db):
            if db.execute('UPDATE favorite_jobs SET data = ? WHERE job_no = ?', (data, jobNo)).rowcount == 0:
                db.execute('INSERT INTO favorite_jobs (job_no, data, favorited_at) VALUES (?, ?, ?)',
                           (jobNo, data, Now()))
        self._run(Write)

    def _removeFavorite(self, db, jobNo):
        # 移出最愛 回傳完整內容(資料/收藏時間/群組/歷程) 供RestoreFavorite復原 不在最愛時回傳None
        found = db.execute('SELECT * FROM favorite_jobs WHERE job_no = ?', (jobNo,)).fetchone()
        if found is None:
            return None
        bundle = {
            'jobNo': jobNo,
            'data': json.loads(found['data']),
            'favoritedAt': found['favorited_at'],
            'groupId': found['group_id'],
            'events': [{'stageId': e['stage_id'], 'stageName': e['stage_name'], 'date': e['event_date'],
                        'note': e['note'], 'createdAt': e['created_at']}
                       for e in db.execute('SELECT * FROM app_events WHERE job_no = ? ORDER BY id', (jobNo,))],
        }
        db.execute('DELETE FROM favorite_jobs WHERE job_no = ?', (jobNo,))  # 歷程由ON DELETE CASCADE一併刪除
        return bundle

    def RemoveFavorite(self, jobNo):
        return self._run(lambda db: self._removeFavorite(db, str(jobNo)))

    def RestoreFavorite(self, bundle):
        # 復原被移出的最愛: 保留原收藏時間 群組/階段若已被刪除則略過(未分組/保留歷程名稱)
        # 隱藏與最愛互斥 復原時一併取消隱藏
        jobNo = str(bundle['jobNo'])

        def Write(db):
            db.execute('DELETE FROM hidden_jobs WHERE job_no = ?', (jobNo,))
            db.execute('DELETE FROM favorite_jobs WHERE job_no = ?', (jobNo,))
            groupId = bundle.get('groupId')
            if groupId is not None and db.execute('SELECT 1 FROM fav_groups WHERE id = ?', (groupId,)).fetchone() is None:
                groupId = None
            db.execute('INSERT INTO favorite_jobs (job_no, data, favorited_at, group_id) VALUES (?, ?, ?, ?)',
                       (jobNo, json.dumps(self._favoriteData(bundle['data']), ensure_ascii=False),
                        bundle.get('favoritedAt') or Now(), groupId))
            for e in bundle.get('events') or []:
                stageId = e.get('stageId')
                if stageId is not None and db.execute('SELECT 1 FROM app_stages WHERE id = ?', (stageId,)).fetchone() is None:
                    stageId = None
                db.execute('INSERT INTO app_events (job_no, stage_id, stage_name, event_date, note, created_at) '
                           'VALUES (?, ?, ?, ?, ?, ?)',
                           (jobNo, stageId, e['stageName'], e['date'], e.get('note') or '', e.get('createdAt') or Now()))
        self._run(Write)

    def ListFavorites(self):
        # 每筆附上 群組 歷程(依日期排序 顯示最新的階段名稱) 與目前階段(最後一筆歷程)
        def Query(db):
            events = dict()
            for e in db.execute('SELECT e.*, s.name AS live_name FROM app_events e '
                                'LEFT JOIN app_stages s ON s.id = e.stage_id ORDER BY e.event_date, e.id'):
                events.setdefault(e['job_no'], []).append({
                    'id': e['id'], 'stageId': e['stage_id'], 'stageName': e['live_name'] or e['stage_name'],
                    'date': e['event_date'], 'note': e['note'],
                })
            result = list()
            for r in db.execute('SELECT * FROM favorite_jobs ORDER BY favorited_at DESC'):
                jobEvents = events.get(r['job_no'], [])
                result.append({**json.loads(r['data']), 'favoritedAt': r['favorited_at'], 'groupId': r['group_id'],
                               'events': jobEvents, 'current': jobEvents[-1] if jobEvents else None})
            return result
        return self._run(Query)

    def RefreshFavorite(self, row):
        # 已收藏的職缺再次被爬到時 以新資料更新存檔
        # 只覆蓋有值的欄位 避免「只抓列表」的結果把先前抓到的詳細資料清空
        jobNo = str(row.get('jobNo', ''))

        def Write(db):
            found = db.execute('SELECT data FROM favorite_jobs WHERE job_no = ?', (jobNo,)).fetchone()
            if found is None:
                return False
            data = json.loads(found['data'])
            data.update({k: v for k, v in self._favoriteData(row).items() if v not in ('', None)})
            db.execute('UPDATE favorite_jobs SET data = ? WHERE job_no = ?',
                       (json.dumps(data, ensure_ascii=False), jobNo))
            return True
        return self._run(Write)

    def SetFavoriteGroup(self, jobNo, groupId):
        return self._run(lambda db: db.execute('UPDATE favorite_jobs SET group_id = ? WHERE job_no = ?',
                                               (groupId, str(jobNo))).rowcount)

    # ---------- 應徵歷程 ----------
    def AddEvent(self, jobNo, stageId, date, note=''):
        # 記下當時的階段名稱 階段被刪除後歷程仍顯示原名
        def Write(db):
            stage = db.execute('SELECT name FROM app_stages WHERE id = ?', (stageId,)).fetchone()
            if stage is None:
                raise ValueError('找不到這個應徵階段')
            if db.execute('SELECT 1 FROM favorite_jobs WHERE job_no = ?', (str(jobNo),)).fetchone() is None:
                raise ValueError('這個職缺不在最愛中')
            return db.execute('INSERT INTO app_events (job_no, stage_id, stage_name, event_date, note, created_at) '
                              'VALUES (?, ?, ?, ?, ?, ?)',
                              (str(jobNo), stageId, stage['name'], date, note.strip(), Now())).lastrowid
        return self._run(Write)

    def DeleteEvent(self, eventId):
        return self._run(lambda db: db.execute('DELETE FROM app_events WHERE id = ?', (eventId,)).rowcount)

    # ---------- 自訂清單 (kind: groups=群組 / stages=應徵階段) ----------
    def ListItems(self, kind):
        # 依順序列出 並附上使用數 (群組=職缺數 階段=歷程筆數)
        table, refTable, refColumn, _ = LIST_TABLES[kind]
        rows = self._run(lambda db: db.execute(
            f'SELECT t.id, t.name, (SELECT COUNT(*) FROM {refTable} r WHERE r.{refColumn} = t.id) AS used '
            f'FROM {table} t ORDER BY t.sort_order, t.id').fetchall())
        return [{'id': r['id'], 'name': r['name'], 'used': r['used']} for r in rows]

    def CreateItem(self, kind, name):
        table, _, _, label = LIST_TABLES[kind]
        name = name.strip()
        try:
            return self._run(lambda db: db.execute(
                f'INSERT INTO {table} (name, sort_order) VALUES (?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {table}))',
                (name,)).lastrowid)
        except sqlite3.IntegrityError:
            raise DuplicateName('已有名為「' + name + '」的' + label)

    def RenameItem(self, kind, itemId, name):
        table, _, _, label = LIST_TABLES[kind]
        name = name.strip()
        try:
            return self._run(lambda db: db.execute(f'UPDATE {table} SET name = ? WHERE id = ?', (name, itemId)).rowcount)
        except sqlite3.IntegrityError:
            raise DuplicateName('已有名為「' + name + '」的' + label)

    def DeleteItem(self, kind, itemId):
        # 群組: 職缺變未分組 / 階段: 歷程保留(顯示原名) 皆由ON DELETE SET NULL處理
        table = LIST_TABLES[kind][0]
        return self._run(lambda db: db.execute(f'DELETE FROM {table} WHERE id = ?', (itemId,)).rowcount)

    def MoveItem(self, kind, itemId, direction):
        # direction: -1=上移 1=下移 與相鄰項目交換順序
        table = LIST_TABLES[kind][0]

        def Write(db):
            items = [r['id'] for r in db.execute(f'SELECT id FROM {table} ORDER BY sort_order, id')]
            if itemId not in items:
                return False
            i = items.index(itemId)
            j = i + (1 if direction > 0 else -1)
            if not 0 <= j < len(items):
                return False
            items[i], items[j] = items[j], items[i]
            for order, rowId in enumerate(items):
                db.execute(f'UPDATE {table} SET sort_order = ? WHERE id = ?', (order, rowId))
            return True
        return self._run(Write)
