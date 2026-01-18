#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
from telegram import Bot

# 安全获取环境变量，处理可能的引号和占位符
def get_env(key: str, default: str = None) -> str:
    """获取环境变量，清理引号和特殊字符"""
    value = os.getenv(key)
    if value is None:
        return default
    
    # 清理引号
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    
    # 如果是占位符，返回默认值
    if "***" in value:
        return default
    
    return value

def get_env_int(key: str, default: int) -> int:
    """安全获取整数环境变量"""
    value = get_env(key)
    if value is None:
        return default
    
    try:
        return int(value)
    except (ValueError, TypeError):
        print(f"警告: {key} 值 '{value}' 不是有效整数，使用默认值 {default}")
        return default

# 获取环境变量
BOT_TOKEN = get_env("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN 环境变量未设置")

CHAT_ID = get_env("CHAT_ID")
if not CHAT_ID:
    raise ValueError("CHAT_ID 环境变量未设置")

CHECK_SEC = get_env_int("CHECK_SEC", 30)  # 默认30秒

bot = Bot(token=BOT_TOKEN)
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

LOCK_FILE = "strict_step_lock.json"

def load_lock():
    if os.path.exists(LOCK_FILE):
        try:
            return json.load(open(LOCK_FILE))
        except json.JSONDecodeError:
            print(f"警告: {LOCK_FILE} 文件损坏，使用默认值")
    
    # 默认值
    return {
        "high_peak": 16.0, 
        "low_valley": 10.0,
        "high": {},
        "low": {}
    }

def save_lock(data):
    with open(LOCK_FILE, "w") as f:
        json.dump(data, f, indent=2)

def hour_key(gear: float) -> str:
    # 使用 gear 的两位小数精度作为键
    return f"{dt.datetime.now():%Y-%m-%d-%H}-{gear:.2f}"

def price(sym: str) -> float:
    try:
        data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
        for i in data.get("listings", []):
            if i.get("ticker") == sym:
                return float(i.get("mark_price", 0))
        raise RuntimeError(f"{sym} 未找到")
    except Exception as e:
        print(f"获取价格失败: {e}")
        raise

def send(msg: str):
    try:
        bot.send_message(chat_id=CHAT_ID, text=msg)
        print(f"消息已发送: {msg}")
    except Exception as e:
        print(f"发送消息失败: {e}")

def main():
    try:
        paxg = price("PAXG")
        xaut = price("XAUT")
        spread = paxg - xaut
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")

        lock = load_lock()

        # ===== 严格大于上一档 +0.5：≥16 =====
        if spread >= 16:
            # gear 直接使用 spread 值，不需要取整
            gear = spread
            key = hour_key(gear)
            
            # 检查是否已经发送过这个档位的提醒
            if key not in lock.get("high", {}):
                old = lock.get("high_peak", 16.0)
                # 只有当价差超过之前记录的最高价差0.5才触发
                if spread > old + 0.499:  # 使用0.499避免浮点数精度问题
                    if "high" not in lock:
                        lock["high"] = {}
                    lock["high"][key] = True
                    lock["high_peak"] = spread
                    save_lock(lock)
                    msg = (f"🔔 PAXG 新高溢价！\n"
                           f"PAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}\n"
                           f"比上一高点{old:.2f}高出{spread-old:.2f}")
                    send(msg)

        # ===== 严格小于上一档 -0.5：≤10 =====
        elif spread <= 10:
            # gear 直接使用 spread 值，不需要取整
            gear = spread
            key = hour_key(gear)
            
            # 检查是否已经发送过这个档位的提醒
            if key not in lock.get("low", {}):
                old = lock.get("low_valley", 10.0)
                # 只有当价差低于之前记录的最低价差0.5才触发
                if spread < old - 0.499:  # 使用0.499避免浮点数精度问题
                    if "low" not in lock:
                        lock["low"] = {}
                    lock["low"][key] = True
                    lock["low_valley"] = spread
                    save_lock(lock)
                    msg = (f"🔔 PAXG 新低溢价！\n"
                           f"PAXG={paxg:.2f}  XAUT={xaut:.2f}  价差={spread:.2f}\n"
                           f"比上一低点{old:.2f}低{old-spread:.2f}")
                    send(msg)
    except Exception as e:
        print(f"主函数错误: {e}")

if __name__ == "__main__":
    print(f"=== PAXG 监控程序启动 ===")
    print(f"检查间隔: {CHECK_SEC}秒")
    print(f"锁定文件: {LOCK_FILE}")
    
    # 调试信息，检查环境变量是否正确
    if BOT_TOKEN:
        print(f"✓ BOT_TOKEN 已设置 (前10位: {BOT_TOKEN[:10]}...)")
    else:
        print("✗ BOT_TOKEN 未设置")
        
    if CHAT_ID:
        print(f"✓ CHAT_ID 已设置: {CHAT_ID}")
    else:
        print("✗ CHAT_ID 未设置")
    
    # 检查锁定文件是否存在
    lock_exists = os.path.exists(LOCK_FILE)
    print(f"锁定文件存在: {'是' if lock_exists else '否'}")
    
    # 首次运行发送启动消息
    if not lock_exists:
        print("发送启动消息...")
        try:
            send("✅ 严格阶梯锁监控已启动")
            print("✓ 启动消息已发送")
        except Exception as e:
            print(f"✗ 发送启动消息失败: {e}")
    else:
        print("检测到已有的锁定文件，不发送启动消息")
    
    print("开始监控...")
    print("-" * 50)
    
    # 运行主循环
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("\n=== 监控程序手动停止 ===")
            break
        except Exception as e:
            print(f"循环错误: {e}")
            # 如果出错，等待更长时间再重试
            time.sleep(min(CHECK_SEC * 5, 300))  # 最多等待5分钟
        
        time.sleep(CHECK_SEC)
