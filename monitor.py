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

# ===== 全局状态：持续计时器 =====
high_state = {"pending": False, "since": 0.0, "last_value": 0.0}   # ≥16计时器
low_state  = {"pending": False, "since": 0.0, "last_value": 0.0}   # ≤10计时器
high_peak = 16.0
low_valley = 10.0


def get_asset_data(sym: str) -> dict:
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
    global high_state, low_state, high_peak, low_valley
    
    paxg = get_asset_data("PAXG")
    xaut = get_asset_data("XAUT")
    
    mark_spread = paxg["mark_price"] - xaut["mark_price"]
    short_spread = paxg["bid_1k"] - xaut["ask_1k"]   # 做空PAXG
    long_spread = paxg["ask_1k"] - xaut["bid_1k"]    # 做多PAXG
    
    now = time.time()
    print(f"{dt.datetime.now():%H:%M:%S}  Mark={mark_spread:.2f}")

    # ===== ≥16 持续1秒确认 =====
    if mark_spread >= 16:
        # 情况1：首次突破或从阈值内重新突破
        if not high_state["pending"] or high_state["last_value"] < 16:
            high_state["pending"] = True
            high_state["since"] = now
            high_state["last_value"] = mark_spread
            print(f"  → 开始计时 ≥16 (初始值: {mark_spread:.2f})")
        
        # 情况2：仍在阈值外，但价差变化了（重置计时器）
        elif abs(mark_spread - high_state["last_value"]) > 0.1:
            high_state["since"] = now
            high_state["last_value"] = mark_spread
            print(f"  → 价差变化，重置计时器 (新值: {mark_spread:.2f})")
        
        # 情况3：持续≥16且时间≥1秒，且是新高
        elif now - high_state["since"] >= 1.0 and mark_spread > high_peak + 0.5:
            high_peak = mark_spread
            high_state["pending"] = False   # 报警后重置
            msg = (f"🔔 PAXG 新高溢价 ≥16！\n"
                   f"真实成交价差: {short_spread:.2f}\n"
                   f"持续1秒确认: {mark_spread:.2f}\n"
                   f"（做空PAXG@市价，做多XAUT@市价）")
            send(msg)
            print(f"  ✅ 报警发送: {mark_spread:.2f}")

    else:
        # 情况4：回到阈值内，清除计时器
        if high_state["pending"]:
            high_state["pending"] = False
            print(f"  → 回到阈值内，清除计时器")

    # ===== ≤10 持续1秒确认 =====
    if mark_spread <= 10:
        if not low_state["pending"] or low_state["last_value"] > 10:
            low_state["pending"] = True
            low_state["since"] = now
            low_state["last_value"] = mark_spread
            print(f"  → 开始计时 ≤10 (初始值: {mark_spread:.2f})")
        
        elif abs(mark_spread - low_state["last_value"]) > 0.1:
            low_state["since"] = now
            low_state["last_value"] = mark_spread
            print(f"  → 价差变化，重置计时器 (新值: {mark_spread:.2f})")
        
        elif now - low_state["since"] >= 1.0 and mark_spread < low_valley - 0.5:
            low_valley = mark_spread
            low_state["pending"] = False
            msg = (f"🔔 PAXG 新低溢价 ≤10！\n"
                   f"真实成交价差: {long_spread:.2f}\n"
                   f"持续1秒确认: {mark_spread:.2f}\n"
                   f"（做多PAXG@市价，做空XAUT@市价）")
            send(msg)
            print(f"  ✅ 报警发送: {mark_spread:.2f}")

    else:
        if low_state["pending"]:
            low_state["pending"] = False
            print(f"  → 回到阈值内，清除计时器")


if __name__ == "__main__":
    send("✅ 1秒持续确认监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
