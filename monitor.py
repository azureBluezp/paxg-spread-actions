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
    return {"high_peak": None, "low_valley": None}


def save_peak(data):
    with open(PEAK_FILE, "w") as f:
        json.dump(data, f)


def hour_key() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d-%H")


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
    hour = hour_key()

    # ===== 峰值锁：≥16 仅当 > 历史峰值 =====
    if spread >= 16:
        old_peak = peak.get("high_peak")
        if old_peak is None or spread > old_peak:
            peak["high_peak"] = spread
            save_peak(peak)
            send(f"🔔 PAXG 新高溢价 ≥16！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 谷值锁：≤10 仅当 < 历史谷值 =====
    elif spread <= 10:
        old_valley = peak.get("low_valley")
        if old_valley is None or spread < old_valley:
            peak["low_valley"] = spread
            save_peak(peak)
            send(f"🔔 PAXG 新低溢价 ≤10！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")


if __name__ == "__main__":
    # 仅第一次部署发消息
    if not os.path.exists(PEAK_FILE):
        send("✅ 峰值锁监控已启动")
    main()
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
