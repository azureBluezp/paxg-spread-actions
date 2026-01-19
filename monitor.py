#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import logging
import datetime as dt
import pickle
from datetime import datetime
from telegram import Bot
from typing import Dict, Optional
from dataclasses import dataclass, field

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# ===== 配置常量 =====
CONFIG = {
    "CHECK_SEC": int(os.getenv("CHECK_SEC", 10)),  # 10秒检查间隔
    "BASE_URL": "https://omni-client-api.prod.ap-northeast-1.variational.io",
    "HIGH_THRESHOLD": 16.0,
    "LOW_THRESHOLD": 10.0,
    "DURATION_SEC": 1.0,
    "GEAR_STEP": 0.5,
}

# ===== 日志配置 =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("monitor.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class SpreadState:
    timers: Dict[float, float] = field(default_factory=dict)
    peak: float = 0.0
    last_gear: Optional[float] = None
    
    def clear_timers(self):
        self.timers.clear()


@dataclass
class PriceData:
    paxg: Optional[Dict] = None
    xaut: Optional[Dict] = None
    last_update: float = 0.0
    
    def is_expired(self, ttl: float = 5.0) -> bool:
        return time.time() - self.last_update > ttl


class PersistState:
    """状态持久化类"""
    FILE_PATH = "/tmp/spread_state.pkl"
    
    @classmethod
    def load(cls) -> tuple:
        if os.path.exists(cls.FILE_PATH):
            try:
                with open(cls.FILE_PATH, 'rb') as f:
                    data = pickle.load(f)
                    logger.info(f"✅ 状态加载成功: {data}")
                    return data.get('high'), data.get('low')
            except Exception as e:
                logger.warning(f"❌ 状态加载失败: {e}")
        logger.info("⚠️ 无历史状态文件")
        return None, None
    
    @classmethod
    def save(cls, high_gear: Optional[float], low_gear: Optional[float]) -> None:
        try:
            with open(cls.FILE_PATH, 'wb') as f:
                pickle.dump({'high': high_gear, 'low': low_gear}, f)
                logger.info(f"✅ 状态保存成功: high={high_gear}, low={low_gear}")
        except Exception as e:
            logger.error(f"❌ 状态保存失败: {e}")


class SpreadMonitor:
    def __init__(self, bot_token: str, chat_id: str):
        logger.info("=" * 80)
        logger.info("🔧 初始化 SpreadMonitor")
        logger.info("=" * 80)
        
        if ":" not in bot_token:
            raise ValueError("Bot Token 格式错误: 必须包含 ':'")
        
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.cache = PriceData()
        self.high_state = SpreadState(peak=CONFIG["HIGH_THRESHOLD"])
        self.low_state = SpreadState(peak=CONFIG["LOW_THRESHOLD"])
        
        self._load_persistent_state()
    
    def _load_persistent_state(self):
        """加载持久化的档位记忆"""
        high_gear, low_gear = PersistState.load()
        self.high_state.last_gear = high_gear
        self.low_state.last_gear = low_gear
        logger.info(f"档位状态: 高价档={self.high_state.last_gear}, 低价档={self.low_state.last_gear}")
    
    def get_both_assets(self) -> bool:
        """使用 cloudscraper 获取价格数据"""
        if not self.cache.is_expired():
            return True
        
        try:
            logger.debug("🌐 请求API...")
            
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            
            resp = scraper.get(f"{CONFIG['BASE_URL']}/metadata/stats", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            listings = {item["ticker"]: item for item in data["listings"]}
            if "PAXG" not in listings or "XAUT" not in listings:
                logger.error("❌ 缺少交易对")
                return False
            
            self.cache.paxg = self._parse_asset(listings["PAXG"])
            self.cache.xaut = self._parse_asset(listings["XAUT"])
            self.cache.last_update = time.time()
            logger.debug("✅ API成功")
            return True
        except Exception as e:
            logger.error(f"❌ API失败: {e}")
            return False
    
    @staticmethod
    def _parse_asset(item: dict) -> dict:
        return {
            "mark": float(item["mark_price"]),
            "bid_1k": float(item["quotes"]["size_1k"]["bid"]),
            "ask_1k": float(item["quotes"]["size_1k"]["ask"]),
        }
    
    def calculate_spreads(self) -> Optional[dict]:
        if not self.cache.paxg or not self.cache.xaut:
            return None
        paxg, xaut = self.cache.paxg, self.cache.xaut
        return {
            "mark": paxg["mark"] - xaut["mark"],
            "short": paxg["bid_1k"] - xaut["ask_1k"],
            "long": paxg["ask_1k"] - xaut["bid_1k"],
        }
    
    @staticmethod
    def calculate_gear(value: float) -> float:
        return
