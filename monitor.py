#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
CHECK_SEC = int(os.getenv("CHECK_SEC", 10))   # ← 彻底无引号

bot = Bot(token=BOT_TOKEN)
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

LOCK_FILE = "strict_step_lock.json"

def load_lock():
    if os.path.exists(LOCK_FILE):
        return json.load(open(LOCK_FILE))
    return {"high_peak": 16.0, "low_valley": 10.0}

def save_lock(data):
    with open(LOCK_FILE, "w") as f:
        json.dump(data, f)

def hour_key(gear: float) -> str:
    return f"{dt.datetime.now():%Y-%m-%d-%H}-{gear}"

def price(sym: str) -> float:
    data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
    for i in data["listings"]:
        if i["ticker"] == sym:
            return float(i["mark_price"])
    raise RuntimeError(f"{sym} not found")   # ← 已去掉多余 }

def send(msg: str):
    bot.send_message(chat_id=CHAT_ID, text=msg)

def main():
    paxg = price("PAXG")
    xaut = price("XAUT")
    spread = paxg - xaut
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")

    lock = load_lock()

    # ===== 严格大于上一档 +0.5：≥16 =====
    if spread >= 16:
        gear = int(spread * 2) / 2
        key = hour_key(gear)
        if key not in lock.get("high", {}):
            old = lock.get("high_peak", 16.0)
            if spread > old + 0.5:
                lock.setdefault("high", {})[key] = True
                lock["high_peak"] = spread
                save_lock(lock)
                send(f"🔔 PAXG 新高溢价 ≥{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 严格小于上一档 -0.5：≤10 =====
    elif spread <= 10:
        gear = int(spread * 2) / 2
        key = hour_key(gear)
        if key not in lock.get("low", {}):
            old = lock.get("low_valley", 10.0)
            if spread < old - 0.5:
                lock.setdefault("low", {})[key] = True
                lock["low_valley"] = spread
                save_lock(lock)
                send(f"🔔 PAXG 新低溢价 ≤{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

if __name__ == "__main__":
    if not os.path.exists(LOCK_FILE):
        send("✅ 严格阶梯锁监控已启动")
    main()
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
