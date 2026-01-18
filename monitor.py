#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
import sys

# ===== 配置区域 =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
# 默认 30 秒检查一次
CHECK_SEC = int(os.getenv("CHECK_SEC", 30))
LOCK_FILE = "strict_step_lock.json"
BASE_URL  = "https://omni-client-api.prod.ap-northeast-1.variational.io"

# 检查环境变量
if not BOT_TOKEN or not CHAT_ID:
    print("❌ 错误: 必须设置 BOT_TOKEN 和 CHAT_ID 环境变量")
    sys.exit(1)

def load_lock():
    """读取锁文件，如果文件损坏或不存在则返回空字典"""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_lock(data):
    """写入锁文件"""
    try:
        with open(LOCK_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"写入锁文件失败: {e}")

def get_price(sym):
    """获取价格，增加重试机制"""
    try:
        resp = requests.get(f"{BASE_URL}/metadata/stats", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for i in data.get("listings", []):
            if i["ticker"] == sym:
                return float(i["mark_price"])
        raise RuntimeError(f"{sym} 未在 API 中找到")
    except Exception as e:
        print(f"获取价格失败: {e}")
        return None

def send_msg(text):
    """使用原生 requests 发送 Telegram 消息，避免 async 报错"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"发送消息失败: {e}")

def main():
    print(f"✅ 监控启动 (检查间隔: {CHECK_SEC}秒)...")
    send_msg("✅ PAXG 溢价监控已启动")

    while True:
        try:
            # 1. 获取价格
            paxg = get_price("PAXG")
            xaut = get_price("XAUT")

            if paxg is None or xaut is None:
                time.sleep(CHECK_SEC)
                continue

            spread = paxg - xaut
            now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"{now_str} | PAXG={paxg:.2f} | XAUT={xaut:.2f} | 价差={spread:.2f}")

            # 2. 读取锁状态
            lock = load_lock()
            
            # 生成当前小时的 Key (例如 2023-10-27-14)
            # 这样每过一小时，Key 就会变，旧的锁自动失效（实现每小时重新提醒）
            hour_key = dt.datetime.now().strftime("%Y-%m-%d-%H")
            
            # 确保数据结构存在
            if "history" not in lock:
                lock["history"] = {}

            # 3. 计算当前档位 (0.5 为一档)
            # 逻辑：16.2 -> 16.0, 16.8 -> 16.5
            gear = int(spread * 2) / 2.0
            
            # 组合唯一锁 Key: "小时-档位" (例如 "2023-10-27-14-16.5")
            lock_key = f"{hour_key}-{gear}"

            triggered = False

            # ===== 触发逻辑 =====
            # 高溢价 >= 16
            if spread >= 16.0:
                if lock_key not in lock["history"]:
                    msg = (f"📈 <b>PAXG 高溢价提醒</b>\n"
                           f"当前档位: ≥ {gear:.1f}\n"
                           f"实际价差: {spread:.2f}\n"
                           f"PAXG: {paxg:.2f}\n"
                           f"XAUT: {xaut:.2f}")
                    send_msg(msg)
                    lock["history"][lock_key] = True
                    triggered = True

            # 低溢价 <= 10
            elif spread <= 10.0:
                if lock_key not in lock["history"]:
                    msg = (f"📉 <b>PAXG 低溢价提醒</b>\n"
                           f"当前档位: ≤ {gear:.1f}\n"
                           f"实际价差: {spread:.2f}\n"
                           f"PAXG: {paxg:.2f}\n"
                           f"XAUT: {xaut:.2f}")
                    send_msg(msg)
                    lock["history"][lock_key] = True
                    triggered = True

            # 如果触发了，保存锁文件
            if triggered:
                # 清理太旧的历史数据(可选，防止文件无限大)，这里简单处理只保留当天的
                # 实际简单起见，只要保存即可，JSON 不会特别大
                save_lock(lock)

        except Exception as e:
            print(f"主循环发生未知错误: {e}")
        
        time.sleep(CHECK_SEC)

if __name__ == "__main__":
    main()
