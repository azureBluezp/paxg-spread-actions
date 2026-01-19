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

# ===== 内存锁（全局变量，仅当前runner有效）=====
high_peak = 16.0     # 历史最高mark价差
low_valley = 10.0    # 历史最低mark价差


def get_asset_data(sym: str) -> dict:
    """获取资产数据：mark_price + bid/ask"""
    data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
    for item in data["listings"]:
        if item["ticker"] == sym:
            return {
                "mark_price": float(item["mark_price"]),
                "bid_1k": float(item["quotes"]["size_1k"]["bid"]),
                "ask_1k": float(item["quotes"]["size_1k"]["ask"])
            }
    raise RuntimeError(f"{sym} 未找到")


def send(msg: str):
    bot.send_message(chat_id=CHAT_ID, text=msg)


def main():
    global high_peak, low_valley
    
    # 获取两种价格
    paxg = get_asset_data("PAXG")
    xaut = get_asset_data("XAUT")
    
    # 报警价差（Mark Price，实时无延迟）
    mark_spread = paxg["mark_price"] - xaut["mark_price"]
    
    # 真实套利价差（Bid/Ask，可立即成交）
    # 做空PAXG做多XAUT：卖PAXG@bid，买XAUT@ask
    short_spread = paxg["bid_1k"] - xaut["ask_1k"]
    # 做多PAXG做空XAUT：买PAXG@ask，卖XAUT@bid
    long_spread = paxg["ask_1k"] - xaut["bid_1k"]
    
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  "
          f"PAXG_mark={paxg['mark_price']:.2f}  "
          f"XAUT_mark={xaut['mark_price']:.2f}  "
          f"mark_spread={mark_spread:.2f}  "
          f"short_spread={short_spread:.2f}  "
          f"long_spread={long_spread:.2f}")

    # ===== 新高锁：> 上一档 +0.5（mark价差）=====
    if mark_spread >= 16 and mark_spread > high_peak + 0.5:
        high_peak = mark_spread
        msg = (f"🔔 PAXG 新高溢价！\n"
               f"Mark价差: {mark_spread:.2f}\n"
               f"做空PAXG价差: {short_spread:.2f}\n"
               f"做多PAXG价差: {long_spread:.2f}\n"
               f"PAXG={paxg['mark_price']:.2f}  XAUT={xaut['mark_price']:.2f}")
        send(msg)

    # ===== 新低锁：< 上一档 -0.5（mark价差）=====
    elif mark_spread <= 10 and mark_spread < low_valley - 0.5:
        low_valley = mark_spread
        msg = (f"🔔 PAXG 新低溢价！\n"
               f"Mark价差: {mark_spread:.2f}\n"
               f"做空PAXG价差: {short_spread:.2f}\n"
               f"做多PAXG价差: {long_spread:.2f}\n"
               f"PAXG={paxg['mark_price']:.2f}  XAUT={xaut['mark_price']:.2f}")
        send(msg)

if __name__ == "__main__":
    send("✅ Mark+Bid/Ask 监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
