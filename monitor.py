#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
CHECK_SEC = int(os.getenv("CHECK_SEC", 30))

bot = Bot(token=BOT_TOKEN)
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

# ===== 内存锁（仅当前 runner 有效）=====
high_peak = 16.0
low_valley = 10.0
last_high_key = ""
last_low_key = ""

def price(sym: str) -> float:
    data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
    for i in data["listings"]:
        if i["ticker"] == sym:
            return float(i["mark_price"])
    raise RuntimeError(f"{sym} not found")

def send(msg: str):
    bot.send_message(chat_id=CHAT_ID, text=msg)

def main():
    global high_peak, low_valley, last_high_key, last_low_key
    
    paxg = price("PAXG")
    xaut = price("XAUT")
    spread = paxg - xaut
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")

    # ===== 新高：> 上一档 +0.5 =====
    if spread >= 16 and spread > high_peak + 0.5:
        high_peak = spread
        send(f"🔔 PAXG 新高溢价！\n价差={spread:.2f} (前高+{spread-high_peak:.2f})")

    # ===== 新低：< 上一档 -0.5 =====
    elif spread <= 10 and spread < low_valley - 0.5:
        low_valley = spread
        send(f"🔔 PAXG 新低溢价！\n价差={spread:.2f} (前低-{low_valley-spread:.2f})")

if __name__ == "__main__":
    send("✅ 监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
