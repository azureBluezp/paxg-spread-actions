#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import telegram

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
CHECK_SEC = int(os.getenv("CHECK_SEC", 30))

bot = telegram.Bot(token=BOT_TOKEN)
last_alert = None
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

def price(sym: str) -> float:
    data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
    for i in data["listings"]:
        if i["ticker"] == sym:
            return float(i["mark_price"])
    raise RuntimeError(f"{sym} not found")

def send(msg: str):
    bot.send_message(chat_id=CHAT_ID, text=msg)

def main():
    global last_alert
    paxg = price("PAXG")
    xaut = price("XAUT")
    spread = paxg - xaut
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")
    if spread >= 15 and last_alert != "high":
        send(f"🔔 PAXG 溢价 ≥15！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")
        last_alert = "high"
    elif spread <= 10 and last_alert != "low":
        send(f"🔔 PAXG 溢价 ≤10！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")
        last_alert = "low"
    elif 10 < spread < 15:
        last_alert = None

if __name__ == "__main__":
    send("✅ GitHub Actions 监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
