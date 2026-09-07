"""
本地文件缓存：避免重复请求 akshare 被限流
缓存策略：按天缓存，同一交易日内的数据直接读本地
"""
import os
import json
import time
import logging
import pandas as pd
from datetime import datetime
from typing import Optional, Any
from backend.config import Config
from backend.utils.helpers import cache_key, today_str

logger = logging.getLogger(__name__)


class DataCache:
    def __init__(self, cache_dir: str = None):
        self.cache_dir = cache_dir or Config.CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_path(self, namespace: str, key: str) -> str:
        return os.path.join(self.cache_dir, namespace, f"{key}_{today_str()}.json")

    def get(self, namespace: str, key: str, max_age_seconds: int = None) -> Optional[Any]:
        """
        获取缓存数据
        Args:
            namespace: 命名空间
            key: 缓存键
            max_age_seconds: 最大缓存时间（秒），如果为None则不检查时间
        """
        path = self._cache_path(namespace, key)
        if not os.path.exists(path):
            return None
        # 检查缓存时间
        if max_age_seconds is not None:
            try:
                mtime = os.path.getmtime(path)
                age = time.time() - mtime
                if age > max_age_seconds:
                    logger.info(f"缓存过期: {namespace}/{key}, 年龄{age:.0f}秒 > {max_age_seconds}秒")
                    return None
            except Exception:
                pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def set(self, namespace: str, key: str, data: Any):
        path = self._cache_path(namespace, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        except Exception:
            pass

    def get_dataframe(self, namespace: str, key: str, max_age_seconds: int = None) -> Optional[pd.DataFrame]:
        raw = self.get(namespace, key, max_age_seconds=max_age_seconds)
        if raw is None:
            return None
        return pd.DataFrame(raw)

    def set_dataframe(self, namespace: str, key: str, df: pd.DataFrame):
        self.set(namespace, key, df.to_dict(orient="records"))


# 全局单例
cache = DataCache()
