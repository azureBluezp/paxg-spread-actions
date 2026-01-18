#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
CHECK_SEC = int(os.getenv("CHECK_SEC", 30))   # ← 彻底无引号

bot = Bot(token=BOT_TOKEN)
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

LOCK_FILE = "strict_step_lock.json"

def load_lock():
    if os.path.exists(LOCK_FILE):
        return json.load(open(LOCK_FILE))
    return {"high_peak": 16.0, "low_valley": 10.0"}

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
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  P
