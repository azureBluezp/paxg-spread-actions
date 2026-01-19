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
                    logger.info(f"加载历史状态: last_high_gear={data.get('high')}, last_low_gear={data.get('low')}")
                    return data.get('high'), data.get('low')
            except Exception as e:
                logger.warning(f"状态加载失败: {e}")
        return None, None
    
    @classmethod
    def save(cls, high_gear: Optional[float], low_gear: Optional[float]) -> None:
        try:
            with open(cls.FILE_PATH, 'wb') as f:
                pickle.dump({'high': high_gear, 'low': low_gear}, f)
                logger.debug("状态已保存")
        except Exception as e:
            logger.error(f"状态保存失败: {e}")


class SpreadMonitor:
    def __init__(self, bot_token: str, chat_id: str):
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
    
    def _save_persistent_state(self):
        """保存当前档位记忆"""
        PersistState.save(self.high_state.last_gear, self.low_state.last_gear)
    
    def get_both_assets(self) -> bool:
        if not self.cache.is_expired():
            return True
        
        try:
            resp = requests.get(
                f"{CONFIG['BASE_URL']}/metadata/stats",
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            
            listings = {item["ticker"]: item for item in data["listings"]}
            if "PAXG" not in listings or "XAUT" not in listings:
                logger.error("缺少交易对数据")
                return False
            
            self.cache.paxg = self._parse_asset(listings["PAXG"])
            self.cache.xaut = self._parse_asset(listings["XAUT"])
            self.cache.last_update = time.time()
            return True
        except Exception as e:
            logger.error(f"API请求失败: {e}")
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
        """发送Telegram消息"""
        try:
            self.bot.send_message(chat_id=self.chat_id, text=msg)
        except Exception as e:
            logger.error(f"Telegram发送失败: {e}")
    
    def run_once(self) -> None:
        """单次运行模式 - 用于GitHub Actions"""
        logger.info("单次运行模式启动")
        
        # 发送启动消息
        try:
            start_msg = (
                f"✅ Actions监控启动\n"
                f"状态: 高价档={self.high_state.last_gear}, 低价档={self.low_state.last_gear}"
            )
            self.bot.send_message(chat_id=self.chat_id, text=start_msg)
            logger.info("启动消息已发送")
            time.sleep(3)  # 确保消息发送完成
        except Exception as e:
            logger.error(f"启动消息失败: {e}")
        
        # 执行一次完整检查
        try:
            if self.get_both_assets():
                spreads = self.calculate_spreads()
                if spreads:
                    gear = self.calculate_gear(spreads["mark"])
                    logger.info(f"检测: Mark={spreads['mark']:.2f} 档位={gear:.1f}")
                    
                    self.check_threshold(
                        spreads, self.high_state, self.low_state, 
                        CONFIG["HIGH_THRESHOLD"], True
                    )
                    self.check_threshold(
                        spreads, self.low_state, self.high_state, 
                        CONFIG["LOW_THRESHOLD"], False
                    )
        except Exception as e:
            logger.exception(f"检测异常: {e}")
        
        logger.info("等待消息发送完成...")
        time.sleep(3)
    
    def run(self) -> None:
        """持续运行模式 - 用于VPS"""
        logger.info("=" * 60)
        logger.info("监控服务启动中...")
        logger.info(f"配置: 检测间隔={CONFIG['CHECK_SEC']}秒")
        logger.info(f"状态: 高价档={self.high_state.last_gear}, 低价档={self.low_state.last_gear}")
        logger.info("=" * 60)
        
        # 发送启动消息
        try:
            start_msg = f"✅ VPS监控启动成功\n检测间隔: {CONFIG['CHECK_SEC']}秒"
            self.send_message(start_msg)
            logger.info("启动消息已发送到 Telegram")
        except Exception as e:
            logger.error(f"启动消息发送失败: {e}")
        
        while True:
            try:
                if self.get_both_assets():
                    spreads = self.calculate_spreads()
                    if spreads:
                        gear = self.calculate_gear(spreads["mark"])
                        logger.info(f"{dt.datetime.now():%H:%M:%S}  Mark={spreads['mark']:.2f}  档位={gear:.1f}")
                        
                        self.check_threshold(
                            spreads, self.high_state, self.low_state, 
                            CONFIG["HIGH_THRESHOLD"], True
                        )
                        self.check_threshold(
                            spreads, self.low_state, self.high_state, 
                            CONFIG["LOW_THRESHOLD"], False
                        )
                
            except Exception as e:
                logger.exception(f"主循环异常: {e}")
            
            time.sleep(CONFIG["CHECK_SEC"])


def validate_config() -> bool:
    required = ["BOT_TOKEN", "CHAT_ID"]
    for var in required:
        if not os.getenv(var):
            logger.error(f"缺少必需的环境变量: {var}")
            return False
    
    token = os.getenv("BOT_TOKEN")
    if not token or ":" not in token:
        logger.error("BOT_TOKEN格式无效")
        return False
    
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="单次运行模式（用于GitHub Actions）")
    args = parser.parse_args()
    
    if not validate_config():
        exit(1)
    
    monitor = SpreadMonitor(
        bot_token=os.getenv("BOT_TOKEN"),
        chat_id=os.getenv("CHAT_ID")
    )
    
    if args.once:
        monitor.run_once()
    else:
        monitor.run()
