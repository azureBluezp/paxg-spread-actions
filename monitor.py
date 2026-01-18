#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
import re

def clean_env_value(value: str) -> str:
    """清理环境变量值，移除所有引号和占位符"""
    if value is None:
        return ""
    
    value = str(value).strip()
    
    # 移除所有引号
    while (value.startswith('"') and value.endswith('"')) or \
          (value.startswith("'") and value.endswith("'")):
        value = value[1:-1].strip()
    
    # 移除占位符标记
    if "***" in value:
        # 尝试从占位符中提取实际值
        match = re.search(r'(\d+)', value)
        if match:
            return match.group(1)
        return ""
    
    return value

def get_env(key: str, default: str = "") -> str:
    """获取环境变量"""
    value = os.getenv(key)
    if value is None:
        return default
    return clean_env_value(value)

def get_env_int(key: str, default: int) -> int:
    """安全获取整数环境变量"""
    value = get_env(key, "")
    if not value:
        return default
    
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

# 获取环境变量
BOT_TOKEN = get_env("BOT_TOKEN")
CHAT_ID = get_env("CHAT_ID")
CHECK_SEC = get_env_int("CHECK_SEC", 30)  # 默认30秒

print(f"=== 环境变量检查 ===")
print(f"BOT_TOKEN 长度: {len(BOT_TOKEN)}")
print(f"CHAT_ID: {CHAT_ID}")
print(f"CHECK_SEC: {CHECK_SEC}")

# 检查必要的环境变量
if not BOT_TOKEN:
    print("错误: BOT_TOKEN 环境变量未设置")
    print("请在 GitHub Secrets 中设置正确的 BOT_TOKEN")
    exit(1)

if not CHAT_ID:
    print("错误: CHAT_ID 环境变量未设置")
    print("请在 GitHub Secrets 中设置正确的 CHAT_ID")
    exit(1)

# 初始化 Bot
try:
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    # 测试 Bot 是否有效
    bot_info = bot.get_me()
    print(f"✓ Telegram Bot 连接成功: @{bot_info.username}")
except Exception as e:
    print(f"错误: Telegram Bot 初始化失败: {e}")
    print("可能的原因:")
    print("1. BOT_TOKEN 格式不正确（正确格式: 1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ）")
    print("2. BOT_TOKEN 已失效")
    print("3. 网络连接问题")
    exit(1)

BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

LOCK_FILE = "strict_step_lock.json"

def load_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"警告: {LOCK_FILE} 文件损坏，使用默认值")
    
    # 默认值，确保包含所有必要的键
    return {
        "high_peak": 16.0, 
        "low_valley": 10.0,
        "high": {},
        "low": {}
    }

def save_lock(data):
    with open(LOCK_FILE, "w") as f:
        json.dump(data, f)

def hour_key(gear: float) -> str:
    return f"{dt.datetime.now():%Y-%m-%d-%H}-{gear:.1f}"

def price(sym: str) -> float:
    try:
        data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
        for i in data.get("listings", []):
            if i.get("ticker") == sym:
                return float(i.get("mark_price", 0))
        raise RuntimeError(f"{sym} not found")
    except Exception as e:
        print(f"获取价格失败: {e}")
        raise

def send(msg: str):
    try:
        bot.send_message(chat_id=CHAT_ID, text=msg)
        print(f"✓ 消息已发送: {msg[:50]}...")
    except Exception as e:
        print(f"发送消息失败: {e}")

def main():
    paxg = price("PAXG")
    xaut = price("XAUT")
    spread = paxg - xaut
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")

    lock = load_lock()

    # ===== 严格大于上一档 +0.5：≥16 =====
    if spread >= 16:
        gear = int(spread * 2) / 2
        key = hour_key(gear)
        
        # 确保 high 字典存在
        if "high" not in lock:
            lock["high"] = {}
            
        if key not in lock["high"]:
            old = lock.get("high_peak", 16.0)
            if spread > old + 0.5:
                lock["high"][key] = True
                lock["high_peak"] = spread
                save_lock(lock)
                send(f"🔔 PAXG 新高溢价 ≥{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

    # ===== 严格小于上一档 -0.5：≤10 =====
    elif spread <= 10:
        gear = int(spread * 2) / 2
        key = hour_key(gear)
        
        # 确保 low 字典存在
        if "low" not in lock:
            lock["low"] = {}
            
        if key not in lock["low"]:
            old = lock.get("low_valley", 10.0)
            if spread < old - 0.5:
                lock["low"][key] = True
                lock["low_valley"] = spread
                save_lock(lock)
                send(f"🔔 PAXG 新低溢价 ≤{gear:.1f}！\nPAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}")

if __name__ == "__main__":
    print(f"\n=== PAXG 监控程序启动 ===")
    print(f"检查间隔: {CHECK_SEC}秒")
    print(f"启动时间: {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"工作目录: {os.getcwd()}")
    
    # 首次运行发送启动消息
    if not os.path.exists(LOCK_FILE):
        print("首次运行，发送启动消息...")
        send("✅ 严格阶梯锁监控已启动")
    else:
        print("检测到已有的锁定文件，不发送启动消息")
    
    print("开始监控...")
    print("-" * 50)
    
    # 运行主循环
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("监控已停止")
            break
        except Exception as e:
            print(f"抓取失败: {e}")
        time.sleep(CHECK_SEC)
