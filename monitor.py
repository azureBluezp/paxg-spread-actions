#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import logging
import pickle
import argparse
import sys
from dataclasses import dataclass, field
from telegram import Bot
from typing import Dict, Optional

# ===== 配置常量 =====
CONFIG = {
    "CHECK_SEC": int(os.getenv("CHECK_SEC", 30)),
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
    def load(cls) -> tuple[Optional[float], Optional[float]]:
        if os.path.exists(cls.FILE_PATH):
            try:
                with open(cls.FILE_PATH, 'rb') as f:
                    data = pickle.load(f)
                    logger.info(f"加载历史状态: {data}")
                    return data.get('high'), data.get('low')
            except Exception as e:
                logger.warning(f"状态加载失败: {e}")
        logger.info("⚠️ 无历史状态文件")
        return None, None
    
    @classmethod
    def save(cls, high_gear: Optional[float], low_gear: Optional[float]) -> None:
        try:
            with open(cls.FILE_PATH, 'wb') as f:
                pickle.dump({'high': high_gear, 'low': low_gear}, f)
                logger.info(f"状态保存成功: high={high_gear}, low={low_gear}")
        except Exception as e:
            logger.error(f"状态保存失败: {e}")


class SpreadMonitor:
    def __init__(self, bot_token: str, chat_id: str):
        logger.info("=" * 80)
        logger.info("🔧 初始化 SpreadMonitor")
        logger.info(f"📱 Bot Token: {bot_token[:10]}...{bot_token[-5:]}")
        logger.info(f"💬 Chat ID: {chat_id}")
        logger.info("=" * 80)
        
        # 验证 Bot Token 格式
        if ":" not in bot_token:
            raise ValueError("Bot Token 格式错误: 必须包含 ':'")
        
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.cache = PriceData()
        self.high_state = SpreadState(peak=CONFIG["HIGH_THRESHOLD"])
        self.low_state = SpreadState(peak=CONFIG["LOW_THRESHOLD"])
        
        self._load_persistent_state()
    
    def _load_persistent_state(self):
        logger.info("📂 正在加载历史状态...")
        high_gear, low_gear = PersistState.load()
        self.high_state.last_gear = high_gear
        self.low_state.last_gear = low_gear
        logger.info(f"📊 最终状态: 高价档={self.high_state.last_gear}, 低价档={self.low_state.last_gear}")
    
    def _save_persistent_state(self):
        logger.info("💾 正在保存状态...")
        PersistState.save(self.high_state.last_gear, self.low_state.last_gear)
    
    def get_both_assets(self) -> bool:
        if not self.cache.is_expired():
            return True
        
        try:
            logger.debug("🌐 请求API...")
            resp = requests.get(
                f"{CONFIG['BASE_URL']}/metadata/stats",
                timeout=10
            )
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
        return int(value * 2) / 2
    
    def check_threshold(
        self, 
        spreads: dict,
        state: SpreadState,
        opposite_state: SpreadState,
        threshold: float,
        is_high: bool
    ) -> None:
        mark_spread = spreads["mark"]
        directional_spread = spreads["short" if is_high else "long"]
        
        condition = mark_spread >= threshold if is_high else mark_spread <= threshold
        
        if not condition:
            if state.timers:
                state.clear_timers()
                logger.info(f"  清除{'≥16' if is_high else '≤10'}计时器")
            return
        
        current_gear = self.calculate_gear(mark_spread)
        
        if is_high:
            step_check = current_gear >= (state.last_gear or -999) + CONFIG["GEAR_STEP"]
        else:
            step_check = current_gear <= (state.last_gear or 999) - CONFIG["GEAR_STEP"]
        
        if not step_check:
            return
        
        if current_gear not in state.timers:
            state.timers[current_gear] = time.time()
            logger.info(f"  档位 {current_gear:.1f} 开始计时")
        
        if time.time() - state.timers[current_gear] >= CONFIG["DURATION_SEC"]:
            state.peak = mark_spread
            state.last_gear = current_gear
            opposite_state.last_gear = None
            
            self._save_persistent_state()
            
            action = "做空PAXG@市价，做多XAUT@市价" if is_high else "做多PAXG@市价，做空XAUT@市价"
            msg = (
                f"🔔 PAXG {'新高' if is_high else '新低'}溢价 {'≥16' if is_high else '≤10'}！\n"
                f"真实成交价差: {directional_spread:.2f}\n"
                f"（{action}）\n"
                f"Mark参考: {mark_spread:.2f}"
            )
            
            self.send_message(msg)
            logger.info(f"  ✅ 报警发送: 档位 {current_gear:.1f}")
            state.clear_timers()
    
    def send_message(self, msg: str) -> None:
        """发送Telegram消息（修复版）"""
        try:
            # 修复：在f-string外部处理字符串
            clean_msg = msg.replace('\n', ' ')
            logger.info(f"📤 发送消息: {clean_msg}")
            
            result = self.bot.send_message(chat_id=self.chat_id, text=msg)
            logger.info(f"✅ 消息成功: {result.message_id}")
            time.sleep(2)  # 确保发送完成
        except Exception as e:
            logger.error(f"❌ 发送失败: {e}")
    
    def run_once(self) -> None:
        """单次运行模式"""
        logger.info("=" * 80)
        logger.info("🚀 单次运行模式启动")
        logger.info(f"⏰ 时间: {dt.datetime.now()}")
        logger.info(f"📊 状态: 高价档={self.high_state.last_gear}, 低价档={self.low_state.last_gear}")
        logger.info("=" * 80)
        
        # 发送启动消息
        try:
            start_msg = f"✅ Actions监控启动\n高价档: {self.high_state.last_gear}\n低价档: {self.low_state.last_gear}"
            self.send_message(start_msg)
            logger.info("⏳ 等待消息确认...")
            time.sleep(3)
        except Exception as e:
            logger.error(f"❌ 启动消息失败: {e}")
        
        # 检测价差
        try:
            if self.get_both_assets():
                spreads = self.calculate_spreads()
                if spreads:
                    gear = self.calculate_gear(spreads["mark"])
                    logger.info(f"🎯 检测: Mark={spreads['mark']:.2f} 档位={gear:.1f}")
                    
                    self.check_threshold(spreads, self.high_state, self.low_state, CONFIG["HIGH_THRESHOLD"], True)
                    self.check_threshold(spreads, self.low_state, self.high_state, CONFIG["LOW_THRESHOLD"], False)
        except Exception as e:
            logger.exception(f"❌ 检测失败: {e}")
        
        logger.info("⏳ 最终等待...")
        time.sleep(3)
        logger.info("✅ 单次运行结束")
    
    def run(self) -> None:
        """持续运行模式"""
        logger.info("=" * 80)
        logger.info("🚀 VPS监控启动")
        logger.info(f"⚙️ 配置: 检测间隔={CONFIG['CHECK_SEC']}秒")
        logger.info(f"📊 状态: 高价档={self.high_state.last_gear}, 低价档={self.low_state.last_gear}")
        logger.info("=" * 80)
        
        self.send_message("✅ VPS监控启动成功")
        
        while True:
            try:
                if self.get_both_assets():
                    spreads = self.calculate_spreads()
                    if spreads:
                        gear = self.calculate_gear(spreads["mark"])
                        logger.info(f"{dt.datetime.now():%H:%M:%S} Mark={spreads['mark']:.2f} 档位={gear:.1f}")
                        
                        self.check_threshold(spreads, self.high_state, self.low_state, CONFIG["HIGH_THRESHOLD"], True)
                        self.check_threshold(spreads, self.low_state, self.high_state, CONFIG["LOW_THRESHOLD"], False)
                
            except Exception as e:
                logger.exception(f"❌ 主循环异常: {e}")
            
            time.sleep(CONFIG["CHECK_SEC"])


def validate_config() -> bool:
    logger.info("🔍 验证配置...")
    required = ["BOT_TOKEN", "CHAT_ID"]
    for var in required:
        value = os.getenv(var)
        if not value:
            logger.error(f"❌ 缺少 {var}")
            return False
        logger.info(f"✅ {var}: {value[:10]}...")
    
    token = os.getenv("BOT_TOKEN")
    if ":" not in token:
        logger.error("❌ BOT_TOKEN格式错误")
        return False
    
    logger.info("✅ 配置验证通过")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="GitHub Actions单次模式")
    args = parser.parse_args()
    
    logger.info(f"🎯 运行模式: {'单次' if args.once else '持续'}")
    
    if not validate_config():
        logger.error("❌ 配置验证失败，退出")
        exit(1)
    
    monitor = SpreadMonitor(
        bot_token=os.getenv("BOT_TOKEN"),
        chat_id=os.getenv("CHAT_ID")
    )
    
    try:
        if args.once:
            monitor.run_once()
        else:
            monitor.run()
    except Exception as e:
        logger.exception(f"❌ 致命错误: {e}")
        exit(1)
