#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞价擒牛引擎（对标"竞价擒牛"独立应用）

数据源：新浪（sina）
  - 全市场竞价快照：akshare.stock_zh_a_spot()（新浪）
  - 历史日线：akshare.stock_zh_a_daily()（新浪，sh/sz 前缀）
  - 周线：由日线 resample 成周线

运行时机：交易日 9:25 集合竞价结束后 ~ 9:30 开盘前。
  - 此时快照的"今开"= 竞价开盘价、"成交量"= 集合竞价成交量。
  - 强时效功能，GitHub Actions 的 schedule 延迟不可用，必须用外部准点 cron
    （cron-job.org 等）通过 repository_dispatch 触发，或手动 workflow_dispatch。

输出：
  - 综合擒牛榜（多策略共振 + 透明打分）
  - 各策略分组（竞价擒牛 / 昨日涨停接力 / 上影突破 / 周线二次金叉 / 板块掘金）
  - 导出 Excel、飞书推送、保存 JSON

注意：本模块只做研究优先级排序，不构成投资建议。
"""
import os
import time
import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")
logger = logging.getLogger("auction")

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except Exception as e:  # pragma: no cover
    AKSHARE_AVAILABLE = False
    logger.error(f"akshare 不可用: {e}")


# =============================================================================
# 工具函数
# =============================================================================
def to_sina_symbol(code: str) -> str:
    """6 位代码 -> 新浪符号（sh600000 / sz000001 / sz300001）。"""
    code = str(code).strip()
    # 已经带前缀
    if code[:2].lower() in ("sh", "sz", "bj"):
        return code.lower()
    code = code.zfill(6)
    if code[0] == "6" or code[:3] in ("900",):
        return "sh" + code
    return "sz" + code


def to_plain_code(code: str) -> str:
    """新浪符号 / 任意格式 -> 6 位代码。"""
    code = str(code).strip().lower()
    if code[:2] in ("sh", "sz", "bj"):
        return code[2:]
    return code.zfill(6)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def calc_macd(close: pd.Series):
    """返回 DIF, DEA, MACD 柱。"""
    dif = ema(close, 12) - ema(close, 26)
    dea = ema(dif, 9)
    macd = (dif - dea) * 2
    return dif, dea, macd


def is_auction_window(ts: str) -> bool:
    """快照时间戳是否在竞价窗口（9:25-9:31）。"""
    try:
        hhmm = ts.replace(":", "")[:4]
        return "0925" <= hhmm <= "0931"
    except Exception:
        return False


# =============================================================================
# K 线获取（新浪，并发 + 重试）
# =============================================================================
def fetch_daily(code: str, retries: int = 2) -> Optional[pd.DataFrame]:
    """取日线（新浪，不复权），返回按日期升序的 DataFrame。"""
    sym = to_sina_symbol(code)
    for attempt in range(retries + 1):
        try:
            df = ak.stock_zh_a_daily(symbol=sym, adjust="")
            if df is None or df.empty:
                return None
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            keep = ["date", "open", "high", "low", "close", "volume"]
            for c in keep:
                if c not in df.columns:
                    df[c] = np.nan
            return df[keep + (["amount"] if "amount" in df.columns else [])]
        except Exception as e:
            if attempt == retries:
                return None
            time.sleep(0.6)
    return None


def analyze_kline(code: str, df: pd.DataFrame, open_price: float) -> Optional[Dict]:
    """
    基于日线 + 今日竞价开盘价，计算日线/周线因子。

    今日（竞价日）尚未产生完整日线，用 open_price 作为今日价格参与判断，
    但不把它写入历史成交量（避免污染均线/量能）。
    """
    if df is None or len(df) < 30:
        return None

    hist = df.tail(260).copy()
    close = hist["close"]
    high = hist["high"]
    low = hist["low"]
    vol = hist["volume"]

    # 昨日及之前的均线（用历史收盘）
    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma25 = close.rolling(25).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else close.mean()

    # 今日开盘相对均线
    above_ma5 = open_price >= ma5
    above_ma20 = open_price >= ma20
    above_ma60 = open_price >= ma60
    trend_align = (ma5 >= ma10 >= ma20) and above_ma5 and above_ma20

    # 昨日量（用于竞价量比）
    yest_vol = float(vol.iloc[-1])
    yest_close = float(close.iloc[-1])

    # 近 5 日（不含今日）
    recent = hist.tail(5)
    recent_high = float(recent["high"].max())
    # 上影突破：近 3 日存在明显上影线（上影 > 实体 1.2 倍），且今日开盘突破该上影高点
    upper_break = False
    for i in range(max(0, len(hist) - 3), len(hist)):
        o, h, l, c = (hist["open"].iloc[i], hist["high"].iloc[i],
                      hist["low"].iloc[i], hist["close"].iloc[i])
        body = abs(c - o)
        upper = h - max(o, c)
        if upper > max(body * 1.2, 0.02 * c) and open_price >= h:
            upper_break = True
            break

    # 涨停基因：近 10 日涨停次数（主板 9.8% / 创业板 19.5%）
    pcode = to_plain_code(code)
    is_cyb = pcode[:3] in ("300", "301")
    is_kcb = pcode[:3] == "688"
    zt_thr = 19.5 if (is_cyb or is_kcb) else 9.5
    limit_up_days = 0
    for i in range(1, min(11, len(hist))):
        c0 = close.iloc[i - 1]
        c1 = close.iloc[i]
        if c0 > 0 and (c1 / c0 - 1) * 100 >= zt_thr:
            limit_up_days += 1
    yest_limit_up = False
    if len(hist) >= 2:
        c0 = close.iloc[-2]
        c1 = close.iloc[-1]
        yest_limit_up = c0 > 0 and (c1 / c0 - 1) * 100 >= zt_thr

    # 位置：相对 60 日区间（0=最低 1=最高）
    win = hist.tail(60)
    pos60 = ((open_price - win["low"].min()) /
             max(win["high"].max() - win["low"].min(), 1e-6))
    pos60 = float(min(max(pos60, 0), 1))

    # 周线二次金叉
    weekly_second_cross = False
    try:
        wk = hist.set_index("date").resample("W-FRI").agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}).dropna()
        if len(wk) >= 35:
            wdif, wdea, _ = calc_macd(wk["close"])
            cross = (wdif > wdea) & (wdif.shift(1) <= wdea.shift(1))
            cross_idx = list(np.where(cross.values)[0])
            if len(cross_idx) >= 2:
                last_cross = cross_idx[-1]
                # 第二次金叉在零轴附近/上方（DIF > -0.05*close）
                if wdif.iloc[last_cross] > -0.02 * wk["close"].iloc[last_cross]:
                    weekly_second_cross = True
    except Exception:
        weekly_second_cross = False

    return {
        "yest_vol": yest_vol,
        "yest_close": yest_close,
        "ma5": round(float(ma5), 3),
        "ma10": round(float(ma10), 3),
        "ma20": round(float(ma20), 3),
        "ma25": round(float(ma25), 3),
        "ma60": round(float(ma60), 3),
        "above_ma5": bool(above_ma5),
        "above_ma20": bool(above_ma20),
        "above_ma60": bool(above_ma60),
        "trend_align": bool(trend_align),
        "upper_break": bool(upper_break),
        "recent_high": round(recent_high, 3),
        "limit_up_days": int(limit_up_days),
        "yest_limit_up": bool(yest_limit_up),
        "pos60": round(pos60, 3),
        "weekly_second_cross": bool(weekly_second_cross),
    }


# =============================================================================
# 主类
# =============================================================================
class AuctionScreener:
    # 竞价参数（可按回测调整）
    OPEN_MIN = 1.0          # 竞价涨幅下限（%）
    OPEN_STRONG_MIN = 2.0   # 强势下限
    OPEN_MAX = 7.0          # 竞价涨幅上限（高开太多易被砸）
    AUCTION_VOL_MIN = 2.0   # 竞价量占昨日量下限（%）
    PRICE_MIN = 2.0
    PRICE_MAX = 10.0
    DEEP_TOP_N = 60         # 进入深度分析的最大只数
    MIN_SCORE = 55          # 综合擒牛榜最低分

    def __init__(self):
        self.snapshot_time = None
        self.in_auction_window = False

    # ------------------------------------------------------------------
    # 1. 全市场竞价快照
    # ------------------------------------------------------------------
    def get_snapshot(self) -> Optional[pd.DataFrame]:
        if not AKSHARE_AVAILABLE:
            logger.error("akshare 不可用，无法获取竞价快照")
            return None
        for attempt in range(3):
            try:
                df = ak.stock_zh_a_spot()
                if df is not None and not df.empty:
                    ts = str(df["时间戳"].iloc[0])
                    self.snapshot_time = ts
                    self.in_auction_window = is_auction_window(ts)
                    logger.info(f"竞价快照 {len(df)} 行，时间 {ts}，"
                                f"竞价窗口={self.in_auction_window}")
                    return df
            except Exception as e:
                logger.warning(f"获取竞价快照失败({attempt+1}): {str(e)[:80]}")
                time.sleep(1.2)
        return None

    # ------------------------------------------------------------------
    # 2. 初筛 universe + 竞价因子
    # ------------------------------------------------------------------
    def build_candidates(self, df: pd.DataFrame) -> List[Dict]:
        cands = []
        for _, r in df.iterrows():
            code = to_plain_code(r["代码"])
            name = str(r["名称"])
            # 排除北交所（沪深为主）
            if str(r["代码"]).lower().startswith("bj"):
                continue
            # 排除 ST / 退市
            if "ST" in name.upper() or "退" in name:
                continue
            try:
                open_p = float(r["今开"])
                yest = float(r["昨收"])
                price = float(r["最新价"])
                vol = float(r["成交量"])
                amount = float(r["成交额"])
            except Exception:
                continue
            # 停牌 / 无竞价
            if open_p <= 0 or yest <= 0 or vol <= 0:
                continue
            # 价格区间（用户偏好）
            if not (self.PRICE_MIN <= price <= self.PRICE_MAX):
                continue
            open_pct = (open_p / yest - 1) * 100
            # 竞价涨幅区间（高开有强度但不追高）
            if not (self.OPEN_MIN <= open_pct <= self.OPEN_MAX):
                continue
            cands.append({
                "code": code,
                "name": name,
                "price": round(price, 2),
                "open_price": round(open_p, 2),
                "yest_close": round(yest, 2),
                "open_pct": round(open_pct, 2),
                "auction_vol": vol,
                "auction_amount": round(amount, 0),
                # 竞价量占昨日量比例，待日线补 yest_vol 后计算
                "auction_vol_ratio": None,
            })
        # 按竞价强度（涨幅 + 竞价额）粗排
        cands.sort(key=lambda x: (x["open_pct"], x["auction_amount"]),
                   reverse=True)
        logger.info(f"初筛通过（高开{self.OPEN_MIN}-{self.OPEN_MAX}%、"
                    f"价{self.PRICE_MIN}-{self.PRICE_MAX}）：{len(cands)} 只")
        return cands

    # ------------------------------------------------------------------
    # 3. 深度分析（并发取日线）
    # ------------------------------------------------------------------
    def deep_analyze(self, cands: List[Dict]) -> List[Dict]:
        top = cands[:self.DEEP_TOP_N]
        logger.info(f"对前 {len(top)} 只并发取日线做深度分析…")
        klines: Dict[str, pd.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(fetch_daily, c["code"]): c["code"]
                    for c in top}
            for f in as_completed(futs):
                code = futs[f]
                try:
                    klines[code] = f.result()
                except Exception:
                    klines[code] = None
        enriched = []
        for c in top:
            fac = analyze_kline(c["code"], klines.get(c["code"]),
                                c["open_price"])
            if fac is None:
                continue
            c["fac"] = fac
            # 竞价量比（竞价量 / 昨日全天量）。
            # 仅在真实竞价窗口（9:25-9:31）有效；非竞价窗口快照成交量是
            # 全天/盘中量，量比会失真，必须停用，避免误判"放量"。
            if self.in_auction_window and fac["yest_vol"] > 0:
                c["auction_vol_ratio"] = round(
                    c["auction_vol"] / fac["yest_vol"] * 100, 2)
            else:
                c["auction_vol_ratio"] = None
            enriched.append(c)
        logger.info(f"深度分析成功：{len(enriched)} 只")
        return enriched

    # ------------------------------------------------------------------
    # 4. 板块共振（用行业映射，统计同行业竞价强势数量）
    # ------------------------------------------------------------------
    def sector_clustering(self, cands: List[Dict]) -> Dict[str, int]:
        """返回 {code: 同行业通过初筛只数}。行业映射取 collector。"""
        sector_of: Dict[str, str] = {}
        try:
            from backend.data.collector import data_collector
            industry_map = data_collector.get_industry_map()
            for c in cands:
                sector_of[c["code"]] = industry_map.get(c["code"], "")
        except Exception:
            return {c["code"]: 0 for c in cands}
        count: Dict[str, int] = {}
        for c in cands:
            sec = sector_of.get(c["code"], "")
            count[sec] = count.get(sec, 0) + 1
        return {c["code"]: count.get(sector_of.get(c["code"], ""), 0)
                for c in cands}

    # ------------------------------------------------------------------
    # 5. 透明打分（满分 100）
    #    竞价强度 35 + 竞价量能 20 + 日线趋势 20 + 涨停基因 15 + 板块共振 10
    # ------------------------------------------------------------------
    def score_one(self, c: Dict, sector_n: int) -> Dict:
        f = c["fac"]
        # 竞价强度：涨幅 2-5% 最佳，线性映射
        op = c["open_pct"]
        if op < 2:
            s_open = 14 + (op - 1) * 14          # 1-2% -> 14~28
        elif op <= 5:
            s_open = 28 + (op - 2) * (7 / 3)     # 2-5% -> 28~35
        else:
            s_open = 35 - (op - 5) * 4           # 5-7% 回落（高开风险）
        s_open = max(0, min(35, s_open))
        # 竞价量能：竞价量占昨日量 2% 起，8% 满分
        vr = c["auction_vol_ratio"] or 0
        s_vol = max(0, min(20, (vr - 2) / 6 * 20))
        # 日线趋势
        s_trend = 0
        if f["trend_align"]:
            s_trend += 12
        elif f["above_ma5"] and f["above_ma20"]:
            s_trend += 8
        if f["above_ma60"]:
            s_trend += 4
        if f["pos60"] <= 0.85:
            s_trend += 4
        s_trend = min(20, s_trend)
        # 涨停基因
        s_gene = min(15, f["limit_up_days"] * 5 + (6 if f["yest_limit_up"] else 0))
        # 板块共振
        s_sector = min(10, max(0, sector_n - 1) * 5)
        total = round(s_open + s_vol + s_trend + s_gene + s_sector, 1)
        return {
            "score": total,
            "score_detail": {
                "竞价强度": round(s_open, 1),
                "竞价量能": round(s_vol, 1),
                "日线趋势": round(s_trend, 1),
                "涨停基因": round(s_gene, 1),
                "板块共振": round(s_sector, 1),
            },
            "sector_n": sector_n,
        }

    # ------------------------------------------------------------------
    # 6. 策略分组 + 买卖点
    # ------------------------------------------------------------------
    def build_pick(self, c: Dict, prev_regime: str) -> Dict:
        f = c["fac"]
        strategies = []
        # 竞价擒牛：高开 2-6% + 竞价量能达标
        if (self.OPEN_STRONG_MIN <= c["open_pct"] <= 6
                and (c["auction_vol_ratio"] or 0) >= self.AUCTION_VOL_MIN):
            strategies.append("竞价擒牛")
        # 昨日涨停接力
        if f["yest_limit_up"]:
            strategies.append("昨日涨停接力")
        # 上影突破
        if f["upper_break"]:
            strategies.append("上影突破")
        # 周线二次金叉
        if f["weekly_second_cross"]:
            strategies.append("周线二次金叉")
        # 板块掘金：同行业 >=2 只
        if c.get("sector_n", 0) >= 2:
            strategies.append("板块掘金")

        buy = c["open_price"]
        # 竞价高开、昨日退潮时，要求更严，止损更紧
        stop = round(buy * 0.97, 2)
        if f["yest_close"] > 0 and f["yest_close"] < stop:
            stop = round(f["yest_close"] * 0.99, 2)
        target1 = round(buy * 1.05, 2)
        target2 = round(buy * 1.10, 2)
        rr = round((target1 - buy) / max(buy - stop, 1e-6), 2)

        reasons = []
        if c["open_pct"] >= 2:
            reasons.append(f"竞价高开 {c['open_pct']}%，资金抢筹")
        if (c["auction_vol_ratio"] or 0) >= 4:
            reasons.append(f"竞价量达昨日 {c['auction_vol_ratio']}%，明显放量")
        if f["trend_align"]:
            reasons.append("均线多头排列，趋势向上")
        if f["yest_limit_up"]:
            reasons.append("昨日涨停，具备龙头基因")
        if f["weekly_second_cross"]:
            reasons.append("周线 MACD 二次金叉，主升启动")
        if c.get("sector_n", 0) >= 2:
            reasons.append(f"同板块 {c['sector_n']} 只竞价强势，板块共振")
        risks = []
        if c["open_pct"] > 5.5:
            risks.append("高开偏多，开盘易被砸")
        if c["auction_vol_ratio"] is None:
            risks.append("非竞价窗口，竞价量能未验证")
        elif c["auction_vol_ratio"] < 3:
            risks.append("竞价量能偏弱，承接不足")
        if prev_regime in ("退潮", "高潮"):
            risks.append(f"昨日情绪{prev_regime}，需弱转强确认")

        return {
            "code": c["code"],
            "name": c["name"],
            "price": buy,
            "buy_price": buy,
            "buy_price_note": "以竞价开盘价附近介入，不追高",
            "sell_price": target1,
            "sell_price_note": "冲高 5% 先止盈",
            "target_price": target2,
            "stop_loss": stop,
            "risk_reward_ratio": rr,
            "score": c["score"],
            "score_detail": c["score_detail"],
            "open_pct": c["open_pct"],
            "auction_vol_ratio": c["auction_vol_ratio"],
            "strategies": strategies,
            "strategy_count": len(strategies),
            "sector_n": c.get("sector_n", 0),
            "analysis": {"reasons": reasons, "risks": risks},
        }

    # ------------------------------------------------------------------
    # 7. 昨日情绪（从已保存的尾盘/复盘数据读取，竞价时当日闸门尚未产生）
    # ------------------------------------------------------------------
    def get_prev_regime(self) -> str:
        try:
            data_dir = os.path.join(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "data")
            files = sorted([f for f in os.listdir(data_dir)
                            if f.startswith("late_day_") and f.endswith(".json")])
            if files:
                import json
                d = json.load(open(os.path.join(data_dir, files[-1])))
                return d.get("market_sentiment", {}).get("risk_regime", "未知")
        except Exception:
            pass
        return "未知"

    # ------------------------------------------------------------------
    # 8. 导出 Excel
    # ------------------------------------------------------------------
    def export_excel(self, picks: List[Dict], path: str):
        rows = []
        for p in picks:
            sd = p["score_detail"]
            rows.append({
                "代码": p["code"], "名称": p["name"],
                "买入价": p["buy_price"], "竞价涨幅%": p["open_pct"],
                "竞价量占昨日%": p["auction_vol_ratio"],
                "命中策略": "、".join(p["strategies"]),
                "策略数": p["strategy_count"],
                "同板块强势数": p["sector_n"],
                "综合评分": p["score"],
                "竞价强度": sd["竞价强度"], "竞价量能": sd["竞价量能"],
                "日线趋势": sd["日线趋势"], "涨停基因": sd["涨停基因"],
                "板块共振": sd["板块共振"],
                "止盈价": p["sell_price"], "目标价": p["target_price"],
                "止损价": p["stop_loss"], "盈亏比": p["risk_reward_ratio"],
                "选中原因": "；".join(p["analysis"]["reasons"]),
                "风险提示": "；".join(p["analysis"]["risks"]),
            })
        df = pd.DataFrame(rows)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="综合擒牛榜", index=False)
            # 各策略单独 sheet
            for sname in ["竞价擒牛", "昨日涨停接力", "上影突破",
                          "周线二次金叉", "板块掘金"]:
                sub = df[df["命中策略"].str.contains(sname)]
                if not sub.empty:
                    sub.to_excel(writer, sheet_name=sname[:28], index=False)
        logger.info(f"Excel 已导出：{path}（{len(df)} 行）")

    # ------------------------------------------------------------------
    # 9. 编排
    # ------------------------------------------------------------------
    def screen(self, export_path: Optional[str] = None) -> Dict:
        t0 = time.time()
        snap = self.get_snapshot()
        if snap is None:
            return {"error": "无法获取竞价快照", "picks": [], "top_picks": []}
        cands = self.build_candidates(snap)
        prev_regime = self.get_prev_regime()
        logger.info(f"昨日情绪：{prev_regime}")

        result = {
            "date": time.strftime("%Y-%m-%d"),
            "snapshot_time": self.snapshot_time,
            "in_auction_window": self.in_auction_window,
            "prev_regime": prev_regime,
            "candidate_count": len(cands),
        }
        if not cands:
            result.update({"picks": [], "top_picks": [],
                           "note": "竞价无符合条件标的（高开/价格/量能不达标）"})
            return result

        enriched = self.deep_analyze(cands)
        sector_map = self.sector_clustering(enriched)

        picks = []
        for c in enriched:
            sc = self.score_one(c, sector_map.get(c["code"], 0))
            c.update(sc)
            pick = self.build_pick(c, prev_regime)
            picks.append(pick)

        # 综合擒牛榜：有命中策略 + 评分达标；多策略共振优先
        # 实时竞价窗口：完整打分（含量能20），阈值 55。
        # 非竞价窗口（回测模式）：量能缺失（满分少20），阈值等比例下调，
        # 仅供学习，不做实时买入推荐。
        live = self.in_auction_window
        threshold = self.MIN_SCORE if live else self.MIN_SCORE - 15
        ranked = sorted(picks,
                        key=lambda x: (x["strategy_count"], x["score"]),
                        reverse=True)
        for p in ranked:
            p["mode"] = "实时竞价" if live else "回测模式"
        top_picks = [p for p in ranked
                     if p["strategies"] and p["score"] >= threshold]

        # 昨日退潮/高潮收紧（仅实时模式）：保留"昨日涨停（弱转强）"或多策略共振。
        # 回测模式不收紧，便于完整观察策略会选出谁。
        if live and prev_regime in ("退潮", "高潮"):
            strict = [p for p in top_picks
                      if ("昨日涨停接力" in p["strategies"])
                      or p["strategy_count"] >= 2]
            logger.info(f"昨日{prev_regime}，竞价收紧：{len(top_picks)} -> "
                        f"{len(strict)} 只")
            top_picks = strict

        # 分组
        groups: Dict[str, List[str]] = {}
        for p in picks:
            for s in p["strategies"]:
                groups.setdefault(s, []).append(p["code"])

        if export_path:
            try:
                self.export_excel(ranked, export_path)
            except Exception as e:
                logger.error(f"导出 Excel 失败：{e}")

        result.update({
            "mode": "实时竞价" if live else "回测模式",
            "picks": ranked,
            "top_picks": top_picks,
            "groups": groups,
            "total_count": len(ranked),
            "top_count": len(top_picks),
            "elapsed": round(time.time() - t0, 1),
        })
        logger.info(f"竞价擒牛完成：候选{len(cands)}、上榜{len(top_picks)}、"
                    f"耗时{result['elapsed']}s")
        return result


auction_screener = AuctionScreener()
