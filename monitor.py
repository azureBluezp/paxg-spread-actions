#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
import re
from telegram import Bot, error as telegram_error

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
        # 移除所有非数字字符
        value = re.sub(r'[^\d-]', '', value)
        return int(value)
    except (ValueError, TypeError):
        print(f"警告: {key} 值 '{value}' 不是有效整数，使用默认值 {default}")
        return default

# 获取环境变量
BOT_TOKEN = get_env("BOT_TOKEN")
CHAT_ID = get_env("CHAT_ID")
CHECK_SEC = get_env_int("CHECK_SEC", 30)  # 默认30秒
HEARTBEAT_MINUTES = 30  # 心跳消息间隔（分钟）

# 全局变量记录最后一次心跳时间
last_heartbeat_time = time.time()

LOCK_FILE = "strict_step_lock.json"

def load_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                return json.load(f)
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
        BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"
        data = requests.get(f"{BASE_URL}/metadata/stats", timeout=10).json()
        for i in data.get("listings", []):
            if i.get("ticker") == sym:
                return float(i.get("mark_price", 0))
        raise RuntimeError(f"{sym} 未找到")
    except Exception as e:
        print(f"获取价格失败: {e}")
        raise

def send(msg: str, bot: Bot, chat_id: str):
    """发送消息到Telegram"""
    try:
        bot.send_message(chat_id=chat_id, text=msg)
        print(f"✓ 消息已发送: {msg}")
        return True
    except telegram_error.InvalidToken:
        print(f"✗ Bot Token无效")
        return False
    except telegram_error.Unauthorized:
        print(f"✗ Bot无权发送消息到该聊天")
        return False
    except Exception as e:
        print(f"✗ 发送消息失败: {e}")
        return False

def send_heartbeat(paxg: float, xaut: float, spread: float, bot: Bot, chat_id: str, start_time: float):
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
    
    return send(msg, bot, chat_id)

def main(bot: Bot, chat_id: str, start_time: float):
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
            if send_heartbeat(paxg, xaut, spread, bot, chat_id, start_time):
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
                    send(msg, bot, chat_id)

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
                    send(msg, bot, chat_id)
    except Exception as e:
        print(f"主函数错误: {e}")

if __name__ == "__main__":
    # 记录程序启动时间
    start_time = time.time()
    
    print(f"=== PAXG 监控程序启动 ===")
    print(f"检查间隔: {CHECK_SEC}秒")
    print(f"心跳间隔: {HEARTBEAT_MINUTES}分钟")
    print(f"锁定文件: {LOCK_FILE}")
    
    # 调试信息，检查环境变量是否正确
    if BOT_TOKEN:
        print(f"BOT_TOKEN 长度: {len(BOT_TOKEN)} 字符")
        print(f"BOT_TOKEN 前20位: {BOT_TOKEN[:20]}")
        
        # 检查 BOT_TOKEN 格式
        if ':' in BOT_TOKEN:
            print("✓ BOT_TOKEN 格式看起来正确（包含冒号）")
        else:
            print("⚠ BOT_TOKEN 格式可能不正确，正确格式应为 '数字:字母'")
    else:
        print("✗ BOT_TOKEN 未设置")
        
    if CHAT_ID:
        print(f"✓ CHAT_ID 已设置: {CHAT_ID}")
        # 检查 CHAT_ID 是否为数字（如果是用户ID）
        if CHAT_ID.lstrip('-').isdigit():
            print(f"  CHAT_ID 为数字ID")
        else:
            print(f"  CHAT_ID 为用户名格式")
    else:
        print("✗ CHAT_ID 未设置")
    
    # 检查锁定文件是否存在
    lock_exists = os.path.exists(LOCK_FILE)
    print(f"锁定文件存在: {'是' if lock_exists else '否'}")
    
    # 初始化Bot对象
    bot = None
    if BOT_TOKEN:
        try:
            print("正在初始化Telegram Bot...")
            bot = Bot(token=BOT_TOKEN)
            
            # 测试Bot是否有效（不验证token，直接尝试发送消息）
            print("跳过Bot连接测试，直接尝试发送消息...")
            
        except Exception as e:
            print(f"初始化Bot时出错: {e}")
            bot = None
    
    # 发送启动消息
    if bot and CHAT_ID:
        print("发送启动消息...")
        try:
            current_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            msg = (f"✅ 严格阶梯锁监控已启动\n"
                   f"启动时间: {current_time}\n"
                   f"检查间隔: {CHECK_SEC}秒\n"
                   f"心跳间隔: {HEARTBEAT_MINUTES}分钟\n"
                   f"BOT_TOKEN前10位: {BOT_TOKEN[:10]}")
            if send(msg, bot, CHAT_ID):
                print("✓ 启动消息已发送")
            else:
                print("✗ 启动消息发送失败")
        except Exception as e:
            print(f"发送启动消息异常: {e}")
    else:
        print("无法发送启动消息: Bot或CHAT_ID未正确设置")
        if not bot:
            print("  - Bot初始化失败")
        if not CHAT_ID:
            print("  - CHAT_ID未设置")
    
    # 初始化心跳时间
    last_heartbeat_time = time.time()
    
    print("开始监控...")
    print("-" * 50)
    
    # 运行主循环
    while True:
        try:
            if bot and CHAT_ID:
                main(bot, CHAT_ID, start_time)
            else:
                # 如果没有有效的Bot，尝试重新初始化
                if BOT_TOKEN and not bot:
                    try:
                        bot = Bot(token=BOT_TOKEN)
                        print("✓ Bot重新初始化成功")
                    except:
                        print("✗ Bot重新初始化失败")
                
                # 模拟价格检查，即使没有Bot
                try:
                    paxg = price("PAXG")
                    xaut = price("XAUT")
                    spread = paxg - xaut
                    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"{timestamp}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f} (无Bot)")
                except Exception as e:
                    print(f"价格检查失败: {e}")
                
        except KeyboardInterrupt:
            print("\n=== 监控程序手动停止 ===")
            # 发送停止消息
            if bot and CHAT_ID:
                stop_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                uptime = time.time() - start_time
                hours = int(uptime // 3600)
                minutes = int((uptime % 3600) // 60)
                stop_msg = (f"🛑 监控程序已停止\n"
                           f"停止时间: {stop_time}\n"
                           f"运行时长: {hours}小时{minutes}分钟")
                send(stop_msg, bot, CHAT_ID)
            break
        except Exception as e:
            print(f"循环错误: {e}")
            # 如果出错，等待更长时间再重试
            time.sleep(min(CHECK_SEC * 5, 300))  # 最多等待5分钟
        
        time.sleep(CHECK_SEC)
