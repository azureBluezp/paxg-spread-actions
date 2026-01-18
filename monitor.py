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

# ---------- 档位锁 ----------
high_locked: set[int] = set()   # ≥15 每 1 元一档
low_locked:  set[int] = set()   # ≤10 每 1 元一档


def price(sym: str) -> float:
    data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
    for i in data["listings"]:
        if i["ticker"] == sym:
            return float(i["mark_price"])
    raise RuntimeError(f"{sym} not found")


def send(msg: str):
    # 自动追加策略提示
    strategy = ""
    if "溢价 ≥" in msg:
        strategy = "\n策略：做空 PAXG，做多 XAUT"
    elif "溢价 ≤" in msg:
        strategy = "\n策略：做多 PAXG，做空 XAUT"
    bot.send_message(chat_id=CHAT_ID, text=msg + strategy)


def main():
    paxg = price("PAXG")
    xaut = price("XAUT")
    spread = paxg - xaut
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")

    # ===== 高档位锁：≥15 每 1 元一档 =====
    if spread >= 15:
        gear = int(spread)          # 15 16 17 ...
        if gear not in high_locked:
            high_locked.add(gear)
            send(f"🔔 PAXG 溢价 ≥{gear}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 低档位锁：≤10 每 1 元一档 =====
    elif spread <= 10:
        gear = int(spread)          # 10 9 8 ...
        if gear not in low_locked:
            low_locked.add(gear)
            send(f"🔔 PAXG 溢价 ≤{gear}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")


if __name__ == "__main__":
    send("✅ 档位锁+策略提示监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
