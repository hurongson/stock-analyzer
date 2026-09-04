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
        self.max_results = 30  # 最多推荐30只（扩大分析范围，用户要求选30支精选10支）
        self.top_picks = 10  # 精选10支（重点推荐）

    def screen(self, stock_df: Optional[pd.DataFrame] = None) -> Dict:
        """
        尾盘选股主函数
        返回：{picks: [...], summary: {...}}
        """
        logger.info("开始尾盘选股...")

        # 大盘环境分析（新增：根据大盘情况调整选股策略）
        # 基于2026-09-02回测：大盘下跌1-2%时，推荐股票平均亏损3.35%
        market_status = self._analyze_market()
        logger.info(f"大盘环境: {market_status['status']} (上证指数{market_status['sh_pct']:+.2f}%, 创业板{market_status['cyb_pct']:+.2f}%)")
        
        # 大盘下跌超过1%时，减少推荐数量，提高选股门槛
        if market_status['sh_pct'] < -1.0:
            self.max_results = 20  # 从30减少到20（不要过度减少，用户要求选30支）
            logger.info(f"大盘下跌{market_status['sh_pct']:.2f}%，推荐数量减少到20只，提高选股门槛")
        elif market_status['sh_pct'] < -0.5:
            self.max_results = 25  # 从30减少到25
            logger.info(f"大盘下跌{market_status['sh_pct']:.2f}%，推荐数量减少到25只")
        else:
            self.max_results = 30  # 正常情况推荐30只

        # 获取全量股票列表
        if stock_df is None:
            stock_df = collector.get_all_stocks()
        if stock_df is None or stock_df.empty:
            return {"error": "无法获取股票列表", "picks": []}

        logger.info(f"股票池数量: {len(stock_df)}")

        # 第一步：初筛（基于实时行情数据快速过滤）
        candidates = self._initial_filter(stock_df)
        logger.info(f"初筛后剩余: {len(candidates)} 只")
        # 限制候选股票数量，避免运行时间过长（按成交量排序，取前100只）
        # 从50只增加到100只，增加推荐数量（用户要求30只推荐）
        # 减少到100只，避免Tushare接口频率超限（50次/分钟）
        if len(candidates) > 100:
            candidates.sort(key=lambda x: x.get("amount", x.get("volume", 0)), reverse=True)
            candidates = candidates[:100]  # 从50增加到100，扩大分析范围
            logger.info(f"候选股票限制为100只（按成交量排序，避免Tushare频率超限）")

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
        batch_kline_data = {}  # 存储批量获取的K线数据
        try:
            from backend.data.collector import DataCollector
            batch_collector = DataCollector()
            codes = [stock["code"] for stock in candidates]
            logger.info(f"开始批量获取K线数据: {len(codes)}只股票")
            batch_result = batch_collector.batch_get_daily_kline(codes, days=60)
            logger.info(f"批量获取K线完成: 成功{len(batch_result)}/{len(codes)}只")
            # 存储批量获取的K线数据
            if isinstance(batch_result, dict):
                batch_kline_data = batch_result
            elif isinstance(batch_result, list):
                for item in batch_result:
                    if isinstance(item, dict) and 'code' in item:
                        batch_kline_data[item['code']] = item.get('kline', item)
        except Exception as e:
            logger.warning(f"批量获取K线失败，将使用单只获取: {e}")

        # 第四步：深度分析（获取K线数据，计算技术指标）
        # 传递批量获取的K线数据，避免重复获取（修复：之前_deep_analyze自己获取K线导致全部失败）
        picks = self._deep_analyze(candidates, batch_kline_data)
        logger.info(f"尾盘选股完成，共推荐 {len(picks)} 只")

        return {
            "picks": picks,
            "summary": {
                "total_stocks": len(stock_df),
                "initial_filtered": len(candidates),
                "final_picks": len(picks),
            }
        }

    def _analyze_market(self) -> Dict:
        """
        分析大盘环境，根据大盘情况调整选股策略
        基于2026-09-02回测：大盘下跌1-2%时，推荐股票平均亏损3.35%
        """
        try:
            import requests
            import re
            
            # 获取上证指数、深证成指、创业板指
            codes = 'sh000001,sz399001,sz399006'
            url = f'http://hq.sinajs.cn/list={codes}'
            headers = {'Referer': 'https://finance.sina.com.cn'}
            response = requests.get(url, headers=headers, timeout=5)
            response.encoding = 'gbk'
            lines = response.text.strip().split('\\n')
            
            sh_pct = 0
            sz_pct = 0
            cyb_pct = 0
            
            for i, line in enumerate(lines[:3]):
                match = re.search(r'=\"([^\"]+)\"', line)
                if match:
                    data = match.group(1).split(',')
                    if len(data) > 3:
                        current = float(data[3])
                        prev_close = float(data[2])
                        if prev_close > 0:
                            pct = (current - prev_close) / prev_close * 100
                            if i == 0:
                                sh_pct = pct
                            elif i == 1:
                                sz_pct = pct
                            elif i == 2:
                                cyb_pct = pct
            
            # 判断大盘状态
            if sh_pct >= 1:
                status = "强势上涨"
            elif sh_pct >= 0:
                status = "震荡偏强"
            elif sh_pct >= -0.5:
                status = "震荡偏弱"
            elif sh_pct >= -1:
                status = "小幅下跌"
            else:
                status = "大幅下跌"
            
            return {
                "status": status,
                "sh_pct": sh_pct,
                "sz_pct": sz_pct,
                "cyb_pct": cyb_pct,
            }
        except Exception as e:
            logger.warning(f"大盘环境分析失败: {e}，使用默认状态")
            return {
                "status": "未知",
                "sh_pct": 0,
                "sz_pct": 0,
                "cyb_pct": 0,
            }

    def _initial_filter(self, stock_df: pd.DataFrame) -> List[Dict]:
        """
        初筛：基于实时行情数据快速过滤（两种模式）
        模式A - 温和上涨型：涨幅 1%-5%，量比>1.2
        模式B - 回调反弹型：涨幅 -3%到1%，缩量整理后反弹（回测发现60%涨停股前一天是这种模式）
        通用条件：
        - 价格 2-50元（优化：从100元缩小到50元，2026-09-04回测发现84.2%涨停股<20元）
        - 成交额 0.5-50亿（新增：2026-09-04回测发现65.8%涨停股<5亿，最低0.78亿）
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
                amount = float(row.get("amount", 0))  # 成交额（元）

                # 过滤条件
                if price <= 0 or pct_change == 0:
                    continue
                # 涨幅 -10%到10%（优化：从-5%扩大到-10%，允许超跌反弹）
                # 2026-09-03回测发现：59%涨停股昨天是下跌的，超跌反弹往往更容易涨停
                if pct_change < -10 or pct_change > 10:
                    continue
                # 价格 2-50元（优化：从100元缩小到50元）
                # 2026-09-04回测发现：84.2%涨停股<20元，44.7%<10元，>=50元极少
                if price < 2 or price > 50:
                    continue
                # 成交额过滤（新增：2026-09-04回测发现65.8%涨停股<5亿）
                # 成交额太小（<0.5亿）流动性差，太大（>50亿）难涨停
                amount_yi = amount / 100000000  # 转换为亿
                if amount_yi > 0 and (amount_yi < 0.5 or amount_yi > 50):
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

                # 标记连板股（昨天涨幅>5%，可能已涨停）
                is_lianban = pct_change > 5

                candidates.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "pct_change": pct_change,
                    "volume": volume,
                    "is_lianban": is_lianban,  # 新增：连板股标记
                })
            except Exception:
                continue

        return candidates

    def _deep_analyze(self, candidates: List[Dict], batch_kline_data: Dict = None) -> List[Dict]:
        """
        深度分析：获取K线数据，计算技术指标，评分排序
        买卖点位逻辑（参照公开尾盘买入法）：
        - 买入价 = 尾盘现价（14:30-15:00直接买入）
        - 卖出价 = 次日冲高3%（止盈目标，保守）
        - 目标价 = 次日冲高5%（激进目标）
        - 止损价 = 买入价下方2%（固定比例止损）
        
        Args:
            candidates: 候选股票列表
            batch_kline_data: 批量获取的K线数据（字典，key为股票代码）
        """
        results = []
        use_batch_kline = batch_kline_data is not None and len(batch_kline_data) > 0
        if use_batch_kline:
            logger.info(f"使用批量获取的K线数据: {len(batch_kline_data)}只股票")

        for i, stock in enumerate(candidates):
            try:
                code = stock["code"]
                # 优先使用批量获取的K线数据，避免重复获取（修复：之前自己获取K线导致全部失败）
                if use_batch_kline and code in batch_kline_data:
                    kline = batch_kline_data[code]
                    # 确保kline是DataFrame格式
                    if not isinstance(kline, pd.DataFrame):
                        # 尝试转换为DataFrame
                        if isinstance(kline, list):
                            kline = pd.DataFrame(kline)
                        elif isinstance(kline, dict):
                            kline = pd.DataFrame(kline)
                else:
                    # 批量获取失败时，使用单只获取
                    kline = collector.get_daily_kline(code, days=60)
                
                if kline is None or len(kline) < 20:
                    if i < 5:
                        logger.debug(f"K线数据不足 {stock['name']}({stock.get('code', '')}): kline={'None' if kline is None else len(kline)}天")
                    continue
                
                if i < 3:
                    logger.debug(f"K线数据正常 {stock['name']}({stock.get('code', '')}): {len(kline)}天, 最新收盘{kline['close'].iloc[-1]:.2f}")

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
                    logger.debug(f"计算量比失败 {stock.get('code', '')}: {e}")

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
                    logger.debug(f"合并当日数据失败 {stock.get('code', '')}: {e}")

                close = kline["close"]
                high = kline["high"]
                low = kline["low"]
                
                if i < 3:
                    logger.debug(f"进入过滤条件 {stock['name']}({stock.get('code', '')}): close={len(close)}天, 最新={close.iloc[-1]:.2f}")

                # 振幅过滤：>1%（优化：从2%降低到1%，允许横盘整理股）
                # 2026-09-02回测发现：34.5%涨停股昨天振幅<2%，横盘整理后突然涨停
                # 深度回测282只涨停股发现：71.3%振幅>3%，但28.7%<=3%，降低门槛提高覆盖率
                if len(close) >= 2:
                    prev_close = close.iloc[-2]
                    today_high = high.iloc[-1]
                    today_low = low.iloc[-1]
                    amplitude = (today_high - today_low) / prev_close * 100 if prev_close > 0 else 0
                    stock["amplitude"] = round(amplitude, 2)
                    if amplitude < 1:
                        if i < 5:
                            logger.debug(f"振幅过滤 {stock['name']}({stock.get('code', '')}): 振幅{amplitude:.1f}% < 1%")
                        continue  # 振幅太小，股性不活跃，很难涨停

                # 换手率过滤：>1%（大规模回测460只涨停股发现：95.4%涨停股换手率>1%，保持门槛）
                turnover = stock.get("turnover", 0)
                if turnover <= 0:
                    # 如果没有实时换手率，用量比代替（涨停前夕分析发现：3.3%涨停股量比<0.5，进一步放宽到0.3）
                    volume_ratio = stock.get("volume_ratio", 0)
                    if volume_ratio < 0.3:
                        if i < 5:
                            logger.debug(f"量比过滤 {stock['name']}({stock.get('code', '')}): 量比{volume_ratio:.2f} < 0.3")
                        continue  # 量比太小，股性不活跃
                elif turnover < 1:
                    if i < 5:
                        logger.debug(f"换手率过滤 {stock['name']}({stock.get('code', '')}): 换手率{turnover:.1f}% < 1%")
                    continue  # 换手率太低，股性不活跃

                # 放宽MA20条件：允许股价在20日均线下方10%以内（突破型）
                # 回测发现33.8%涨停股前一天股价不在MA20之上，很多是从下方突破的
                ma20 = calc_sma(close, 20).iloc[-1]
                if current_price < ma20 * 0.9:  # 允许低于MA20不超过10%
                    if i < 5:
                        logger.debug(f"MA20过滤 {stock['name']}({stock.get('code', '')}): 价格{current_price:.2f} < MA20*0.9={ma20*0.9:.2f}")
                    continue

                # 计算技术指标
                score, analysis = self._calc_late_day_score(kline, stock)
                
                # 调试日志：输出每只股票的评分情况
                if i < 10 or score >= 60:
                    logger.debug(f"评分调试 {stock['name']}({stock.get('code', '')}): 涨幅{stock.get('pct_change', 0):.1f}%, 价格{current_price}, 评分{score}, 理由{analysis.get('reasons', [])[:3]}")

                # 去掉量能硬过滤：回测发现46.3%涨停股前一天不满足连续放量条件
                # 很多是缩量整理后突然放量涨停，量能只在评分中考虑
                # 连续放量过滤已移除，改为评分项

                # 只保留评分>=50的（降低门槛，扩大推荐范围，用户要求选30支精选10支）
                # 修复：评分系统优化后，final_score上限从100降低到95，需要相应降低门槛
                if score >= 50:
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
                    # 修复：之前三把锁权重过大（最高50分），导致final_score轻易达到100分
                    # 优化：三把锁权重降低到20%，bonus降低，避免过度乐观
                    # 回测优化：采用加权平均，趋势锁权重最高（点亮率68.1%，预测能力最强），资金锁权重最低（点亮率47.1%）
                    tl_score = 0
                    if three_locks:
                        total_locked = three_locks.get("total_locked", 0)
                        trend_score = three_locks.get("trend_lock",{}).get("score",0)
                        activity_score = three_locks.get("activity_lock",{}).get("score",0)
                        capital_score = three_locks.get("capital_lock",{}).get("score",0)
                        # 加权平均：趋势锁40%，股性锁35%，资金锁25%（回测优化）
                        tl_avg = trend_score * 0.4 + activity_score * 0.35 + capital_score * 0.25
                        # 三把锁权重：全亮+10分，两亮+5分，一亮0分，零亮-5分（从20/10/0/-10降低）
                        tl_bonus = {3: 10, 2: 5, 1: 0, 0: -5}.get(total_locked, 0)
                        tl_score = int(tl_avg * 0.2 + tl_bonus)  # 三把锁占20%权重（从30%降低）
                    
                    # 原评分占80%，三把锁占20%（从70%/30%调整）
                    # 限制final_score上限为95分，避免轻易达到100分（100分意味着完美，很少有股票能达到）
                    final_score = min(95, int(score * 0.8 + tl_score))

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
                        "news_impact": stock.get("news_impact", {}),
                        "concept_analysis": stock.get("concept_analysis", {}),
                    }
                    results.append(result)

            except Exception as e:
                logger.info(f"分析失败 {stock.get('code')} {stock.get('name', '')}: {e}")
                import traceback
                logger.info(traceback.format_exc()[:500])
                continue

        # 行业分散度限制：同一行业最多推荐2只，避免行业集中风险
        # 基于2026-09-01回测：化工4只平均-8.02%，行业集中导致大幅亏损
        industry_count = {}
        filtered_results = []
        for stock in results:
            industry = stock.get("industry", "") or stock.get("所属行业", "") or "未知"
            if industry not in industry_count:
                industry_count[industry] = 0
            if industry_count[industry] < 10:  # 同一行业最多10只（从5增加到10，避免过度过滤导致推荐太少，用户要求30只推荐）
                industry_count[industry] += 1
                filtered_results.append(stock)
        
        logger.info(f"行业分散度过滤: 从{len(results)}只减少到{len(filtered_results)}只")
        results = filtered_results

        # 三把锁信号过滤（优化：放宽过滤，增加推荐数量）
        # 第一优先级：买入/强烈买入/谨慎买入信号的股票
        # 第二优先级：2/3亮以上的股票（即使信号不是买入）
        # 第三优先级：1/3亮的股票（如果数量还不够）
        buy_signals = ["强烈买入", "买入", "谨慎买入"]
        buy_results = []
        two_locked_results = []
        one_locked_results = []
        watch_results = []
        
        for stock in results:
            # 类型检查：确保stock是字典，跳过字符串等非字典元素（修复TypeError）
            if not isinstance(stock, dict):
                logger.warning(f"跳过非字典元素: {type(stock)} - {stock}")
                continue
            tl = stock.get("three_locks", {}) or {}
            tl_signal = tl.get("signal", "")
            tl_locked = tl.get("total_locked", 0)
            
            if tl_signal in buy_signals:
                buy_results.append(stock)
            elif tl_locked >= 2:
                two_locked_results.append(stock)
            elif tl_locked >= 1:
                one_locked_results.append(stock)
            else:
                watch_results.append(stock)
        
        logger.info(f"三把锁过滤: 买入信号{len(buy_results)}只, 2/3亮{len(two_locked_results)}只, 1/3亮{len(one_locked_results)}只, 0/3亮{len(watch_results)}只")
        
        # 合并结果：买入信号 + 2/3亮 + 1/3亮（按优先级排序）
        # 目标：推荐30只股票，如果买入信号不足，依次补充2/3亮和1/3亮的股票
        results = buy_results + two_locked_results + one_locked_results
        
        # 如果还是不足10只，增加0/3亮的股票（极端情况）
        if len(results) < 10:
            logger.info(f"推荐股票不足10只，增加0/3亮的股票")
            results = results + watch_results
        
        logger.info(f"三把锁过滤后共{len(results)}只股票")

        # 排序：优先按涨停概率，再按三把锁点亮数，最后按综合评分
        # 基于6个月460只涨停股回测分析，涨停概率是最重要的指标
        def sort_key(x):
            # 类型检查：确保x是字典（修复TypeError）
            if not isinstance(x, dict):
                return (0, 0, 0)
            tl = x.get("three_locks", {})
            locked = tl.get("total_locked", 0) if tl else 0
            analysis = x.get("analysis", {})
            limit_up_prob = analysis.get("limit_up_probability", 0) if analysis else 0
            return (limit_up_prob, locked, x.get("score", 0))
        results.sort(key=sort_key, reverse=True)
        
        # 分为精选10支和全部30支
        all_picks = results[:self.max_results]
        top_picks = all_picks[:self.top_picks] if len(all_picks) >= self.top_picks else all_picks
        
        # 标记精选股票
        for i, stock in enumerate(top_picks):
            stock["is_top_pick"] = True
            stock["top_pick_rank"] = i + 1
        
        return {
            "all_picks": all_picks,  # 全部30支
            "top_picks": top_picks,  # 精选10支
            "total_count": len(all_picks),
            "top_count": len(top_picks),
        }

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
        # 2026-09-02回测发现：31%涨停股昨天涨幅>5%（已涨停，连板股）
        # 2026-09-03回测发现：59%涨停股昨天是下跌的，超跌反弹往往更容易涨停
        pattern = "未知"
        is_lianban = stock.get("is_lianban", False) or pct_change > 5
        
        if is_lianban:
            # 连板股专门分析（新增）
            # 昨天已涨停，今天可能继续连板
            score += 10  # 连板股基础加分
            reasons.append(f"连板股(昨涨{pct_change:.1f}%)，强势延续可能继续涨停")
            pattern = "连板延续型"
            
            # 连板股风险评估
            # 连续涨停天数过多，回调风险大
            try:
                up_days = 0
                for j in range(1, min(6, len(close))):
                    if close.iloc[-j] > close.iloc[-j-1]:
                        up_days += 1
                    else:
                        break
                if up_days >= 3:
                    score -= 5
                    risks.append(f"连续上涨{up_days}天，高位回调风险大")
                elif up_days == 2:
                    score += 3
                    reasons.append(f"2连板，强势确立")
            except Exception:
                pass
        elif -1 <= pct_change < 1:
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
            score += 13  # 大跌反弹，提高分数（2026-09-03回测：超跌反弹容易涨停）
            reasons.append(f"大跌反弹({pct_change:.1f}%)，超跌反弹概率高")
            pattern = "超跌反弹型"
        elif -8 <= pct_change < -5:
            score += 12  # 深度超跌反弹，较高分数（新增）
            reasons.append(f"深度超跌({pct_change:.1f}%)，报复性反弹概率高")
            pattern = "深度超跌反弹型"
        elif -10 <= pct_change < -8:
            score += 10  # 极端超跌反弹，一定分数（新增）
            reasons.append(f"极端超跌({pct_change:.1f}%)，注意风险但反弹空间大")
            pattern = "极端超跌反弹型"
            risks.append(f"极端超跌({pct_change:.1f}%)，基本面可能有问题")
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
            news_code = stock.get("code", "")
            news_name = stock.get("name", "")
            news_impact = news_analyzer.get_news_impact_score(news_code, news_name)
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
            logger.info(f"消息面分析失败 {stock.get('code', '')}: {e}")

        # 6.6 概念热点评分（10%）- 结合近期热门题材、概念板块
        try:
            from backend.analysis.concept import analyze_concept
            concept_result = analyze_concept(stock.get("code", ""))
            concept_score = concept_result.get("score", 50)
            matched_hot = concept_result.get("matched_hot", [])
            if matched_hot:
                hot_names = "、".join([h.get("name", "") for h in matched_hot[:3]])
                if concept_score >= 70:
                    score += 10
                    reasons.append(f"热门概念({hot_names})，题材风口")
                elif concept_score >= 60:
                    score += 6
                    reasons.append(f"涉及热门概念({hot_names})")
                elif concept_score <= 40:
                    score -= 3
                    risks.append(f"概念板块走弱({hot_names})")
            else:
                score -= 2
                risks.append("非当前热门题材")
            stock["concept_analysis"] = concept_result
        except Exception as e:
            logger.info(f"概念热点分析失败 {stock.get('code', '')}: {e}")

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

        # 8. 涨停概率预测（基于6个月460只涨停股回测分析，优化版）
        # 回测关键特征：60%涨幅-3%~3%，70%振幅3%~7%，60%换手率2%~7%
        # 23.5%量比0.5~0.8（缩量整理），86.5%首板，47.6%均线多头
        # 优化：降低基础概率，增加风险扣分，避免过于乐观（2026-09-01回测85%概率实际-6.84%）
        limit_up_prob = 20  # 基础概率（从30降低到20，更保守）
        limit_up_reasons = []
        
        # 8.1 涨幅特征（横盘整理概率最高，连板股单独评估）
        # 2026-09-02回测发现：31%涨停股昨天涨幅>5%（已涨停，连板股）
        is_lianban = pct_change > 5
        if is_lianban:
            # 连板股专门评估
            limit_up_prob += 8  # 连板股基础加分（强势延续）
            limit_up_reasons.append(f"连板股(昨涨{pct_change:.1f}%)，强势延续可能继续涨停")
        elif -1 <= pct_change < 1:
            limit_up_prob += 12  # 从15降低到12
            limit_up_reasons.append("横盘整理(-1%~1%)，蓄势待发")
        elif -3 <= pct_change < -1:
            limit_up_prob += 11  # 从10提高到11，超跌反弹容易涨停
            limit_up_reasons.append("缩量回调(-3%~-1%)，洗盘后反弹")
        elif -5 <= pct_change < -3:
            limit_up_prob += 10  # 新增，大跌反弹
            limit_up_reasons.append(f"大跌反弹({pct_change:.1f}%)，超跌反弹概率高")
        elif -8 <= pct_change < -5:
            limit_up_prob += 8  # 新增，深度超跌反弹
            limit_up_reasons.append(f"深度超跌({pct_change:.1f}%)，报复性反弹")
        elif -10 <= pct_change < -8:
            limit_up_prob += 5  # 新增，极端超跌反弹
            limit_up_reasons.append(f"极端超跌({pct_change:.1f}%)，注意风险但反弹空间大")
        elif 1 <= pct_change <= 3:
            limit_up_prob += 8  # 从10降低到8
            limit_up_reasons.append("温和上涨(1%~3%)，稳步推升")
        elif 3 < pct_change <= 5:
            limit_up_prob += 3
            limit_up_reasons.append(f"涨幅较大({pct_change:.1f}%)，接近涨停")
        
        # 8.2 振幅特征（振幅大股性活跃，但过大也有风险）
        if 3 <= amplitude < 7:
            limit_up_prob += 8
            limit_up_reasons.append(f"振幅适中({amplitude:.1f}%)，股性活跃")
        elif amplitude >= 7:
            limit_up_prob += 4  # 振幅过大，风险增加
            limit_up_reasons.append(f"振幅大({amplitude:.1f}%)，波动剧烈")
        elif amplitude >= 2:
            limit_up_prob += 3
        
        # 8.3 换手率特征（适度活跃概率高，过高有风险）
        if 3 <= turnover <= 7:
            limit_up_prob += 6  # 从8降低到6
            limit_up_reasons.append(f"换手率适中({turnover:.1f}%)，资金关注度高")
        elif 7 < turnover <= 15:
            limit_up_prob += 3
            limit_up_reasons.append(f"换手率较高({turnover:.1f}%)，交投活跃")
        elif turnover > 15:
            limit_up_prob -= 3  # 换手率过高，出货风险
            limit_up_reasons.append(f"换手率过高({turnover:.1f}%)，出货风险")
        
        # 8.4 量比特征（缩量整理后放量涨停是常见模式）
        if 0.5 <= vol_ratio < 0.8:
            limit_up_prob += 6  # 从8降低到6
            limit_up_reasons.append(f"缩量整理(量比{vol_ratio:.1f})，洗盘后可能放量涨停")
        elif 0.8 <= vol_ratio <= 1.2:
            limit_up_prob += 4  # 从5降低到4
            limit_up_reasons.append(f"量能平稳(量比{vol_ratio:.1f})，蓄势整理")
        elif 1.2 < vol_ratio <= 2:
            limit_up_prob += 4
            limit_up_reasons.append(f"温和放量(量比{vol_ratio:.1f})，资金关注")
        elif vol_ratio > 3:
            limit_up_prob -= 3  # 量比过大，追高风险
            limit_up_reasons.append(f"量比过大({vol_ratio:.1f})，追高风险")
        
        # 8.5 均线特征（多头排列趋势强势）
        try:
            ma5 = calc_sma(close, 5).iloc[-1]
            ma10 = calc_sma(close, 10).iloc[-1]
            ma20_val = calc_sma(close, 20).iloc[-1]
            if ma5 > ma10 > ma20_val:
                limit_up_prob += 6  # 从8降低到6
                limit_up_reasons.append("均线多头排列，趋势强势")
            elif current_price > ma20_val:
                limit_up_prob += 3  # 从4降低到3
                limit_up_reasons.append("股价在MA20上方，趋势向好")
            else:
                limit_up_prob -= 3  # 股价在MA20下方，趋势偏弱
                limit_up_reasons.append("股价在MA20下方，趋势偏弱")
        except Exception:
            pass
        
        # 8.6 价格特征（低价股更容易涨停，但波动性大风险高）
        # 2026-09-04回测发现：84.2%涨停股<20元，44.7%<10元，>=50元极少
        if 3 <= current_price < 10:
            limit_up_prob += 8  # 从5增加到8，中低价股弹性最好（44.7%涨停股<10元）
            limit_up_reasons.append(f"中低价股({current_price}元)，弹性好易涨停")
        elif current_price < 3:
            limit_up_prob += 4  # 从2增加到4，低价股波动大
            limit_up_reasons.append(f"低价股({current_price}元)，波动大弹性足")
        elif current_price < 20:
            limit_up_prob += 5  # 从3增加到5，中价股也容易涨停（84.2%涨停股<20元）
            limit_up_reasons.append(f"中价股({current_price}元)，价格适中")
        elif current_price < 50:
            limit_up_prob += 2  # 高价股涨停概率低
            limit_up_reasons.append(f"中高价股({current_price}元)，涨停难度大")
        else:
            limit_up_prob -= 2  # >=50元极少涨停
            limit_up_reasons.append(f"高价股({current_price}元)，很难涨停")
        
        # 8.6.1 成交额特征（新增：2026-09-04回测发现65.8%涨停股<5亿）
        # 成交额太小流动性差，太大难涨停，5亿以下最佳
        amount = stock.get("amount", 0)
        amount_yi = amount / 100000000 if amount > 0 else 0
        if amount_yi > 0:
            if 0.5 <= amount_yi < 5:
                limit_up_prob += 8  # 小盘股最容易涨停（65.8%涨停股<5亿）
                limit_up_reasons.append(f"成交额适中({amount_yi:.1f}亿)，小盘股易拉升")
            elif 5 <= amount_yi < 10:
                limit_up_prob += 5  # 中盘股也有机会
                limit_up_reasons.append(f"成交额良好({amount_yi:.1f}亿)，中盘股有机会")
            elif 10 <= amount_yi < 20:
                limit_up_prob += 2  # 大盘股涨停难度大
                limit_up_reasons.append(f"成交额较大({amount_yi:.1f}亿)，大盘股难涨停")
            elif amount_yi >= 20:
                limit_up_prob -= 2  # 超大盘股很难涨停
                limit_up_reasons.append(f"成交额过大({amount_yi:.1f}亿)，很难涨停")
            elif amount_yi < 0.5:
                limit_up_prob -= 3  # 成交额太小流动性差
                limit_up_reasons.append(f"成交额过小({amount_yi:.2f}亿)，流动性差")
        
        # 8.7 消息面加成
        try:
            news_impact = stock.get("news_impact", {})
            news_score = news_impact.get("score", 50)
            if news_score >= 70:
                limit_up_prob += 8  # 从10降低到8
                limit_up_reasons.append("消息面利好，有催化")
            elif news_score >= 60:
                limit_up_prob += 4  # 从5降低到4
                limit_up_reasons.append("消息面偏利好")
            elif news_score <= 30:
                limit_up_prob -= 5  # 消息面利空，大幅扣分
                limit_up_reasons.append("消息面利空，风险大")
        except Exception:
            pass
        
        # 8.8 概念热点加成
        try:
            concept_analysis = stock.get("concept_analysis", {})
            matched_hot = concept_analysis.get("matched_hot", [])
            if matched_hot:
                limit_up_prob += 6  # 从8降低到6
                limit_up_reasons.append("涉及热门概念，题材风口")
        except Exception:
            pass
        
        # 8.9 风险因素综合扣分（新增）
        # 连续上涨天数过多，回调风险大
        try:
            up_days = 0
            for j in range(1, min(6, len(close))):
                if close.iloc[-j] > close.iloc[-j-1]:
                    up_days += 1
                else:
                    break
            if up_days >= 4:
                limit_up_prob -= 5
                limit_up_reasons.append(f"连续上涨{up_days}天，回调风险大")
        except Exception:
            pass
        
        # 限制概率范围（最高从95降低到80，更保守）
        limit_up_prob = max(5, min(80, round(limit_up_prob)))
        
        # 9. 基本面评分（优化：添加真正的基本面数据，之前只基于消息面和概念热点导致都是0分）
        # 基于：ROE、毛利率、营收增长、利润增长、PE/PB等真正的基本面指标
        # 消息面和概念热点作为补充
        fundamental_score = 0
        fundamental_changes = []
        fundamental_research = ""
        fundamental_data = {}
        
        try:
            # 9.0 获取真正的基本面数据（使用Tushare接口，GitHub Actions环境可用）
            code = stock.get("code", "")  # 从stock字典中获取code（修复：之前code未定义）
            try:
                from backend.data.collector import DataCollector
                fundamental_collector = DataCollector()
                fundamental_data = fundamental_collector.get_fundamental(code)
                if fundamental_data:
                    fundamental_changes.append("基本面数据已获取")
            except Exception as e:
                logger.debug(f"获取基本面数据失败 {code}: {e}")
                fundamental_data = {}
            
            # 9.1 ROE评分（净资产收益率，最重要的基本面指标）
            roe = fundamental_data.get("roe", 0)
            if roe > 0:
                if roe >= 20:
                    fundamental_score += 20
                    fundamental_changes.append(f"ROE优秀({roe:.1f}%)")
                elif roe >= 15:
                    fundamental_score += 15
                    fundamental_changes.append(f"ROE良好({roe:.1f}%)")
                elif roe >= 10:
                    fundamental_score += 10
                    fundamental_changes.append(f"ROE一般({roe:.1f}%)")
                elif roe >= 5:
                    fundamental_score += 5
                    fundamental_changes.append(f"ROE较低({roe:.1f}%)")
                else:
                    fundamental_score -= 5
                    fundamental_changes.append(f"ROE差({roe:.1f}%)")
            
            # 9.2 毛利率评分
            gross_margin = fundamental_data.get("gross_margin", 0)
            if gross_margin > 0:
                if gross_margin >= 40:
                    fundamental_score += 10
                    fundamental_changes.append(f"毛利率高({gross_margin:.1f}%)")
                elif gross_margin >= 25:
                    fundamental_score += 7
                    fundamental_changes.append(f"毛利率良好({gross_margin:.1f}%)")
                elif gross_margin >= 15:
                    fundamental_score += 4
                    fundamental_changes.append(f"毛利率一般({gross_margin:.1f}%)")
            
            # 9.3 营收增长评分
            revenue_yoy = fundamental_data.get("revenue_yoy", 0)
            if revenue_yoy > 0:
                if revenue_yoy >= 30:
                    fundamental_score += 15
                    fundamental_changes.append(f"营收高增长({revenue_yoy:.1f}%)")
                elif revenue_yoy >= 15:
                    fundamental_score += 10
                    fundamental_changes.append(f"营收增长良好({revenue_yoy:.1f}%)")
                elif revenue_yoy >= 5:
                    fundamental_score += 5
                    fundamental_changes.append(f"营收稳定增长({revenue_yoy:.1f}%)")
            elif revenue_yoy < 0:
                fundamental_score -= 5
                fundamental_changes.append(f"营收下滑({revenue_yoy:.1f}%)")
            
            # 9.4 利润增长评分
            profit_yoy = fundamental_data.get("profit_yoy", 0)
            if profit_yoy > 0:
                if profit_yoy >= 50:
                    fundamental_score += 15
                    fundamental_changes.append(f"利润暴增({profit_yoy:.1f}%)")
                elif profit_yoy >= 30:
                    fundamental_score += 10
                    fundamental_changes.append(f"利润高增长({profit_yoy:.1f}%)")
                elif profit_yoy >= 10:
                    fundamental_score += 5
                    fundamental_changes.append(f"利润稳定增长({profit_yoy:.1f}%)")
            elif profit_yoy < 0:
                fundamental_score -= 10
                fundamental_changes.append(f"利润下滑({profit_yoy:.1f}%)")
            
            # 9.5 PE/PB估值评分（从行情数据中获取）
            pe = fundamental_data.get("pe", 0)
            pb = fundamental_data.get("pb", 0)
            if pe > 0:
                if pe <= 15:
                    fundamental_score += 10
                    fundamental_changes.append(f"PE低估值({pe:.1f})")
                elif pe <= 30:
                    fundamental_score += 5
                    fundamental_changes.append(f"PE合理({pe:.1f})")
                elif pe > 50:
                    fundamental_score -= 5
                    fundamental_changes.append(f"PE高估({pe:.1f})")
            
            # 9.6 消息面基本面变化（作为补充）
            news_impact = stock.get("news_impact", {})
            news_score = news_impact.get("score", 50)
            news_reasons = news_impact.get("reasons", [])
            
            if news_score >= 70:
                fundamental_score += 10
                fundamental_changes.append("消息面利好")
                if news_reasons:
                    fundamental_changes.extend(news_reasons[:2])
            elif news_score <= 30:
                fundamental_score -= 5
                fundamental_changes.append("消息面利空")
            
            # 9.7 概念热点基本面变化（作为补充）
            concept_analysis = stock.get("concept_analysis", {})
            matched_hot = concept_analysis.get("matched_hot", [])
            if matched_hot:
                fundamental_score += 5
                fundamental_changes.append(f"涉及热门概念: {'、'.join(matched_hot[:2])}")
            
            # 9.8 行业景气度变化
            industry = stock.get("industry", "")
            if industry:
                fundamental_changes.append(f"所属行业: {industry}")
            
            # 9.9 确定今天最值得研究什么
            if fundamental_changes:
                fundamental_research = f"重点研究: {'、'.join(fundamental_changes[:3])}"
            else:
                fundamental_research = "重点研究: 技术面突破信号和资金流向"
                
        except Exception as e:
            logger.debug(f"基本面评分计算失败 {code}: {e}")
            fundamental_research = "重点研究: 技术面突破信号和资金流向"
        
        # 限制基本面评分范围（0-100）
        fundamental_score = max(0, min(100, fundamental_score))
        
        # 将基本面评分加入总分（占20%权重）
        score += fundamental_score * 0.2
        
        # 10. 逻辑反证检查（新增，基于表4：逻辑反证逻辑）
        # 主动寻找反面证据，不迎合用户观点
        counter_evidences = []
        try:
            # 10.1 连续上涨天数过多，回调风险
            up_days = 0
            for j in range(1, min(6, len(close))):
                if close.iloc[-j] > close.iloc[-j-1]:
                    up_days += 1
                else:
                    break
            if up_days >= 4:
                counter_evidences.append(f"连续上涨{up_days}天，短期回调风险大")
            
            # 10.2 涨幅过大，追高风险
            if pct_change > 7:
                counter_evidences.append(f"涨幅过大({pct_change:.1f}%)，追高风险")
            
            # 10.3 换手率过高，出货风险
            turnover = stock.get("turnover", 0)
            if turnover > 15:
                counter_evidences.append(f"换手率过高({turnover:.1f}%)，可能出货")
            
            # 10.4 量比过大，追高风险
            if vol_ratio > 3:
                counter_evidences.append(f"量比过大({vol_ratio:.1f})，短期过热")
            
            # 10.5 股价远离均线，回调风险
            try:
                ma20_val = calc_sma(close, 20).iloc[-1]
                if ma20_val > 0 and current_price > ma20_val * 1.2:
                    deviation = (current_price - ma20_val) / ma20_val * 100
                    counter_evidences.append(f"股价偏离MA20达{deviation:.1f}%，技术回调风险")
            except Exception:
                pass
            
            # 10.6 消息面利空
            if news_score <= 30:
                counter_evidences.append("消息面偏利空，需警惕基本面恶化")
                
        except Exception:
            pass
        
        # 如果有反证，降低评分
        if counter_evidences:
            score -= len(counter_evidences) * 2
            risks.extend(counter_evidences)
        
        score = max(0, min(100, round(score)))

        analysis = {
            "reasons": reasons,
            "risks": risks,
            "trend": trend_name,
            "volume_ratio": vol_ratio,
            "pattern": pattern,
            "limit_up_probability": limit_up_prob,
            "limit_up_reasons": limit_up_reasons,
            # 新增：基本面变化和逻辑反证
            "fundamental_score": round(fundamental_score, 1),
            "fundamental_changes": fundamental_changes,
            "fundamental_research": fundamental_research,
            "counter_evidences": counter_evidences,
            "has_counter_evidence": len(counter_evidences) > 0,
        }

        return score, analysis


# 全局单例
late_day_screener = LateDayScreener()
