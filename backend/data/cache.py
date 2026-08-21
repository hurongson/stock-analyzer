"""
本地文件缓存：避免重复请求 akshare 被限流
缓存策略：按天缓存，同一交易日内的数据直接读本地
"""
import os
import json
import pandas as pd
from datetime import datetime
from typing import Optional, Any
from backend.config import Config
from backend.utils.helpers import cache_key, today_str


class DataCache:
    def __init__(self, cache_dir: str = None):
        self.cache_dir = cache_dir or Config.CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_path(self, namespace: str, key: str) -> str:
        return os.path.join(self.cache_dir, namespace, f"{key}_{today_str()}.json")

    def get(self, namespace: str, key: str) -> Optional[Any]:
        path = self._cache_path(namespace, key)
        if not os.path.exists(path):
            return None
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

    def get_dataframe(self, namespace: str, key: str) -> Optional[pd.DataFrame]:
        raw = self.get(namespace, key)
        if raw is None:
            return None
        return pd.DataFrame(raw)

    def set_dataframe(self, namespace: str, key: str, df: pd.DataFrame):
        self.set(namespace, key, df.to_dict(orient="records"))


# 全局单例
cache = DataCache()
