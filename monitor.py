#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
from telegram import Bot

# ========== 环境变量 ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
CHECK_SEC = int(os.getenv("CHECK_SEC", 30))

bot = Bot(token=BOT_TOKEN)
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

# ========== 内存锁（全局变量，仅当前runner有效）======
high_peak = 16.0     # 历史最高mark价差（初始化）
low_valley = 10.0    # 历史最低mark价差（初始化）


def get_asset_data(sym: str) -> dict:
    """获取资产数据：mark_price + bid/ask"""
    data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
    for item in data["listings"]:
        if item["ticker"] == sym:
            return {
                "mark_price": float(item["mark_price"]),
                "bid_1k": float(item["quotes"]["size_1k"]["bid"]),   # 可卖出价
                "ask_1k": float(item["quotes"]["size_1k"]["ask"])    # 可买入价
            }
    raise RuntimeError(f"{sym} 未找到")


def send(msg: str):
    """发送Telegram消息"""
    bot.send_message(chat_id=CHAT_ID, text=msg)


def main():
    global high_peak, low_valley
    
    # ===== 获取数据 =====
    paxg = get_asset_data("PAXG")
    xaut = get_asset_data("XAUT")
    
    # ===== 计算三种价差 =====
    mark_spread = paxg["mark_price"] - xaut["mark_price"]          # 报警用（Mark）
    short_spread = paxg["bid_1k"] - xaut["ask_1k"]                # 做空PAXG的真实价差
    long_spread = paxg["ask_1k"] - xaut["bid_1k"]                 # 做多PAXG的真实价差
    
    # ===== 控制台日志 =====
    print(f"{dt.datetime.now():%H:%M:%S}  "
          f"Mark={mark_spread:.2f}  "
          f"做空={short_spread:.2f}  "
          f"做多={long_spread:.2f}")

    # ===== 新高报警：≥16，只显示做空价差 =====
    if mark_spread >= 16 and mark_spread > high_peak + 0.5:
        high_peak = mark_spread   # 更新峰值
        msg = (f"🔔 PAXG 新高溢价 ≥16！\n"
               f"真实成交价差: {short_spread:.2f}\n"
               f"（做空PAXG@市价，做多XAUT@市价）\n"
               f"Mark参考: {mark_spread:.2f}")
        send(msg)

    # ===== 新低报警：≤10，只显示做多价差 =====
    elif mark_spread <= 10 and mark_spread < low_valley - 0.5:
        low_valley = mark_spread   # 更新谷值
        msg = (f"🔔 PAXG 新低溢价 ≤10！\n"
               f"真实成交价差: {long_spread:.2f}\n"
               f"（做多PAXG@市价，做空XAUT@市价）\n"
               f"Mark参考: {mark_spread:.2f}")
        send(msg)


if __name__ == "__main__":
    # ===== 启动提示 =====
    send("✅ Mark+Bid/Ask 监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
