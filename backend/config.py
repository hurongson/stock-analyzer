"""
全局配置管理
从环境变量 / .env 文件读取配置
"""
import os
from dotenv import load_dotenv

# 加载 .env（GitHub Actions 中通过 Secrets 注入环境变量，.env 不存在也不报错）
load_dotenv()


def _get_env(key: str, default: str = "") -> str:
    """
    读取环境变量，空字符串视为未设置，返回默认值。
    解决 GitHub Actions 中未设置的 Secret 会被设为空字符串的问题。
    """
    val = os.getenv(key, "")
    return val if val.strip() != "" else default


class Config:
    # ===== 自选股 =====
    STOCK_LIST = [s.strip() for s in _get_env("STOCK_LIST", "600519,000001").split(",") if s.strip()]

    # ===== LLM =====
    LLM_API_KEY = _get_env("LLM_API_KEY", "")
    LLM_BASE_URL = _get_env("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_MODEL = _get_env("LLM_MODEL", "deepseek-chat")
    ENABLE_LLM = _get_env("ENABLE_LLM", "true").lower() == "true"

    # ===== 飞书 =====
    FEISHU_WEBHOOK_URL = _get_env("FEISHU_WEBHOOK_URL", "")
    FEISHU_SECRET = _get_env("FEISHU_SECRET", "")

    # ===== Tushare（可选）=====
    TUSHARE_TOKEN = _get_env("TUSHARE_TOKEN", "")

    # ===== 选股 =====
    LOW_PRICE_THRESHOLD = float(_get_env("LOW_PRICE_THRESHOLD", "15"))
    SCREENER_MAX_RESULTS = int(_get_env("SCREENER_MAX_RESULTS", "50"))
    SCREENER_UNIVERSE = _get_env("SCREENER_UNIVERSE", "all")

    # ===== 分析 =====
    TECHNICAL_LOOKBACK_DAYS = int(_get_env("TECHNICAL_LOOKBACK_DAYS", "120"))

    # ===== 路径 =====
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    CACHE_DIR = os.path.join(DATA_DIR, "cache")
    REPORT_DIR = os.path.join(DATA_DIR, "reports")

    @classmethod
    def ensure_dirs(cls):
        for d in [cls.DATA_DIR, cls.CACHE_DIR, cls.REPORT_DIR]:
            os.makedirs(d, exist_ok=True)
