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

# ---------- 0.5 元小时档位锁 ----------
high_locked: set[str] = set()   # 格式 "YYYY-MM-DD-HH-档位"
low_locked:  set[str] = set()


def half_hour_key(gear: float) -> str:
    """生成 小时-0.5档位 键"""
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

    # ===== 0.5 元高档位锁：≥15 每 0.5 一档 =====
    if spread >= 15:
        gear = round(spread * 2) / 2   # 15.0 15.5 16.0 16.5 ...
        key = half_hour_key(gear)
        if key not in high_locked:
            high_locked.add(key)
            send(f"🔔 PAXG 溢价 ≥{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 0.5 元低档位锁：≤10 每 0.5 一档 =====
    elif spread <= 10:
        gear = round(spread * 2) / 2   # 10.0 9.5 9.0 8.5 ...
        key = half_hour_key(gear)
        if key not in low_locked:
            low_locked.add(key)
            send(f"🔔 PAXG 溢价 ≤{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")


if __name__ == "__main__":
    send("✅ 0.5元小时档位锁监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
