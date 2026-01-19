#!/usr/bin/env python3
import os
import time
import datetime as dt
import requests
import logging
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
        logging.StreamHandler(),
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


class SpreadMonitor:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.cache = PriceData()
        self.high_state = SpreadState(peak=CONFIG["HIGH_THRESHOLD"])
        self.low_state = SpreadState(peak=CONFIG["LOW_THRESHOLD"])
    
    def get_both_assets(self) -> bool:
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
        opposite_state: SpreadState,  # 新增：对方状态
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
        step_check = (
            state.last_gear is None or 
            current_gear >= state.last_gear + CONFIG["GEAR_STEP"] if is_high 
            else current_gear <= state.last_gear - CONFIG["GEAR_STEP"]
        )
        
        if not step_check:
            return
        
        if current_gear not in state.timers:
            state.timers[current_gear] = time.time()
            logger.info(f"  档位 {current_gear:.1f} 开始计时")
        
        if time.time() - state.timers[current_gear] >= CONFIG["DURATION_SEC"]:
            state.peak = mark_spread
            state.last_gear = current_gear
            opposite_state.last_gear = None  # ⭐ 核心：重置对方档位记忆
            
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
        try:
            self.bot.send_message(chat_id=self.chat_id, text=msg)
        except Exception as e:
            logger.error(f"Telegram发送失败: {e}")
    
    def run(self) -> None:
        logger.info("监控服务启动")
        self.send_message("✅ 循环监控已启动 (档位记忆双向重置)")
        
        while True:
            try:
                if self.get_both_assets():
                    spreads = self.calculate_spreads()
                    if spreads:
                        gear = self.calculate_gear(spreads["mark"])
                        logger.info(f"{dt.datetime.now():%H:%M:%S}  Mark={spreads['mark']:.2f}  档位={gear:.1f}")
                        
                        # ⭐ 传递对方状态实现双向重置
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
    if not validate_config():
        exit(1)
    
    monitor = SpreadMonitor(
        bot_token=os.getenv("BOT_TOKEN"),
        chat_id=os.getenv("CHAT_ID")
    )
    monitor.run()
