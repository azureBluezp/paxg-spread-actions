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
    "DURATION_SEC": 1.0,  # 持续时长
    "GEAR_STEP": 0.5,     # 档位步长
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
    """状态管理类，替代全局变量"""
    timers: Dict[float, float] = field(default_factory=dict)
    peak: float = 0.0
    last_gear: Optional[float] = None
    
    def clear_timers(self):
        self.timers.clear()


@dataclass
class PriceData:
    """价格数据缓存"""
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
        
        # 双向监控状态
        self.high_state = SpreadState(peak=CONFIG["HIGH_THRESHOLD"])
        self.low_state = SpreadState(peak=CONFIG["LOW_THRESHOLD"])
        
    def get_both_assets(self) -> bool:
        """单次请求获取两个资产数据，带缓存"""
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
        """统一解析资产数据"""
        return {
            "mark": float(item["mark_price"]),
            "bid_1k": float(item["quotes"]["size_1k"]["bid"]),
            "ask_1k": float(item["quotes"]["size_1k"]["ask"]),
        }
    
    def calculate_spreads(self) -> Optional[dict]:
        """计算各类价差"""
        if not self.cache.paxg or not self.cache.xaut:
            return None
            
        paxg, xaut = self.cache.paxg, self.cache.xaut
        
        return {
            "mark": paxg["mark"] - xaut["mark"],
            "short": paxg["bid_1k"] - xaut["ask_1k"],  # 做空PAXG
            "long": paxg["ask_1k"] - xaut["bid_1k"],   # 做多PAXG
        }
    
    @staticmethod
    def calculate_gear(value: float) -> float:
        """计算档位（0.5步长）"""
        return int(value * 2) / 2
    
    def check_threshold(
        self, 
        spreads: dict,
        state: SpreadState,
        threshold: float,
        is_high: bool
    ) -> None:
        """统一阈值检查逻辑"""
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
            current_gear >= (state.last_gear or -999) + CONFIG["GEAR_STEP"] 
            if is_high 
            else current_gear <= (state.last_gear or 999) - CONFIG["GEAR_STEP"]
        )
        
        if not step_check:
            return
        
        # 启动/更新计时器
        if current_gear not in state.timers:
            state.timers[current_gear] = time.time()
            logger.info(f"  档位 {current_gear:.1f} 开始计时")
        
        # 检查持续时间
        if time.time() - state.timers[current_gear] >= CONFIG["DURATION_SEC"]:
            state.peak = mark_spread
            state.last_gear = current_gear
            
            # 生成消息
            action = "做空PAXG@市价，做多XAUT@市价" if is_high else "做多PAXG@市价，做空XAUT@市价"
            emoji = "🔴" if is_high else "🔵"
            
            msg = (
                f"{emoji} PAXG {'新高' if is_high else '新低'}溢价 {'≥16' if is_high else '≤10'}！\n"
                f"真实成交价差: {directional_spread:.2f}\n"
                f"（{action}）\n"
                f"Mark参考: {mark_spread:.2f}"
            )
            
            self.send_message(msg)
            logger.info(f"  ✅ 报警发送: 档位 {current_gear:.1f}")
            state.clear_timers()
    
    def send_message(self, msg: str) -> None:
        """发送消息，带错误处理"""
        try:
            self.bot.send_message(chat_id=self.chat_id, text=msg)
        except Exception as e:
            logger.error(f"Telegram发送失败: {e}")
    
    def run(self) -> None:
        """主循环"""
        logger.info("监控服务启动")
        self.send_message("✅ 优化版监控已启动 (缓存+重试+日志)")
        
        while True:
            try:
                if self.get_both_assets():
                    spreads = self.calculate_spreads()
                    if spreads:
                        # 打印简洁状态
                        gear = self.calculate_gear(spreads["mark"])
                        logger.info(
                            f"{dt.datetime.now():%H:%M:%S}  "
                            f"Mark={spreads['mark']:.2f}  "
                            f"档位={gear:.1f}"
                        )
                        
                        # 检查两个方向
                        self.check_threshold(spreads, self.high_state, CONFIG["HIGH_THRESHOLD"], True)
                        self.check_threshold(spreads, self.low_state, CONFIG["LOW_THRESHOLD"], False)
                
            except Exception as e:
                logger.exception(f"主循环异常: {e}")
            
            time.sleep(CONFIG["CHECK_SEC"])


def validate_config() -> bool:
    """环境变量预校验"""
    required = ["BOT_TOKEN", "CHAT_ID"]
    
    for var in required:
        if not os.getenv(var):
            logger.error(f"缺少必需的环境变量: {var}")
            return False
    
    # 校验token格式
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
