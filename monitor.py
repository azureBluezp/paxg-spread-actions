#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CHECK_SEC = int(os.getenv("CHECK_SEC", 30))

bot = Bot(token=BOT_TOKEN)
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

# ===== 全局状态 =====
high_timers = {}          # {gear: start_time}
low_timers = {}
high_peak = 16.0          # 历史最高mark价差
low_valley = 10.0         # 历史最低mark价差
last_high_gear = None     # 上次报警的高档位
last_low_gear = None      # 上次报警的抵挡位


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
    """发送Telegram消息"""
    bot.send_message(chat_id=CHAT_ID, text=msg)


def main():
    global high_timers, low_timers, high_peak, low_valley, last_high_gear, last_low_gear
    
    # 获取数据
    paxg = get_asset_data("PAXG")
    xaut = get_asset_data("XAUT")
    
    # 计算价差
    mark_spread = paxg["mark_price"] - xaut["mark_price"]
    short_spread = paxg["bid_1k"] - xaut["ask_1k"]  # 做空PAXG的真实价差
    long_spread = paxg["ask_1k"] - xaut["bid_1k"]   # 做多PAXG的真实价差
    
    now = time.time()
    current_gear = int(mark_spread * 2) / 2  # 保留一位小数档位
    
    print(f"{dt.datetime.now():%H:%M:%S}  Mark={mark_spread:.2f}  档位={current_gear:.1f}")

    # ===== ≥16 处理（核心：档位递增0.5 + 首次允许 + 持续1秒）=====
    if mark_spread >= 16:
        # 清理不在当前档位的计时器
        to_remove = [g for g in high_timers.keys() if g != current_gear]
        for g in to_remove:
            del high_timers[g]
            print(f"  清除档位 {g:.1f} 计时器")
        
        # 检查是否满足档位间隔（首次或比上次报警高0.5）
        if last_high_gear is None or current_gear >= last_high_gear + 0.5:
            # 为当前档位启动计时器（如果不存在）
            if current_gear not in high_timers:
                high_timers[current_gear] = now
                print(f"  档位 {current_gear:.1f} 开始计时")
            
            # 检查是否持续1秒
            if now - high_timers[current_gear] >= 1.0:
                # 更新峰值和上次报警档位
                high_peak = mark_spread
                last_high_gear = current_gear  # 关键：更新为当前档位
                msg = (f"🔔 PAXG 新高溢价 ≥16！\n"
                       f"档位: {current_gear:.1f}\n"
                       f"真实成交价差: {short_spread:.2f}\n"
                       f"持续1秒: {mark_spread:.2f}")
                send(msg)
                print(f"  ✅ 报警发送: 档位 {current_gear:.1f}")
                # 报警后清除计时器，避免重复
                del high_timers[current_gear]
    
    # ===== ≤10 处理（档位递减0.5）=====
    elif mark_spread <= 10:
        # 清理不在当前档位的计时器
        to_remove = [g for g in low_timers.keys() if g != current_gear]
        for g in to_remove:
            del low_timers[g]
            print(f"  清除档位 {g:.1f} 计时器")
        
        # 检查是否满足档位间隔（首次或比上次报警低0.5）
        if last_low_gear is None or current_gear <= last_low_gear - 0.5:
            # 为当前档位启动计时器（如果不存在）
            if current_gear not in low_timers:
                low_timers[current_gear] = now
                print(f"  档位 {current_gear:.1f} 开始计时")
            
            # 检查是否持续1秒
            if now - low_timers[current_gear] >= 1.0:
                # 更新谷值和上次报警档位
                low_valley = mark_spread
                last_low_gear = current_gear  # 关键：更新为当前档位
                msg = (f"🔔 PAXG 新低溢价 ≤10！\n"
                       f"档位: {current_gear:.1f}\n"
                       f"真实成交价差: {long_spread:.2f}\n"
                       f"持续1秒: {mark_spread:.2f}")
                send(msg)
                print(f"  ✅ 报警发送: 档位 {current_gear:.1f}")
                # 报警后清除计时器，避免重复
                del low_timers[current_gear]
    
    # ===== 阈值外清理 =====
    else:
        if high_timers:
            high_timers.clear()
            print(f"  清除所有 ≥16 计时器")
        if low_timers:
            low_timers.clear()
            print(f"  清除所有 ≤10 计时器")


if __name__ == "__main__":
    send("✅ 1秒持续+档位递增0.5 监控已启动")
    while True:
        try:
            main()
        except Exception as e:
            print("抓取失败:", e)
        time.sleep(CHECK_SEC)
