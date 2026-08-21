"""
全局配置管理
从环境变量 / .env 文件读取配置
"""
import os
from dotenv import load_dotenv

# 加载 .env（GitHub Actions 中通过 Secrets 注入环境变量，.env 不存在也不报错）
load_dotenv()


class Config:
    # ===== 自选股 =====
    STOCK_LIST = [s.strip() for s in os.getenv("STOCK_LIST", "600519,000001").split(",") if s.strip()]

    # ===== LLM =====
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
    ENABLE_LLM = os.getenv("ENABLE_LLM", "true").lower() == "true"

    # ===== 飞书 =====
    FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
    FEISHU_SECRET = os.getenv("FEISHU_SECRET", "")

    # ===== Tushare（可选）=====
    TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

    # ===== 选股 =====
    LOW_PRICE_THRESHOLD = float(os.getenv("LOW_PRICE_THRESHOLD", "15"))
    SCREENER_MAX_RESULTS = int(os.getenv("SCREENER_MAX_RESULTS", "50"))
    SCREENER_UNIVERSE = os.getenv("SCREENER_UNIVERSE", "all")

    # ===== 分析 =====
    TECHNICAL_LOOKBACK_DAYS = int(os.getenv("TECHNICAL_LOOKBACK_DAYS", "120"))

    # ===== 路径 =====
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    CACHE_DIR = os.path.join(DATA_DIR, "cache")
    REPORT_DIR = os.path.join(DATA_DIR, "reports")

    @classmethod
    def ensure_dirs(cls):
        for d in [cls.DATA_DIR, cls.CACHE_DIR, cls.REPORT_DIR]:
            os.makedirs(d, exist_ok=True)
