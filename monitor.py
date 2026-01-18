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

PEAK_FILE = "peak_lock.json"   # 持久化峰值/谷值


def load_peak():
    if os.path.exists(PEAK_FILE):
        return json.load(open(PEAK_FILE))
    return {"high": {}, "low": {}}


def save_peak(data):
    with open(PEAK_FILE, "w") as f:
        json.dump(data, f)


def second_key(tag: str) -> str:
    """秒级锁：同一秒内只报一次"""
    return f"{dt.datetime.now():%Y-%m-%d-%H-%M-%S}-{tag}"


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

    peak = load_peak()

    # ===== 新高锁：≥16 同一秒内只报一次 =====
    if spread >= 16:
        key = second_key("high")               # 秒级键
        if key not in peak.get("high", {}):
            peak["high_peak"] = spread
            peak.setdefault("high", {})[key] = True
            save_peak(peak)
            send(f"🔔 PAXG 新高溢价 ≥{spread:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 新低锁：≤10 同一秒内只报一次 =====
    elif spread <= 10:
        key = second_key("low")                # 秒级键
        if key not in peak.get("low", {}):
            peak["low_valley"] = spread
            peak.setdefault("low", {})[key] = True
            save_peak(peak)
            send(f"🔔 PAXG 新低溢价 ≤{spread:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")


if __name__ == "__main__":
    # 仅第一次部署发消息
    if not os.path.exists(PEAK_FILE):
        send("✅ 秒级锁+实时价差监控已启动")
    main()
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
