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

LOCK_FILE = "step_lock.json"   # 0.5 元阶梯锁


def load_lock():
    if os.path.exists(LOCK_FILE):
        return json.load(open(LOCK_FILE))
    return {"high": {}, "low": {}}


def save_lock(data):
    with open(LOCK_FILE, "w") as f:
        json.dump(data, f)


def second_key(gear: float, tag: str) -> str:
    """秒级锁：同一秒内只报一次"""
    return f"{dt.datetime.now():%Y-%m-%d-%H-%M-%S}-{gear}-{tag}"


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

    # ===== 0.5 元阶梯锁：≥16 每 0.5 一档 + 秒级锁 =====
    if spread >= 16:
        gear = int(spread * 2) / 2        # 16.0 16.5 17.0 ...
        key = second_key(gear, "high")    # 秒级键
        if key not in lock.get("high", {}):
            lock.setdefault("high", {})[key] = True
            save_lock(lock)
            send(f"🔔 PAXG 新高溢价 ≥{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 0.5 元阶梯锁：≤10 每 0.5 一档 + 秒级锁 =====
    elif spread <= 10:
        gear = int(spread * 2) / 2        # 10.0 9.5 9.0 ...
        key = second_key(gear, "low")     # 秒级键
        if key not in lock.get("low", {}):
            lock.setdefault("low", {})[key] = True
            save_lock(lock)
            send(f"🔔 PAXG 新低溢价 ≤{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")


if __name__ == "__main__":
    # 仅第一次部署发消息
    if not os.path.exists(LOCK_FILE):
        send("✅ 0.5元阶梯+秒级锁监控已启动")
    main()
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
