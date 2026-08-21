"""
选股策略基类
"""
from abc import ABC, abstractmethod
from typing import List, Dict
import pandas as pd


class BaseStrategy(ABC):
    """选股策略基类"""

    name: str = "base"
    description: str = "基础策略"

    @abstractmethod
    def screen(self, df: pd.DataFrame, **kwargs) -> List[Dict]:
        """
        从股票列表中筛选符合条件的股票
        :param df: 全量股票数据 DataFrame（来自 get_all_stocks）
        :return: 符合条件的股票列表，每项包含 code/name/price/reason/score
        """
        pass

    def _make_result(self, row: pd.Series, reason: str, score: int) -> Dict:
        return {
            "code": row.get("code", ""),
            "name": row.get("name", ""),
            "price": row.get("price", 0),
            "pct_change": row.get("pct_change", 0),
            "strategy": self.name,
            "reason": reason,
            "score": score,
        }
