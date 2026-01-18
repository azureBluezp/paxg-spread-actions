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

# ---------- 小时档位锁 ----------
high_locked: set[str] = set()   # 格式 "YYYY-MM-DD-HH-档位"
low_locked:  set[str] = set()


def hour_key(gear: int) -> str:
    """生成 小时-档位 键"""
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

    # ===== 高档位锁：≥15 每 1 元一档 =====
    if spread >= 15:
        gear = int(spread)
        key = hour_key(gear)
        if key not in high_locked:
            high_locked.add(key)
            send(f"🔔 PAXG 溢价 ≥{gear}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 低档位锁：≤10 每 1 元一档 =====
    elif spread <= 10:
        gear = int(spread)
        key = hour_key(gear)
        if key not in low_locked:
            low_locked.add(key)
            send(f"🔔 PAXG 溢价 ≤{gear}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")


if __name__ == "__main__":
    send("✅ 小时档位锁监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
