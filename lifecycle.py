# 網頁全部關閉時自動結束程式
# 網頁開啟時定時回報(heartbeat) 關閉時送出bye 全部網頁都送出bye後呼叫onIdle
#
# 只依bye判斷關閉 不用「多久沒回報」判斷:
#   Edge/Chrome 會讓閒置的背景分頁休眠 休眠期間完全不回報
#   若以逾時判斷 會在網頁其實還開著時把程式關掉 (爬蟲執行中也會被中斷)
#   代價: 瀏覽器當掉而沒送出bye時 程式不會自動結束 需手動關閉視窗
import time
import threading


class ClientWatchdog:
    # byeGrace: 收到bye後等待秒數 (按F5重新整理時 新頁面會在這段時間內回報)
    def __init__(self, onIdle, byeGrace=5, tick=1, clock=time.time):
        self.onIdle = onIdle
        self.byeGrace = byeGrace
        self.tick = tick
        self.clock = clock
        self.clients = set()       # 目前開著的網頁
        self.byeDeadline = None
        self.fired = False
        self._lock = threading.Lock()

    def heartbeat(self, clientId):
        with self._lock:
            self.clients.add(clientId)
            self.byeDeadline = None

    def bye(self, clientId):
        with self._lock:
            self.clients.discard(clientId)
            if not self.clients:
                self.byeDeadline = self.clock() + self.byeGrace

    def check(self):
        # 回傳True表示所有網頁都已關閉
        with self._lock:
            return (not self.clients and self.byeDeadline is not None
                    and self.clock() >= self.byeDeadline)

    def _loop(self):
        while not self.fired:
            time.sleep(self.tick)
            if self.check():
                self.fired = True
                self.onIdle()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self
