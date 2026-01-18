#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
CHECK_SEC = int(os.getenv("CHECK_SEC", 30))

bot = Bot(token=BOT_TOKEN)
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

LOCK_FILE = "hour_lock.json"   # 持久化锁


def load_lock():
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE, "r") as f:
            return json.load(f)
    return {"high": {}, "low": {}}   # 结构 {"high": {"2026-01-18-15-30.0": true}}


def save_lock(data):
    with open(LOCK_FILE, "w") as f:
        json.dump(data, f)


def half_hour_key(gear: float) -> str:
    return f"{dt.datetime.now():%Y-%m-%d-%H}-{gear}"


def price(sym: str) -> float:
    data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
    for i in data["listings"]:
        if i["ticker"] == sym:
            return float(i["mark_price"])
    raise RuntimeError(f"{sym} not found")


def send(msg: str):
    bot.send_message(chat_id=CHAT_ID, text=msg)


def main():
    paxg = price("PAXG")
    xaut = price("XAUT")
    spread = paxg - xaut
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")

    lock = load_lock()

    # ===== 0.5 元高档位锁：≥15 每 0.5 一档 =====
    if spread >= 15:
        gear = round(spread * 2) / 2   # 15.0 15.5 16.0 ...
        key = half_hour_key(gear)
        if key not in lock["high"]:
            lock["high"][key] = True
            save_lock(lock)
            send(f"🔔 PAXG 溢价 ≥{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 0.5 元低档位锁：≤10 每 0.5 一档 =====
    elif spread <= 10:
        gear = round(spread * 2) / 2   # 10.0 9.5 9.0 ...
        key = half_hour_key(gear)
        if key not in lock["low"]:
            lock["low"][key] = True
            save_lock(lock)
            send(f"🔔 PAXG 溢价 ≤{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")


if __name__ == "__main__":
    send("✅ 文件持久化+0.5元小时档位锁监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
