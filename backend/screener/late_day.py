"""
尾盘选股模块（优化版）
每天14:30根据实时数据，推荐当天可买入、次日可卖出的股票
策略：尾盘买入法（T+1短线）
参照公开尾盘选股策略优化：
- 买入价 = 尾盘现价（直接买入，不等回调）
- 卖出价 = 次日冲高3%-5%（止盈目标）
- 止损价 = 买入价下方2%-3%（固定比例止损）
- 选股条件：涨幅2%-6%、量比>1、股价在20日均线之上、非ST
"""
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from backend.data.collector import collector
from backend.analysis.three_locks import three_locks_analyzer
from backend.analysis.trend_analysis import trend_analyzer
from backend.analysis.indicators import (
    calc_sma, calc_trend, calc_macd, calc_kdj, calc_rsi,
    calc_bollinger, calc_volume_analysis, calc_ma_system, calc_momentum
)

logger = logging.getLogger(__name__)


class LateDayScreener:
    """尾盘选股器"""

    def __init__(self):
        self.max_results = 8  # 最多推荐8只

    def screen(self, stock_df: Optional[pd.DataFrame] = None) -> Dict:
        """
        尾盘选股主函数
        返回：{picks: [...], summary: {...}}
        """
        logger.info("开始尾盘选股...")

        # 获取全量股票列表
        if stock_df is None:
            stock_df = collector.get_all_stocks()
        if stock_df is None or stock_df.empty:
            return {"error": "无法获取股票列表", "picks": []}

        logger.info(f"股票池数量: {len(stock_df)}")

        # 第一步：初筛（基于实时行情数据快速过滤）
        candidates = self._initial_filter(stock_df)
        logger.info(f"初筛后剩余: {len(candidates)} 只")
        # 限制候选股票数量，避免运行时间过长（按成交量排序，取前50只）
        # 减少到50只，避免Tushare接口频率超限（50次/分钟）
        if len(candidates) > 50:
            candidates.sort(key=lambda x: x.get("amount", x.get("volume", 0)), reverse=True)
            candidates = candidates[:50]
            logger.info(f"候选股票限制为50只（按成交量排序，避免Tushare频率超限）")

        if not candidates:
            return {"picks": [], "summary": {"total": 0, "filtered": 0}}

        # 第二步：获取实时行情数据，确保使用当日最新数据（多数据源 fallback）
        try:
            import akshare as ak
            import time
            realtime_df = None
            realtime_source = None
            
            # 数据源1: 新浪财经（东方财富接口在部分环境代理失败，新浪更稳定）
            for retry in range(2):
                try:
                    logger.info(f"尝试新浪财经实时行情（第{retry+1}次）...")
                    realtime_df = ak.stock_zh_a_spot()
                    if realtime_df is not None and not realtime_df.empty:
                        realtime_source = "sina"
                        logger.info(f"✅ 新浪财经实时行情获取成功，共{len(realtime_df)}只股票")
                        break
                except Exception as e:
                    logger.warning(f"新浪财经实时行情第{retry+1}次失败: {e}")
                    time.sleep(2)
            
            # 数据源2: 腾讯财经（fallback）
            if realtime_df is None or realtime_df.empty:
                for retry in range(2):
                    try:
                        logger.info(f"尝试腾讯财经实时行情（第{retry+1}次）...")
                        realtime_df = ak.stock_zh_a_spot_tx()
                        if realtime_df is not None and not realtime_df.empty:
                            realtime_source = "tencent"
                            logger.info(f"✅ 腾讯财经实时行情获取成功，共{len(realtime_df)}只股票")
                            break
                    except Exception as e:
                        logger.warning(f"腾讯财经实时行情第{retry+1}次失败: {e}")
                        time.sleep(2)
            
            # 数据源3: 东方财富（最后fallback）
            if realtime_df is None or realtime_df.empty:
                try:
                    logger.info("尝试东方财富实时行情...")
                    realtime_df = ak.stock_zh_a_spot_em()
                    if realtime_df is not None and not realtime_df.empty:
                        realtime_source = "eastmoney"
                        logger.info(f"✅ 东方财富实时行情获取成功，共{len(realtime_df)}只股票")
                except Exception as e:
                    logger.warning(f"东方财富实时行情失败: {e}")
            if realtime_df is not None and not realtime_df.empty:
                realtime_map = {}
                # 根据数据源选择列名映射
                if realtime_source == "sina":
                    # 新浪财经列名：代码、名称、最新价、涨跌幅、成交量、成交额、最高、最低、今开
                    code_col, name_col = "代码", "名称"
                    price_col, pct_col = "最新价", "涨跌幅"
                    vol_col, amt_col = "成交量", "成交额"
                    high_col, low_col, open_col = "最高", "最低", "今开"
                    turnover_col = None  # 新浪财经没有换手率字段
                elif realtime_source == "tencent":
                    # 腾讯财经列名：code, name, hsl(换手率), lb(量比)
                    code_col, name_col = "code", "name"
                    price_col, pct_col = None, None  # 腾讯财经可能没有价格和涨幅
                    vol_col, amt_col = None, None
                    high_col, low_col, open_col = None, None, None
                    turnover_col = "hsl"
                else:
                    # 东方财富列名：代码、名称、最新价、涨跌幅、成交量、成交额、换手率、最高、最低、今开
                    code_col, name_col = "代码", "名称"
                    price_col, pct_col = "最新价", "涨跌幅"
                    vol_col, amt_col = "成交量", "成交额"
                    high_col, low_col, open_col = "最高", "最低", "今开"
                    turnover_col = "换手率"
                
                for _, row in realtime_df.iterrows():
                    code = str(row.get(code_col, "")) if code_col else ""
                    # 统一股票代码格式（去掉前缀如bj/sh/sz）
                    code = code.replace("bj", "").replace("sh", "").replace("sz", "")
                    if code and len(code) == 6:
                        try:
                            price = float(row.get(price_col, 0)) if price_col else 0
                            pct = float(row.get(pct_col, 0)) if pct_col else 0
                            vol = float(row.get(vol_col, 0)) * 100 if vol_col else 0  # 手→股
                            amt = float(row.get(amt_col, 0)) if amt_col else 0
                            turnover = float(row.get(turnover_col, 0)) if turnover_col else 0
                            high = float(row.get(high_col, 0)) if high_col else 0
                            low = float(row.get(low_col, 0)) if low_col else 0
                            open_p = float(row.get(open_col, 0)) if open_col else 0
                            
                            if price > 0:
                                realtime_map[code] = {
                                    "price": price,
                                    "pct_change": pct,
                                    "volume": vol,
                                    "amount": amt,
                                    "turnover": turnover,
                                    "high": high,
                                    "low": low,
                                    "open": open_p,
                                }
                        except (ValueError, TypeError):
                            continue
                # 更新候选股票的实时数据
                updated_count = 0
                for stock in candidates:
                    code = stock["code"]
                    if code in realtime_map:
                        rt = realtime_map[code]
                        if rt["price"] > 0:
                            stock["price"] = rt["price"]
                            stock["pct_change"] = rt["pct_change"]
                            stock["volume"] = rt["volume"]
                            stock["amount"] = rt["amount"]
                            stock["turnover"] = rt["turnover"]
                            stock["high"] = rt["high"]
                            stock["low"] = rt["low"]
                            stock["open"] = rt["open"]
                            updated_count += 1
                logger.info(f"已更新{updated_count}/{len(candidates)}只股票的实时行情数据")
                
                # 更新实时数据后再次过滤涨幅（确保捕捉涨停前夕信号，而非已涨停股票）
                before_count = len(candidates)
                candidates = [s for s in candidates if -5 <= s.get("pct_change", 0) <= 5]
                logger.info(f"实时数据更新后涨幅过滤: {before_count}->{len(candidates)}只（过滤掉涨幅超出-5%到5%的股票）")
                
                # 换手率不做硬过滤（GitHub Actions环境可能获取失败），只在评分中考虑
                logger.info(f"换手率数据: 有{sum(1 for s in candidates if s.get('turnover',0)>0)}只，无{sum(1 for s in candidates if s.get('turnover',0)==0)}只")
            else:
                logger.warning("实时行情获取失败，使用历史数据")
        except Exception as e:
            logger.warning(f"获取实时行情异常，使用历史数据: {e}")

        # 第三步：批量获取K线数据（使用Tushare批量接口，避免频率超限）
        batch_collector = None
        try:
            from backend.data.collector import DataCollector
            batch_collector = DataCollector()
            codes = [stock["code"] for stock in candidates]
            logger.info(f"开始批量获取K线数据: {len(codes)}只股票")
            batch_result = batch_collector.batch_get_daily_kline(codes, days=60)
            logger.info(f"批量获取K线完成: 成功{len(batch_result)}/{len(codes)}只")
        except Exception as e:
            logger.warning(f"批量获取K线失败，将使用单只获取: {e}")

        # 第四步：深度分析（获取K线数据，计算技术指标）
        picks = self._deep_analyze(candidates)
        logger.info(f"尾盘选股完成，共推荐 {len(picks)} 只")

        return {
            "picks": picks,
            "summary": {
                "total_stocks": len(stock_df),
                "initial_filtered": len(candidates),
                "final_picks": len(picks),
            }
        }

    def _initial_filter(self, stock_df: pd.DataFrame) -> List[Dict]:
        """
        初筛：基于实时行情数据快速过滤（两种模式）
        模式A - 温和上涨型：涨幅 1%-5%，量比>1.2
        模式B - 回调反弹型：涨幅 -3%到1%，缩量整理后反弹（回测发现60%涨停股前一天是这种模式）
        通用条件：
        - 价格 2-40元（扩大范围，覆盖低价和中高价）
        - 成交量 > 800万（有流动性）
        - 非ST、非退市
        - 非北交所、非科创板
        """
        candidates = []
        for _, row in stock_df.iterrows():
            try:
                code = str(row.get("code", ""))
                name = str(row.get("name", ""))
                price = float(row.get("price", 0))
                pct_change = float(row.get("pct_change", 0))
                volume = float(row.get("volume", 0))

                # 过滤条件
                if price <= 0 or pct_change == 0:
                    continue
                # 涨幅 -5%到5%（涨停前夕分析460只涨停股发现：60%涨停股涨停前一天涨幅在-3%到3%，横盘整理为主）
                # 只有13.5%涨停股涨停前一天涨幅>7%（已经接近涨停或连板），推荐已涨停股票没有意义
                # 重点捕捉涨停前夕信号：横盘整理(-1%到1%)占23.3%，小幅下跌(-3%到-1%)占19.1%，温和上涨(1%到3%)占18.5%
                if pct_change < -5 or pct_change > 5:
                    continue
                # 价格 2-80元（大规模回测发现：11.5%涨停股价格不在2-50元，扩大覆盖中高价股）
                if price < 2 or price > 80:
                    continue
                # 排除ST和退市
                if "ST" in name or "退" in name or "*" in name:
                    continue
                # 排除北交所（8开头）和科创板（688开头，波动大）
                if code.startswith("8") or code.startswith("4") or code.startswith("688"):
                    continue
                # 排除金融板块（银行、证券、保险）- 回测发现涨停股中金融股仅占1%，但推荐中占50%
                finance_keywords = ["银行", "证券", "保险", "信托", "期货", "金融"]
                if any(kw in name for kw in finance_keywords):
                    continue
                # 排除常见银行股代码
                bank_codes = ["601398", "601939", "601288", "601988", "600036", "601166", 
                              "600000", "601328", "000001", "601818", "600015", "601169",
                              "601009", "002142", "600919", "600926", "601128", "603323",
                              "002807", "002839", "601658", "601601", "601318", "601336",
                              "601628", "601099", "600030", "600837", "600999", "601788",
                              "601211", "600109", "000776", "000166", "600958", "601375"]
                if code in bank_codes:
                    continue

                candidates.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "pct_change": pct_change,
                    "volume": volume,
                })
            except Exception:
                continue

        return candidates

    def _deep_analyze(self, candidates: List[Dict]) -> List[Dict]:
        """
        深度分析：获取K线数据，计算技术指标，评分排序
        买卖点位逻辑（参照公开尾盘买入法）：
        - 买入价 = 尾盘现价（14:30-15:00直接买入）
        - 卖出价 = 次日冲高3%（止盈目标，保守）
        - 目标价 = 次日冲高5%（激进目标）
        - 止损价 = 买入价下方2%（固定比例止损）
        """
        results = []

        for i, stock in enumerate(candidates):
            try:
                code = stock["code"]
                # 获取60天K线数据
                kline = collector.get_daily_kline(code, days=60)
                if kline is None or len(kline) < 20:
                    if i < 5:
                        logger.info(f"K线数据不足 {stock['name']}({code}): kline={'None' if kline is None else len(kline)}天")
                    continue
                
                if i < 3:
                    logger.info(f"K线数据正常 {stock['name']}({code}): {len(kline)}天, 最新收盘{kline['close'].iloc[-1]:.2f}")

                # 用K线数据计算量比（代替换手率，不依赖外部接口）
                try:
                    volume = kline["volume"]
                    if len(volume) >= 6:
                        vol_today = volume.iloc[-1]
                        vol_ma5 = volume.iloc[-6:-1].mean()  # 前5日均量（不含当日）
                        if vol_ma5 > 0:
                            volume_ratio = vol_today / vol_ma5
                            stock["volume_ratio"] = round(volume_ratio, 2)
                            # 用量比估算活跃度（量比>1.5=活跃，>2=非常活跃）
                            if volume_ratio >= 1.5:
                                stock["turnover"] = max(stock.get("turnover", 0), 3.0)  # 估算为活跃
                            elif volume_ratio >= 1.2:
                                stock["turnover"] = max(stock.get("turnover", 0), 2.0)  # 估算为较活跃
                except Exception as e:
                    logger.debug(f"计算量比失败 {code}: {e}")

                # 把当日实时数据合并到K线中（确保技术指标包含当日数据）
                current_price = stock["price"]
                try:
                    today = pd.Timestamp.now().strftime("%Y-%m-%d")
                    # 检查K线最后一天是否是今天
                    last_date = str(kline.index[-1])[:10] if hasattr(kline.index[-1], 'strftime') else str(kline.index[-1])[:10]
                    if last_date != today:
                        # 添加当日实时数据到K线
                        new_row = pd.DataFrame({
                            "open": [stock.get("open", current_price)],
                            "high": [stock.get("high", current_price)],
                            "low": [stock.get("low", current_price)],
                            "close": [current_price],
                            "volume": [stock.get("volume", 0)],
                            "amount": [stock.get("amount", 0)],
                            "pct_chg": [stock.get("pct_change", 0)],
                        }, index=pd.to_datetime([today]))
                        kline = pd.concat([kline, new_row])
                except Exception as e:
                    logger.debug(f"合并当日数据失败 {code}: {e}")

                close = kline["close"]
                high = kline["high"]
                low = kline["low"]
                
                if i < 3:
                    logger.info(f"进入过滤条件 {stock['name']}({code}): close={len(close)}天, 最新={close.iloc[-1]:.2f}")

                # 振幅过滤：>2%（深度回测282只涨停股发现：71.3%振幅>3%，但28.7%<=3%，降低门槛提高覆盖率）
                if len(close) >= 2:
                    prev_close = close.iloc[-2]
                    today_high = high.iloc[-1]
                    today_low = low.iloc[-1]
                    amplitude = (today_high - today_low) / prev_close * 100 if prev_close > 0 else 0
                    stock["amplitude"] = round(amplitude, 2)
                    if amplitude < 2:
                        if i < 5:
                            logger.info(f"振幅过滤 {stock['name']}({code}): 振幅{amplitude:.1f}% < 2%")
                        continue  # 振幅太小，股性不活跃，很难涨停

                # 换手率过滤：>1%（大规模回测460只涨停股发现：95.4%涨停股换手率>1%，保持门槛）
                turnover = stock.get("turnover", 0)
                if turnover <= 0:
                    # 如果没有实时换手率，用量比代替（涨停前夕分析发现：3.3%涨停股量比<0.5，进一步放宽到0.3）
                    volume_ratio = stock.get("volume_ratio", 0)
                    if volume_ratio < 0.3:
                        if i < 5:
                            logger.info(f"量比过滤 {stock['name']}({code}): 量比{volume_ratio:.2f} < 0.3")
                        continue  # 量比太小，股性不活跃
                elif turnover < 1:
                    if i < 5:
                        logger.info(f"换手率过滤 {stock['name']}({code}): 换手率{turnover:.1f}% < 1%")
                    continue  # 换手率太低，股性不活跃

                # 放宽MA20条件：允许股价在20日均线下方10%以内（突破型）
                # 回测发现33.8%涨停股前一天股价不在MA20之上，很多是从下方突破的
                ma20 = calc_sma(close, 20).iloc[-1]
                if current_price < ma20 * 0.9:  # 允许低于MA20不超过10%
                    if i < 5:
                        logger.info(f"MA20过滤 {stock['name']}({code}): 价格{current_price:.2f} < MA20*0.9={ma20*0.9:.2f}")
                    continue

                # 计算技术指标
                score, analysis = self._calc_late_day_score(kline, stock)
                
                # 调试日志：输出每只股票的评分情况
                if i < 10 or score >= 60:
                    logger.info(f"评分调试 {stock['name']}({code}): 涨幅{stock.get('pct_change', 0):.1f}%, 价格{current_price}, 评分{score}, 理由{analysis.get('reasons', [])[:3]}")

                # 去掉量能硬过滤：回测发现46.3%涨停股前一天不满足连续放量条件
                # 很多是缩量整理后突然放量涨停，量能只在评分中考虑
                # 连续放量过滤已移除，改为评分项

                # 只保留评分>=70的（更严格，提高胜率）
                if score >= 70:
                    # === 买卖点位计算（优化：更合理的盈亏比）===
                    # 买入价 = 尾盘现价（14:30-15:00直接买入）
                    buy_price = round(current_price, 2)
                    buy_price_note = "尾盘现价买入"

                    # 卖出价 = 次日冲高5%（优化止盈目标，提高收益）
                    target_3pct = round(current_price * 1.03, 2)
                    target_5pct = round(current_price * 1.05, 2)
                    target_8pct = round(current_price * 1.08, 2)
                    sell_price = target_5pct
                    sell_price_note = "次日冲高5%止盈"
                    target_price = target_8pct

                    # 止损价 = 买入价下方3%（优化：稍微放宽止损，避免被洗出）
                    stop_loss = round(current_price * 0.97, 2)
                    stop_loss_note = "跌破3%止损"

                    # 盈亏比 = (目标价-买入价)/(买入价-止损价)
                    risk_reward_ratio = round((target_price - buy_price) / (buy_price - stop_loss), 2) if buy_price > stop_loss else None

                    # 次日卖出策略
                    sell_strategy = self._get_sell_strategy(buy_price, target_3pct, target_5pct, stop_loss)

                    # 三把锁分析
                    try:
                        quote = {"price": stock["price"], "pct_change": stock["pct_change"]}
                        three_locks = three_locks_analyzer.analyze(kline, quote)
                    except Exception:
                        three_locks = None

                    # 走势分析
                    try:
                        trend_analysis = trend_analyzer.analyze(kline, quote)
                    except Exception:
                        trend_analysis = None

                    # 将三把锁得分融入总评分（统一评分标准）
                    tl_score = 0
                    if three_locks:
                        total_locked = three_locks.get("total_locked", 0)
                        tl_avg = (three_locks.get("trend_lock",{}).get("score",0) + 
                                  three_locks.get("activity_lock",{}).get("score",0) + 
                                  three_locks.get("capital_lock",{}).get("score",0)) / 3
                        # 三把锁权重：全亮+20分，两亮+10分，一亮0分，零亮-10分
                        tl_bonus = {3: 20, 2: 10, 1: 0, 0: -10}.get(total_locked, 0)
                        tl_score = int(tl_avg * 0.3 + tl_bonus)  # 三把锁占30%权重
                    
                    final_score = min(100, int(score * 0.7 + tl_score))  # 原评分占70%，三把锁占30%

                    result = {
                        "code": code,
                        "name": stock["name"],
                        "price": stock["price"],
                        "pct_change": stock["pct_change"],
                        "score": final_score,
                        "base_score": score,
                        "three_locks_score": tl_score,
                        "pattern": analysis.get("pattern", "未知"),
                        "volume_ratio": stock.get("volume_ratio", 0),
                        "turnover": stock.get("turnover", 0),
                        "amplitude": stock.get("amplitude", 0),
                        "analysis": analysis,
                        "buy_price": buy_price,
                        "buy_price_note": buy_price_note,
                        "sell_price": sell_price,
                        "sell_price_note": sell_price_note,
                        "stop_loss": stop_loss,
                        "stop_loss_note": stop_loss_note,
                        "target_price": target_price,
                        "risk_reward_ratio": risk_reward_ratio,
                        "sell_strategy": sell_strategy,
                        "ma20": round(ma20, 2),
                        "three_locks": three_locks,
                        "trend_analysis": trend_analysis,
                    }
                    results.append(result)

            except Exception as e:
                logger.info(f"分析失败 {stock.get('code')} {stock.get('name', '')}: {e}")
                import traceback
                logger.info(traceback.format_exc()[:500])
                continue

        # 排序：优先按三把锁点亮数，再按综合评分（确保推荐股票与三把锁一致）
        def sort_key(x):
            tl = x.get("three_locks", {})
            locked = tl.get("total_locked", 0) if tl else 0
            return (locked, x["score"])
        results.sort(key=sort_key, reverse=True)
        return results[:self.max_results]

    def _get_sell_strategy(self, buy_price: float, target_3pct: float, target_5pct: float, stop_loss: float) -> Dict:
        """
        次日卖出策略（参照公开尾盘买入法）
        """
        return {
            "time": "次日9:30-10:30（早盘半小时内必须卖出）",
            "take_profit_1": f"高开3%以上：开盘5分钟不涨停直接卖出（{target_3pct}元）",
            "take_profit_2": f"平开/小幅高开：冲高3%-5%分批卖出（{target_3pct}-{target_5pct}元）",
            "take_profit_3": "涨停封死：可持有到第三天，跌破分时线再卖",
            "stop_loss_1": f"低开：开盘15分钟内无法翻红，果断止损（{stop_loss}元）",
            "stop_loss_2": f"跌破昨日收盘价：立即卖出（{buy_price}元）",
            "stop_loss_3": f"亏损达到2%：无条件止损（{stop_loss}元）",
            "core_rule": "无论盈亏，次日10:30前必卖，绝不延长持仓",
        }

    def _calc_late_day_score(self, kline: pd.DataFrame, stock: Dict) -> tuple:
        """
        计算尾盘选股评分（0-100）
        维度：涨幅、成交量、趋势、MACD、KDJ、价格、动量、20日均线
        """
        close = kline["close"]
        high = kline["high"]
        low = kline["low"]
        volume = kline["volume"]
        current_price = stock["price"]
        pct_change = stock["pct_change"]

        score = 50  # 基准分
        reasons = []
        risks = []
        vol_ratio = 0
        trend_name = "未知"

        # 1. 涨幅评分（15%）- 基于涨停前夕分析优化（460只涨停股）
        # 涨停前夕特征：60%涨幅在-3%到3%，横盘整理(-1%到1%)占23.3%最多
        # 只有13.5%涨幅>7%（已接近涨停），推荐已涨停股票没有意义
        pattern = "未知"
        if -1 <= pct_change < 1:
            score += 15  # 横盘整理最多，给最高分
            reasons.append(f"横盘整理({pct_change:.1f}%)，蓄势待发可能突破涨停")
            pattern = "横盘突破型"
        elif -3 <= pct_change < -1:
            score += 14  # 小幅回调，次高分
            reasons.append(f"缩量回调({pct_change:.1f}%)，洗盘后反弹概率高")
            pattern = "回调反弹型"
        elif 1 <= pct_change <= 3:
            score += 13  # 温和上涨，第三高分
            reasons.append(f"温和上涨({pct_change:.1f}%)，稳步推升可能涨停")
            pattern = "温和上涨型"
        elif -5 <= pct_change < -3:
            score += 11  # 大跌反弹，一定分数
            reasons.append(f"大跌反弹({pct_change:.1f}%)，超跌反弹概率高")
            pattern = "超跌反弹型"
        elif 3 < pct_change <= 5:
            score += 8  # 涨幅较大，较低分（只有5.4%涨停股属于此区间）
            reasons.append(f"涨幅尚可({pct_change:.1f}%)，注意追高风险")
            pattern = "温和上涨型"
        else:
            risks.append("涨幅异常")

        # 2. 成交量评分（20%）- 基于涨停前夕分析优化
        # 涨停前夕特征：23.5%量比0.5-0.8（缩量整理），29.6%量比1.0-1.5（温和放量）
        # 缩量整理后突然放量涨停是常见模式，不应对缩量扣分太多
        try:
            vol = calc_volume_analysis(volume, close)
            vol_ratio = vol["volume_ratio"]
            vp = vol.get("volume_price", "")
            if "放量上涨" in vp:
                score += 18
                reasons.append(f"放量上涨(量比{vol_ratio:.1f})，资金入场")
            elif vol_ratio > 1.5:
                score += 14
                reasons.append(f"成交量明显放大(量比{vol_ratio:.1f})，资金关注")
            elif vol_ratio > 1.2:
                score += 10
                reasons.append(f"成交量温和放大(量比{vol_ratio:.1f})")
            elif 0.8 <= vol_ratio <= 1.2:
                score += 8
                reasons.append(f"成交量平稳(量比{vol_ratio:.1f})，蓄势整理")
            elif 0.5 <= vol_ratio < 0.8:
                score += 5  # 缩量整理不扣分，反而给一定分数（洗盘特征）
                reasons.append(f"缩量整理(量比{vol_ratio:.1f})，洗盘后可能放量涨停")
            elif vol_ratio < 0.5:
                score -= 3  # 极度缩量才少量扣分
                risks.append("成交量极度萎缩，需关注是否有资金关注")
        except Exception:
            pass

        # 2.5 振幅评分（5分）- 深度回测发现：振幅大的股票更容易涨停
        amplitude = stock.get("amplitude", 0)
        if amplitude >= 5:
            score += 5
            reasons.append(f"振幅大({amplitude:.1f}%)，股性活跃")
        elif amplitude >= 3:
            score += 3
            reasons.append(f"振幅适中({amplitude:.1f}%)")
        elif amplitude >= 2:
            score += 1
            reasons.append(f"振幅较小({amplitude:.1f}%)")

        # 2.6 换手率评分（5分）- 深度回测发现：换手率高的股票更容易涨停
        turnover = stock.get("turnover", 0)
        if turnover >= 5:
            score += 5
            reasons.append(f"换手率高({turnover:.1f}%)，资金关注度高")
        elif turnover >= 3:
            score += 3
            reasons.append(f"换手率适中({turnover:.1f}%)")
        elif turnover >= 1:
            score += 1
            reasons.append(f"换手率较低({turnover:.1f}%)")

        # 2.7 均线多头排列评分（5分）- 深度回测发现：40.1%涨停股均线多头排列
        try:
            ma5 = calc_sma(close, 5).iloc[-1]
            ma10 = calc_sma(close, 10).iloc[-1]
            ma20_score = calc_sma(close, 20).iloc[-1]
            if ma5 > ma10 > ma20_score:
                score += 5
                reasons.append("均线多头排列，趋势强势")
            elif ma5 > ma10:
                score += 2
                reasons.append("短期均线向上")
        except Exception:
            pass

        # 3. 趋势评分（20%）
        try:
            trend = calc_trend(close)
            trend_score = trend["trend_score"]
            trend_name = trend["trend"]
            if trend_score >= 75:
                score += 15
                reasons.append(f"{trend['trend']}，趋势向好")
            elif trend_score >= 60:
                score += 8
                reasons.append(f"{trend['trend']}")
            elif trend_score <= 35:
                score -= 10
                risks.append(f"{trend['trend']}，趋势偏弱")
        except Exception:
            pass

        # 4. MACD评分（15%）
        try:
            macd = calc_macd(close)
            if macd.get("golden_cross"):
                score += 12
                reasons.append("MACD金叉，短期动能转强")
            elif macd["dif"] > macd["dea"] and macd["dif"] > 0:
                score += 8
                reasons.append("MACD多头排列")
            elif macd.get("death_cross"):
                score -= 8
                risks.append("MACD死叉，短期动能转弱")
        except Exception:
            pass

        # 5. KDJ评分（10%）
        try:
            kdj = calc_kdj(high, low, close)
            k_val = kdj.get("k", 50)
            if kdj.get("golden_cross") and k_val < 50:
                score += 8
                reasons.append("KDJ金叉，低位启动")
            elif 30 <= k_val <= 70:
                score += 3
            elif k_val > 85:
                score -= 5
                risks.append("KDJ超买，次日可能回调")
        except Exception:
            pass

        # 6. 价格评分（10%）
        if current_price < 5:
            score += 8
            reasons.append(f"低价股({current_price}元)，容易次日冲高")
        elif current_price < 10:
            score += 5
            reasons.append(f"中低价股({current_price}元)")
        elif current_price > 20:
            score -= 3

        # 6.5 消息面评分（10%）- 结合时事新闻、政策消息、公司公告
        try:
            from backend.analysis.news_analyzer import news_analyzer
            news_impact = news_analyzer.get_news_impact_score(code, name)
            news_score = news_impact.get("score", 50)
            news_level = news_impact.get("level", "中性")
            if news_score >= 70:
                score += 10
                reasons.append(f"消息面利好({news_level})，有正面催化")
            elif news_score >= 60:
                score += 6
                reasons.append(f"消息面偏利好({news_level})")
            elif news_score <= 30:
                score -= 8
                risks.append(f"消息面利空({news_level})，需谨慎")
            elif news_score <= 40:
                score -= 4
                risks.append(f"消息面偏利空({news_level})")
            stock["news_impact"] = news_impact
        except Exception as e:
            logger.debug(f"消息面分析失败 {code}: {e}")

        # 7. 动量评分（10%）
        try:
            mom = calc_momentum(close)
            roc5 = mom.get("roc5")
            if roc5 and 2 <= roc5 <= 10:
                score += 6
                reasons.append(f"5日动量适中(+{roc5:.1f}%)")
            elif roc5 and roc5 > 15:
                score -= 3
                risks.append("短期涨幅过大，可能回调")
        except Exception:
            pass

        score = max(0, min(100, round(score)))

        analysis = {
            "reasons": reasons,
            "risks": risks,
            "trend": trend_name,
            "volume_ratio": vol_ratio,
            "pattern": pattern,
        }

        return score, analysis


# 全局单例
late_day_screener = LateDayScreener()
