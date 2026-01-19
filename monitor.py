#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import datetime as dt
import cloudscraper
from telegram import Bot

# ===== 配置 =====
CHECK_SEC = 10
BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"
HIGH_THRESHOLD = 16.0
LOW_THRESHOLD = 10.0
DURATION_SEC = 1.0
GEAR_STEP = 0.5

# ===== Telegram 配置 =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ===== 日志配置 =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class SpreadMonitor:
    def __init__(self):
        logger.info("🔧 初始化 SpreadMonitor")
        self.bot = Bot(token=BOT_TOKEN)
        self.last_high_gear = None
        self.last_low_gear = None
    
    def get_spread_data(self) -> dict:
        """获取 PAXG & XAUT 价格数据"""
        try:
            scraper = cloudscraper.create_scraper()
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            
            resp = scraper.get(f"{BASE_URL}/metadata/stats", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            listings = {item["ticker"]: item for item in data["listings"]}
            
            paxg = {
                "mark": float(listings["PAXG"]["mark_price"]),
                "bid_1k": float(listings["PAXG"]["quotes"]["size_1k"]["bid"]),
                "ask_1k": float(listings["PAXG"]["quotes"]["size_1k"]["ask"]),
            }
            
            xaut = {
                "mark": float(listings["XAUT"]["mark_price"]),
                "bid_1k": float(listings["XAUT"]["quotes"]["size_1k"]["bid"]),
                "ask_1k": float(listings["XAUT"]["quotes"]["size_1k"]["ask"]),
            }
            
            return {
                "mark": paxg["mark"] - xaut["mark"],
                "short": paxg["bid_1k"] - xaut["ask_1k"],
                "long": paxg["ask_1k"] - xaut["bid_1k"],
            }
            
        except Exception as e:
            logger.error(f"❌ 获取数据失败: {e}")
            return None
    
    def calculate_gear(self, value: float) -> float:
        return int(value * 2) / 2
    
    def check_and_alert(self, spreads: dict):
        """检查价差并发送警报"""
        if not spreads:
            return
        
        mark_spread = spreads["mark"]
        logger.info(f"当前价差: Mark={mark_spread:.2f}")
        
        # 检查高价阈值
        if mark_spread >= HIGH_THRESHOLD:
            current_gear = self.calculate_gear(mark_spread)
            if self.last_high_gear is None or current_gear >= (self.last_high_gear + GEAR_STEP):
                self.last_high_gear = current_gear
                self.last_low_gear = None
                
                msg = (
                    f"🔔 PAXG 溢价 ≥ {HIGH_THRESHOLD}！\n"
                    f"当前档位: {current_gear:.1f}\n"
                    f"Mark价差: {mark_spread:.2f}\n"
                    f"真实成交价差: {spreads['short']:.2f}\n"
                    f"建议: 做空PAXG，做多XAUT"
                )
                
                self.send_message(msg)
                logger.info(f"✅ 高价报警发送: {current_gear:.1f}")
        
        # 检查低价阈值
        elif mark_spread <= LOW_THRESHOLD:
            current_gear = self.calculate_gear(mark_spread)
            if self.last_low_gear is None or current_gear <= (self.last_low_gear - GEAR_STEP):
                self.last_low_gear = current_gear
                self.last_high_gear = None
                
                msg = (
                    f"🔔 PAXG 溢价 ≤ {LOW_THRESHOLD}！\n"
                    f"当前档位: {current_gear:.1f}\n"
                    f"Mark价差: {mark_spread:.2f}\n"
                    f"真实成交价差: {spreads['long']:.2f}\n"
                    f"建议: 做多PAXG，做空XAUT"
                )
                
                self.send_message(msg)
                logger.info(f"✅ 低价报警发送: {current_gear:.1f}")
    
    def send_message(self, msg: str):
        """发送Telegram消息"""
        try:
            logger.info(f"📤 发送: {msg[:50]}...")
            self.bot.send_message(chat_id=CHAT_ID, text=msg)
            logger.info("✅ 消息发送成功")
        except Exception as e:
            logger.error(f"❌ 发送失败: {e}")
    
    def run(self):
        """运行一次快速检测"""
        logger.info("=" * 80)
        logger.info("🚀 PAXG 价差监控启动")
        logger.info(f"⏰ 时间: {dt.datetime.now()}")
        logger.info("=" * 80)
        
        max_checks = 5  # 运行5次检查
        for i in range(max_checks):
            spreads = self.get_spread_data()
            if spreads:
                self.check_and_alert(spreads)
            time.sleep(CHECK_SEC)
        
        logger.info("✅ 快速检测完成")


if __name__ == "__main__":
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("❌ 缺少 BOT_TOKEN 或 CHAT_ID")
        exit(1)
    
    monitor = SpreadMonitor()
    monitor.run()
