#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
from telegram import Bot
import traceback

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
HEARTBEAT_MINUTES = 30  # 心跳消息间隔（分钟）

# 全局变量记录最后一次心跳时间
last_heartbeat_time = time.time()

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
    return f"{dt.datetime.now():%Y-%m-d-%H}-{gear:.2f}"

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
    """发送消息到Telegram"""
    try:
        print(f"尝试发送消息: {msg[:100]}...")
        bot.send_message(chat_id=CHAT_ID, text=msg)
        print(f"✓ 消息已发送: {msg}")
        return True
    except Exception as e:
        print(f"✗ 发送消息失败: {e}")
        traceback.print_exc()
        return False

def send_heartbeat(paxg: float, xaut: float, spread: float):
    """发送心跳消息，报告程序运行状态"""
    current_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uptime = time.time() - start_time
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    
    lock = load_lock()
    high_peak = lock.get("high_peak", 16.0)
    low_valley = lock.get("low_valley", 10.0)
    
    msg = (f"❤️ 监控程序运行状态\n"
           f"时间: {current_time}\n"
           f"运行时长: {hours}小时{minutes}分钟\n"
           f"当前价格:\n"
           f"  PAXG: {paxg:.2f}\n"
           f"  XAUT: {xaut:.2f}\n"
           f"  价差: {spread:.2f}\n"
           f"当前记录:\n"
           f"  最高溢价: {high_peak:.2f}\n"
           f"  最低溢价: {low_valley:.2f}\n"
           f"检查间隔: {CHECK_SEC}秒\n"
           f"程序正常运行中...")
    
    return send(msg)

def main():
    global last_heartbeat_time
    
    try:
        paxg = price("PAXG")
        xaut = price("XAUT")
        spread = paxg - xaut
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")

        # 检查是否需要发送心跳消息（每30分钟）
        current_time = time.time()
        if current_time - last_heartbeat_time >= HEARTBEAT_MINUTES * 60:
            if send_heartbeat(paxg, xaut, spread):
                last_heartbeat_time = current_time

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
        traceback.print_exc()

if __name__ == "__main__":
    # 记录程序启动时间
    start_time = time.time()
    
    print(f"=== PAXG 监控程序启动 ===")
    print(f"检查间隔: {CHECK_SEC}秒")
    print(f"心跳间隔: {HEARTBEAT_MINUTES}分钟")
    print(f"锁定文件: {LOCK_FILE}")
    
    # 调试信息，检查环境变量是否正确
    if BOT_TOKEN:
        print(f"✓ BOT_TOKEN 已设置 (前10位: {BOT_TOKEN[:10]}...)")
        # 如果BOT_TOKEN太短，可能是错误的
        if len(BOT_TOKEN) < 30:
            print(f"警告: BOT_TOKEN长度只有{len(BOT_TOKEN)}，可能不正确")
    else:
        print("✗ BOT_TOKEN 未设置")
        
    if CHAT_ID:
        print(f"✓ CHAT_ID 已设置: {CHAT_ID}")
    else:
        print("✗ CHAT_ID 未设置")
    
    # 检查锁定文件是否存在
    lock_exists = os.path.exists(LOCK_FILE)
    print(f"锁定文件存在: {'是' if lock_exists else '否'}")
    
    # 先初始化Bot对象，以便发送测试消息
    try:
        print("正在初始化Telegram Bot...")
        bot = Bot(token=BOT_TOKEN)
        
        # 测试Bot是否有效
        print("测试Bot连接...")
        bot_info = bot.get_me()
        print(f"✓ Bot已连接: {bot_info.username} (ID: {bot_info.id})")
        
        # 测试发送消息
        print("发送测试消息...")
        test_msg = "🤖 Bot连接测试消息"
        bot.send_message(chat_id=CHAT_ID, text=test_msg)
        print(f"✓ 测试消息已发送: {test_msg}")
        
    except Exception as e:
        print(f"✗ 初始化Bot失败: {e}")
        traceback.print_exc()
        exit(1)
    
    # 初始化API连接
    BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"
    print(f"API地址: {BASE_URL}")
    
    # 发送启动消息
    print("发送启动消息...")
    try:
        current_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = (f"✅ 严格阶梯锁监控已启动\n"
               f"启动时间: {current_time}\n"
               f"检查间隔: {CHECK_SEC}秒\n"
               f"心跳间隔: {HEARTBEAT_MINUTES}分钟")
        if send(msg):
            print("✓ 启动消息已发送")
        else:
            print("✗ 启动消息发送失败")
    except Exception as e:
        print(f"✗ 发送启动消息异常: {e}")
        traceback.print_exc()
    
    # 初始化心跳时间
    last_heartbeat_time = time.time()
    
    print("开始监控...")
    print("-" * 50)
    
    # 运行主循环
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("\n=== 监控程序手动停止 ===")
            # 发送停止消息
            stop_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            uptime = time.time() - start_time
            hours = int(uptime // 3600)
            minutes = int((uptime % 3600) // 60)
            stop_msg = (f"🛑 监控程序已停止\n"
                       f"停止时间: {stop_time}\n"
                       f"运行时长: {hours}小时{minutes}分钟")
            send(stop_msg)
            break
        except Exception as e:
            print(f"循环错误: {e}")
            traceback.print_exc()
            # 如果出错，等待更长时间再重试
            time.sleep(min(CHECK_SEC * 5, 300))  # 最多等待5分钟
        
        time.sleep(CHECK_SEC)
