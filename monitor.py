#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import json
import re
import traceback
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
        print(f"请求API: {BASE_URL}/metadata/stats")
        response = requests.get(f"{BASE_URL}/metadata/stats", timeout=10)
        print(f"API响应状态码: {response.status_code}")
        data = response.json()
        
        for i in data.get("listings", []):
            if i.get("ticker") == sym:
                price_val = float(i.get("mark_price", 0))
                print(f"找到 {sym}: {price_val}")
                return price_val
        raise RuntimeError(f"{sym} 未找到")
    except Exception as e:
        print(f"获取价格失败: {e}")
        raise

def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """直接使用requests发送Telegram消息，避免Bot初始化问题"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        
        print(f"发送Telegram消息到URL: {url}")
        print(f"消息内容: {text}")
        
        response = requests.post(url, data=payload, timeout=10)
        print(f"Telegram API响应: {response.status_code}")
        print(f"Telegram API响应内容: {response.text}")
        
        if response.status_code == 200:
            print("✓ Telegram消息发送成功")
            return True
        else:
            print(f"✗ Telegram消息发送失败: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ 发送Telegram消息异常: {e}")
        traceback.print_exc()
        return False

def send(msg: str):
    """发送消息到Telegram"""
    return send_telegram_message(BOT_TOKEN, CHAT_ID, msg)

def send_heartbeat(paxg: float, xaut: float, spread: float, start_time: float):
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

def main(start_time: float):
    global last_heartbeat_time
    
    try:
        print(f"开始获取价格数据...")
        paxg = price("PAXG")
        xaut = price("XAUT")
        spread = paxg - xaut
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp}  PAXG={paxg:.2f}  XAUT={xaut:.2f}  spread={spread:.2f}")

        # 检查是否需要发送心跳消息（每30分钟）
        current_time = time.time()
        if current_time - last_heartbeat_time >= HEARTBEAT_MINUTES * 60:
            print(f"发送心跳消息，距离上次: {current_time - last_heartbeat_time:.0f}秒")
            if send_heartbeat(paxg, xaut, spread, start_time):
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
                    print(f"检测到新高溢价! spread={spread:.2f}, old={old:.2f}")
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
                    print(f"检测到新低溢价! spread={spread:.2f}, old={old:.2f}")
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
    print(f"启动时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"检查间隔: {CHECK_SEC}秒")
    print(f"心跳间隔: {HEARTBEAT_MINUTES}分钟")
    print(f"锁定文件: {LOCK_FILE}")
    print(f"工作目录: {os.getcwd()}")
    
    # 详细的环境变量检查
    print(f"\n=== 环境变量检查 ===")
    
    if BOT_TOKEN:
        print(f"✓ BOT_TOKEN 已设置")
        print(f"  长度: {len(BOT_TOKEN)} 字符")
        print(f"  前20位: {BOT_TOKEN[:20]}...")
        
        # 检查 BOT_TOKEN 格式
        if ':' in BOT_TOKEN:
            print(f"  格式: 正确 (包含冒号分隔符)")
            parts = BOT_TOKEN.split(':')
            if len(parts) == 2:
                print(f"  Bot ID: {parts[0]}")
                print(f"  Token部分长度: {len(parts[1])} 字符")
        else:
            print(f"  警告: 格式可能不正确，正确格式应为 '数字:字母'")
    else:
        print(f"✗ BOT_TOKEN 未设置或为空")
        
    if CHAT_ID:
        print(f"✓ CHAT_ID 已设置")
        print(f"  值: {CHAT_ID}")
        # 检查 CHAT_ID 是否为数字（如果是用户ID）
        if CHAT_ID.lstrip('-').replace('.', '').isdigit():
            print(f"  类型: 数字ID")
        else:
            print(f"  类型: 用户名格式")
    else:
        print(f"✗ CHAT_ID 未设置或为空")
    
    # 检查锁定文件是否存在
    lock_exists = os.path.exists(LOCK_FILE)
    print(f"\n锁定文件存在: {'是' if lock_exists else '否'}")
    
    # 测试环境变量是否有效
    print(f"\n=== 环境变量测试 ===")
    
    # 测试Bot Token格式
    if BOT_TOKEN and ':' in BOT_TOKEN:
        parts = BOT_TOKEN.split(':')
        if len(parts) == 2 and parts[0].isdigit() and len(parts[1]) > 10:
            print(f"✓ Bot Token 格式验证通过")
            
            # 尝试通过Telegram API测试Bot Token
            try:
                test_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
                print(f"测试Telegram API连接: {test_url}")
                response = requests.get(test_url, timeout=10)
                if response.status_code == 200:
                    bot_info = response.json()
                    print(f"✓ Bot验证成功: {bot_info.get('result', {}).get('username')}")
                else:
                    print(f"✗ Bot验证失败: HTTP {response.status_code}")
                    print(f"  响应: {response.text}")
            except Exception as e:
                print(f"✗ Bot验证异常: {e}")
        else:
            print(f"✗ Bot Token 格式不正确")
    else:
        print(f"✗ Bot Token 格式不正确或未设置")
    
    # 发送启动消息
    print(f"\n=== 发送启动消息 ===")
    
    if BOT_TOKEN and CHAT_ID:
        print("正在发送启动消息...")
        try:
            current_time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            msg = (f"✅ 严格阶梯锁监控已启动\n"
                   f"启动时间: {current_time}\n"
                   f"检查间隔: {CHECK_SEC}秒\n"
                   f"心跳间隔: {HEARTBEAT_MINUTES}分钟\n"
                   f"工作目录: {os.getcwd()}")
            
            if send(msg):
                print("✓ 启动消息发送命令已执行")
            else:
                print("✗ 启动消息发送失败")
                
        except Exception as e:
            print(f"✗ 发送启动消息异常: {e}")
            traceback.print_exc()
    else:
        print("无法发送启动消息: 缺少必要的环境变量")
        if not BOT_TOKEN:
            print("  - BOT_TOKEN未设置")
        if not CHAT_ID:
            print("  - CHAT_ID未设置")
    
    # 初始化心跳时间
    last_heartbeat_time = time.time()
    
    print("\n=== 开始监控 ===")
    print("-" * 50)
    
    # 运行主循环
    loop_count = 0
    while True:
        try:
            loop_count += 1
            print(f"\n循环 #{loop_count} - {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            main(start_time)
            
        except KeyboardInterrupt:
            print("\n=== 监控程序手动停止 ===")
            # 发送停止消息
            if BOT_TOKEN and CHAT_ID:
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
            wait_time = min(CHECK_SEC * 5, 300)
            print(f"等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)
        
        print(f"等待 {CHECK_SEC} 秒后继续...")
        time.sleep(CHECK_SEC)
