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
from typing import Dict, List, Optional
from backend.data.collector import collector
from backend.analysis.three_locks import three_locks_analyzer
from backend.analysis.trend_analysis import trend_analyzer
from backend.analysis.indicators import (
    calc_sma, calc_trend, calc_macd, calc_kdj,
    calc_volume_analysis, calc_momentum
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
        score_threshold = 50  # 默认评分门槛
        min_locks = 0  # 默认三把锁门槛（0=不限制）
        if market_status['sh_pct'] < -1.0:
            self.max_results = 20  # 从30减少到20
            score_threshold = 55  # 提高评分门槛（从50提高到55）
            min_locks = 1  # 至少1/3亮
            logger.info(f"大盘下跌{market_status['sh_pct']:.2f}%，推荐数量减少到20只，评分门槛提高到55分，三把锁至少1/3亮")
        elif market_status['sh_pct'] < -0.5:
            self.max_results = 25  # 从30减少到25
            score_threshold = 50  # 提高评分门槛（从50提高到50）
            min_locks = 1  # 至少1/3亮
            logger.info(f"大盘下跌{market_status['sh_pct']:.2f}%，推荐数量减少到25只，评分门槛提高到50分，三把锁至少1/3亮")
        else:
            self.max_results = 30  # 正常情况推荐30只
            score_threshold = 35  # 正常评分门槛（从40降低到35，基于2026-09-07回测，很多涨停股票评分低于40分）
            min_locks = 0  # 不限制三把锁
            logger.info(f"大盘正常，推荐数量30只，评分门槛35分（基于回测优化，提高涨停股命中率）")

        # 获取全量股票列表
        if stock_df is None:
            stock_df = collector.get_all_stocks()
        if stock_df is None or stock_df.empty:
            return {"error": "无法获取股票列表", "picks": []}

        logger.info(f"股票池数量: {len(stock_df)}")

        # 第一步：初筛（基于实时行情数据快速过滤）
        candidates = self._initial_filter(stock_df)
        logger.info(f"初筛后剩余: {len(candidates)} 只")
        # 限制候选股票数量，避免运行时间过长（按成交量排序，取前120只）
        # 基于2026-09-07回测优化：从100增加到120，扩大分析范围，提高涨停股命中率
        if len(candidates) > 120:
            candidates.sort(key=lambda x: x.get("amount", x.get("volume", 0)), reverse=True)
            candidates = candidates[:120]  # 从100增加到120，扩大分析范围
            logger.info(f"候选股票限制为120只（按成交量排序，基于回测优化提高命中率）")

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
        # 传递批量获取的K线数据和大盘环境参数，避免重复获取
        # 注意：换手率数据通过量比估算（Tushare daily_basic频率限制1次/小时无法使用）
        deep_result = self._deep_analyze(candidates, batch_kline_data, score_threshold, min_locks)
        
        # 从_deep_analyze返回的字典中获取all_picks、top_picks和special_picks
        # 兼容_deep_analyze返回字典或列表的情况
        if isinstance(deep_result, dict):
            all_picks = deep_result.get("all_picks", [])
            top_picks = deep_result.get("top_picks", [])
            special_picks = deep_result.get("special_picks", [])
            picks = all_picks
        else:
            # 兼容旧版本：_deep_analyze返回列表
            picks = deep_result if isinstance(deep_result, list) else []
            all_picks = picks[:self.max_results] if len(picks) >= self.max_results else picks
            top_picks = all_picks[:self.top_picks] if len(all_picks) >= self.top_picks else all_picks
            special_picks = all_picks[:5] if len(all_picks) >= 5 else all_picks
        
        logger.info(f"尾盘选股完成，共推荐 {len(all_picks)} 只")
        logger.info(f"陈小群风格特别推荐: {len(special_picks)}只")
        
        return {
            "picks": picks,
            "all_picks": all_picks,  # 全部30支
            "top_picks": top_picks,  # 精选10支
            "special_picks": special_picks,  # 陈小群风格特别推荐5支
            "total_count": len(all_picks),
            "top_count": len(top_picks),
            "special_count": len(special_picks),
            "summary": {
                "total_stocks": len(stock_df),
                "initial_filtered": len(candidates),
                "final_picks": len(all_picks),
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
                # 价格 2-200元（优化：从50元扩大到200元，2026-09-07回测发现21.5%涨停股>50元，科技股价格较高）
                # 2026-09-04回测发现84.2%涨停股<20元，但市场环境变化，不能只关注低价股
                if price < 2 or price > 200:
                    continue
                # 成交额过滤（优化：从0.5-50亿扩大到0.5-100亿，2026-09-07回测发现30.1%涨停股>10亿）
                # 成交额太小（<0.5亿）流动性差，太大（>100亿）难涨停
                amount_yi = amount / 100000000  # 转换为亿
                if amount_yi > 0 and (amount_yi < 0.5 or amount_yi > 100):
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

    def _deep_analyze(self, candidates: List[Dict], batch_kline_data: Dict = None, score_threshold: int = 50, min_locks: int = 0) -> List[Dict]:
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
        # 调试日志：排查推荐0只股票的问题
        logger.info(f"深度分析开始: candidates={len(candidates)}只, batch_kline_data={len(batch_kline_data) if batch_kline_data else 0}只, score_threshold={score_threshold}")
        use_batch_kline = batch_kline_data is not None and len(batch_kline_data) > 0
        if use_batch_kline:
            logger.info(f"使用批量获取的K线数据: {len(batch_kline_data)}只股票")
        
        # 换手率数据通过量比估算（Tushare daily_basic频率限制1次/小时无法使用）
        
        # 板块效应分析（基于2026-09-07回测优化：科技/电子类占25.3%，是最大的明确行业类别）
        # 基于股票名称关键词识别热门板块，给热门板块内的股票加分
        sector_keywords = {
            "科技半导体": ["科技", "半导体", "芯片", "集成", "电路", "电子", "软件", "信息", "通信", "5G", "人工智能", "AI", "大数据", "云计算", "物联网", "区块链", "量子", "机器人", "智能", "光电", "射频", "传感", "精密", "微", "数字", "网络", "互联", "数据", "计算", "存储", "显示", "光学", "激光"],
            "农业食品": ["农", "粮", "种", "牧", "渔", "食", "酒", "饮", "奶", "肉", "蛋", "糖", "盐", "油", "面", "米", "果", "菜", "茶", "烟", "饲", "肥", "农药", "养殖", "屠宰", "食品", "农业", "种业", "牧业", "渔业"],
            "医药医疗": ["药", "医", "疗", "健", "康", "生物", "制药", "药业", "医疗", "医院", "诊所", "疫苗", "检测", "器械", "耗材", "健康", "保健"],
            "新能源": ["新能", "光伏", "风电", "锂电", "电池", "储能", "氢能", "充电", "新能源", "太阳能", "风能", "核能", "碳中和", "碳交易"],
            "汽车交通": ["汽车", "车", "交通", "运输", "物流", "快递", "航运", "航空", "机场", "港口", "铁路", "公路", "公交", "出租", "网约车", "新能源汽车", "电动车", "智能驾驶"],
            "房地产建筑": ["地产", "房", "建筑", "建材", "水泥", "钢铁", "玻璃", "陶瓷", "涂料", "防水", "装修", "装饰", "物业", "园林", "环保", "节能"],
            "金融": ["银行", "证券", "保险", "信托", "期货", "金融", "基金", "租赁", "担保", "典当", "财富", "资管"],
            "传媒娱乐": ["传媒", "娱乐", "影视", "电影", "电视", "广播", "出版", "游戏", "动漫", "音乐", "体育", "旅游", "酒店", "餐饮", "免税", "彩票"],
            "化工材料": ["化工", "化学", "材料", "塑料", "橡胶", "纤维", "涂料", "染料", "颜料", "化肥", "农药", "医药中间体", "新材料", "石墨烯", "碳纤维", "稀土", "有色", "金属", "黄金", "白银", "铜", "铝", "锌", "镍", "钴", "锂"],
            "电力能源": ["电力", "能源", "火电", "水电", "核电", "风电", "光伏", "生物质", "地热", "潮汐", "煤炭", "石油", "天然气", "燃气", "油品", "加油"],
            "商业零售": ["商业", "零售", "百货", "超市", "商场", "购物", "电商", "网购", "直播", "带货", "连锁", "加盟", "批发", "贸易", "外贸", "跨境"],
            "军工国防": ["军工", "国防", "航天", "航空", "兵器", "船舶", "核工业", "军事", "武器", "装备", "雷达", "导弹", "卫星", "飞船", "航母", "潜艇", "坦克"],
        }
        
        # 统计候选股票的板块分布
        sector_count = {}
        stock_sector = {}
        for stock in candidates:
            name = stock.get("name", "")
            matched_sectors = []
            for sector, keywords in sector_keywords.items():
                if any(kw in name for kw in keywords):
                    matched_sectors.append(sector)
            if matched_sectors:
                # 科技半导体优先（回测显示科技/电子类涨停最多）
                if "科技半导体" in matched_sectors:
                    main_sector = "科技半导体"
                else:
                    main_sector = matched_sectors[0]
                stock_sector[stock["code"]] = main_sector
                sector_count[main_sector] = sector_count.get(main_sector, 0) + 1
        
        # 识别热门板块（候选股票数量最多的前3个板块）
        hot_sectors = sorted(sector_count.items(), key=lambda x: x[1], reverse=True)[:3]
        hot_sector_names = [s[0] for s in hot_sectors if s[1] >= 2]  # 至少2只股票才算热门板块
        if hot_sector_names:
            logger.info(f"热门板块识别: {', '.join([f'{s}({sector_count[s]}只)' for s in hot_sector_names])}")

        # 统计计数器：排查推荐0只股票的问题
        stats = {"total": 0, "kline_ok": 0, "amplitude_ok": 0, "turnover_ok": 0, "ma20_ok": 0, "score_ok": 0, "errors": 0}
        
        for i, stock in enumerate(candidates):
            try:
                stats["total"] += 1
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
                stats["kline_ok"] += 1
                
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
                            # 用量比估算换手率（Tushare daily_basic频率限制1次/小时无法使用，改用估算）
                            # 基于量比与换手率的正相关关系估算（2026-09-04涨停股平均换手率9.63%）
                            if volume_ratio < 0.5:
                                estimated_turnover = 1.0  # 非常不活跃
                            elif volume_ratio < 0.8:
                                estimated_turnover = 2.0  # 缩量整理
                            elif volume_ratio < 1.2:
                                estimated_turnover = 3.0  # 量能平稳
                            elif volume_ratio < 1.5:
                                estimated_turnover = 4.0  # 温和放量
                            elif volume_ratio < 2.0:
                                estimated_turnover = 6.0  # 放量
                            elif volume_ratio < 3.0:
                                estimated_turnover = 8.0  # 明显放量
                            else:
                                estimated_turnover = 12.0  # 巨量
                            # 只在没有真实换手率数据时使用估算值
                            if stock.get("turnover", 0) <= 0:
                                stock["turnover"] = estimated_turnover
                                stock["turnover_estimated"] = True
                except Exception as e:
                    logger.debug(f"计算量比失败 {stock.get('code', '')}: {e}")

                # 把当日实时数据合并到K线中（确保技术指标包含当日数据）
                current_price = stock["price"]
                try:
                    today = pd.Timestamp.now().strftime("%Y-%m-%d")
                    # 检查K线最后一天是否是今天
                    last_date = str(kline.index[-1])[:10] if hasattr(kline.index[-1], 'strftime') else str(kline.index[-1])[:10]
                    if last_date != today:
                        # 获取当日high和low，检查是否合理（修复：之前high和low都是current_price导致振幅为0）
                        today_high = stock.get("high", 0)
                        today_low = stock.get("low", 0)
                        today_open = stock.get("open", current_price)
                        # 如果high和low不合理（都等于close或者high<=low），使用前一天的high和low估算
                        if today_high <= 0 or today_low <= 0 or today_high <= today_low or (today_high == current_price and today_low == current_price):
                            # 使用前一天的振幅估算当日振幅
                            if len(kline) >= 2:
                                prev_high = high.iloc[-1] if 'high' in kline.columns else current_price * 1.02
                                prev_low = low.iloc[-1] if 'low' in kline.columns else current_price * 0.98
                                prev_close_amt = close.iloc[-1] if len(close) > 0 else current_price
                                prev_amplitude = (prev_high - prev_low) / prev_close_amt if prev_close_amt > 0 else 0.02
                                today_high = current_price * (1 + prev_amplitude / 2)
                                today_low = current_price * (1 - prev_amplitude / 2)
                                today_open = current_price * (1 - prev_amplitude / 4)
                            else:
                                today_high = current_price * 1.02
                                today_low = current_price * 0.98
                                today_open = current_price
                        # 添加当日实时数据到K线
                        new_row = pd.DataFrame({
                            "open": [today_open],
                            "high": [today_high],
                            "low": [today_low],
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
                        if i < 10:
                            logger.info(f"振幅过滤 {stock['name']}({stock.get('code', '')}): high={today_high:.2f}, low={today_low:.2f}, prev_close={prev_close:.2f}, 振幅{amplitude:.2f}% < 1%")
                        continue  # 振幅太小，股性不活跃，很难涨停
                stats["amplitude_ok"] += 1

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
                stats["turnover_ok"] += 1

                # 放宽MA20条件：允许股价在20日均线下方10%以内（突破型）
                # 回测发现33.8%涨停股前一天股价不在MA20之上，很多是从下方突破的
                ma20 = calc_sma(close, 20).iloc[-1]
                if current_price < ma20 * 0.9:  # 允许低于MA20不超过10%
                    if i < 5:
                        logger.debug(f"MA20过滤 {stock['name']}({stock.get('code', '')}): 价格{current_price:.2f} < MA20*0.9={ma20*0.9:.2f}")
                    continue
                stats["ma20_ok"] += 1

                # 板块效应加分（基于2026-09-08回测优化：农业食品、传媒娱乐、科技半导体、医药医疗是涨停最多的行业）
                # 热门板块内的股票更容易涨停，增加加分权重
                sector_bonus = 0
                stock_main_sector = stock_sector.get(code, "")
                # 基础加分：基于2026-09-08回测，涨停最多的行业给予基础加分
                sector_base_bonus = {
                    "科技半导体": 4,  # 科技半导体基础加4分（长期涨停最多）
                    "农业食品": 3,    # 农业食品基础加3分（2026-09-08涨停8只，占11.3%）
                    "传媒娱乐": 3,    # 传媒娱乐基础加3分（2026-09-08涨停7只，占9.9%）
                    "医药医疗": 3,    # 医药医疗基础加3分（2026-09-08涨停6只，占8.5%）
                    "化工材料": 2,    # 化工材料基础加2分
                    "新能源": 2,      # 新能源基础加2分
                }
                if stock_main_sector in sector_base_bonus:
                    sector_bonus = sector_base_bonus[stock_main_sector]
                if stock_main_sector in hot_sector_names:
                    sector_bonus += 10  # 热门板块加10分（从8分提高）
                    # 科技半导体板块作为热门板块时额外加分
                    if stock_main_sector == "科技半导体":
                        sector_bonus += 3  # 科技半导体热门板块额外加3分
                stock["sector_bonus"] = sector_bonus
                stock["sector"] = stock_main_sector
                
                # 计算技术指标
                score, analysis = self._calc_late_day_score(kline, stock)
                # 加上板块效应加分
                score = score + sector_bonus
                
                # 调试日志：输出每只股票的评分情况（改为info级别，方便在GitHub Actions中排查问题）
                if i < 10 or score >= 60:
                    logger.info(f"评分调试 {stock['name']}({stock.get('code', '')}): 涨幅{stock.get('pct_change', 0):.1f}%, 价格{current_price}, 评分{score}, 理由{analysis.get('reasons', [])[:3]}")

                # 去掉量能硬过滤：回测发现46.3%涨停股前一天不满足连续放量条件
                # 很多是缩量整理后突然放量涨停，量能只在评分中考虑
                # 连续放量过滤已移除，改为评分项

                # 只保留评分>=score_threshold的（大盘下跌时提高门槛，正常情况50分）
                # 修复：评分系统优化后，final_score上限从100降低到95，需要相应降低门槛
                if score >= score_threshold:
                    stats["score_ok"] += 1
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
                        # 基本面评分（先初始化为0，后面计算完成后更新）
                        "fundamental_score": 0,
                        "fundamental": {
                            "score": 0,
                            "data": {},
                            "changes": [],
                            "research": "",
                        },
                    }
                    results.append(result)
                    result_index = len(results) - 1  # 记录当前结果在列表中的索引

            except Exception as e:
                stats["errors"] += 1
                logger.info(f"分析失败 {stock.get('code')} {stock.get('name', '')}: {e}")
                import traceback
                logger.info(traceback.format_exc()[:500])
                continue
        
        # 输出统计信息：排查推荐0只股票的问题
        logger.info(f"深度分析统计: 总数{stats['total']}, K线正常{stats['kline_ok']}, 振幅通过{stats['amplitude_ok']}, 换手率通过{stats['turnover_ok']}, MA20通过{stats['ma20_ok']}, 评分通过{stats['score_ok']}, 错误{stats['errors']}, 最终结果{len(results)}")

        # 行业分散度限制：同一行业最多推荐2只，避免行业集中风险
        # 基于2026-09-01回测：化工4只平均-8.02%，行业集中导致大幅亏损
        # 基于2026-09-07回测优化：从15增加到25，因为行业分散度过滤从86只减少到15只，太严格了，错过很多涨停股
        industry_count = {}
        filtered_results = []
        for stock in results:
            industry = stock.get("industry", "") or stock.get("所属行业", "") or "未知"
            if industry not in industry_count:
                industry_count[industry] = 0
            if industry_count[industry] < 25:  # 同一行业最多25只（从15增加到25，基于2026-09-07回测，行业分散度过滤太严格错过很多涨停股）
                industry_count[industry] += 1
                filtered_results.append(stock)
        
        logger.info(f"行业分散度过滤: 从{len(results)}只减少到{len(filtered_results)}只（同一行业最多25只）")
        results = filtered_results

        # 三把锁信号过滤（优化：只保留买入信号，排除卖出和观望信号）
        # 用户反馈：观望的股票不应该出现在推荐里，只推荐有明确买入信号的股票
        # 三把锁门槛已降低（趋势40分、股性50分、资金30分），确保有足够的买入信号股票
        buy_signals = ["强烈买入", "买入"]  # 只保留买入信号
        sell_signals = ["强烈卖出", "卖出", "谨慎买入", "观望", "观望（趋势向好）"]  # 排除卖出和观望信号
        excluded_sell_count = 0
        
        filtered_results = []
        for stock in results:
            # 类型检查：确保stock是字典，跳过字符串等非字典元素（修复TypeError）
            if not isinstance(stock, dict):
                logger.warning(f"跳过非字典元素: {type(stock)} - {stock}")
                continue
            tl = stock.get("three_locks", {}) or {}
            tl_signal = tl.get("signal", "")
            tl_locked = tl.get("total_locked", 0)
            
            # 严重bug修复：强烈卖出、卖出、谨慎买入、观望信号的股票直接跳过，不放入任何结果列表
            # 只保留有明确买入信号的股票（强烈买入、买入）
            if tl_signal in sell_signals or tl_signal not in buy_signals:
                excluded_sell_count += 1
                continue
            
            filtered_results.append(stock)
        
        if excluded_sell_count > 0:
            logger.info(f"已排除卖出/观望信号股票: {excluded_sell_count}只（只保留买入信号）")
        
        logger.info(f"三把锁过滤: 从{len(results)}只减少到{len(filtered_results)}只（只保留买入信号，排除卖出和观望信号）")
        results = filtered_results

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
        
        # 陈小群风格特别推荐（深度优化：真正体现陈小群选股思路，使用可靠字段）
        # 核心标准：逻辑硬 + 板块合力（最重要）+ 量价市值 + 四类有效涨停
        # 陈小群名言：买在分歧、卖在一致、死守主线、只做真龙
        special_picks = []
        for stock in all_picks:
            try:
                special_score = 20  # 基础分20分，确保评分不为0
                special_reasons = []
                
                # 获取可靠字段
                current_price = stock.get("price", 0)
                pct_change = stock.get("pct_change", 0)
                amount = stock.get("amount", 0)
                amount_yi = amount / 100000000 if amount > 0 else 0
                base_score = stock.get("score", 0)
                analysis = stock.get("analysis", {}) or {}
                limit_up_prob = analysis.get("limit_up_probability", 0) if analysis else 0
                pattern = analysis.get("pattern", "") if analysis else ""
                sector = stock.get("sector", "")
                sector_bonus = stock.get("sector_bonus", 0)
                vol_ratio = stock.get("volume_ratio", analysis.get("volume_ratio", 0) if analysis else 0)
                
                # 1. 板块合力（最重要，占40分）
                # 陈小群：涨停后30分钟内同板块≥5只涨停，能带动板块的才叫龙头
                # 代理指标：板块效应加分 + 热门板块 + 综合评分高
                if sector_bonus >= 8:
                    special_score += 30
                    special_reasons.append("板块合力强（板块效应8分+）")
                elif sector_bonus >= 5:
                    special_score += 20
                    special_reasons.append("板块合力较好（板块效应5分+）")
                elif sector_bonus >= 3:
                    special_score += 10
                    special_reasons.append("板块有一定合力")
                
                # 科技/电子/新能源等主线板块加分（陈小群死守主线）
                main_sectors = ["科技半导体", "新能源", "医药医疗", "汽车交通", "传媒娱乐"]
                if sector in main_sectors:
                    special_score += 10
                    special_reasons.append(f"主线板块（{sector}）")
                
                # 2. 量价市值（占30分）
                # 陈小群：流通市值50-300亿，换手率10-30%，低位放量≥前5日均量3倍
                # 价格10-50元（弹性好，对应50-300亿流通市值）
                if 10 <= current_price <= 50:
                    special_score += 10
                    special_reasons.append(f"价格{current_price}元（弹性好易拉升）")
                elif 5 <= current_price < 10 or 50 < current_price <= 100:
                    special_score += 5
                    special_reasons.append(f"价格{current_price}元（适中）")
                
                # 成交额1-20亿（有流动性但不大，对应50-300亿流通市值）
                if 1 <= amount_yi <= 20:
                    special_score += 10
                    special_reasons.append(f"成交额{amount_yi:.1f}亿（流动性好）")
                elif 0.5 <= amount_yi < 1 or 20 < amount_yi <= 50:
                    special_score += 5
                    special_reasons.append(f"成交额{amount_yi:.1f}亿（适中）")
                
                # 量比>1.5（放量，对应低位放量≥前5日均量3倍）
                if vol_ratio >= 2:
                    special_score += 10
                    special_reasons.append(f"量比{vol_ratio:.1f}（显著放量）")
                elif vol_ratio >= 1.5:
                    special_score += 5
                    special_reasons.append(f"量比{vol_ratio:.1f}（温和放量）")
                
                # 3. 四类有效涨停特征（占20分）
                # 陈小群：主线情绪首板、龙头回调二波、弱转强反包（最擅长）、首阴反包
                # 弱转强反包（最擅长）：前日走弱，今日超预期（涨幅0-5%+放量）
                if 0 <= pct_change <= 5 and vol_ratio >= 1.5:
                    special_score += 15
                    special_reasons.append("弱转强反包形态（陈小群最擅长）")
                # 首阴反包：总龙头首次回调后二次启动（涨幅-3%到0%）
                elif -3 <= pct_change < 0:
                    special_score += 10
                    special_reasons.append("首阴反包形态")
                # 主线情绪首板：低位分歧转一致启动（涨幅3-7%）
                elif 3 <= pct_change <= 7:
                    special_score += 8
                    special_reasons.append("主线情绪首板形态")
                
                # 涨停概率高（真龙特征）
                if limit_up_prob >= 70:
                    special_score += 5
                    special_reasons.append(f"涨停概率{limit_up_prob}%（高）")
                elif limit_up_prob >= 50:
                    special_score += 3
                    special_reasons.append(f"涨停概率{limit_up_prob}%（较高）")
                
                # 4. 逻辑硬（占10分）
                # 陈小群：必须政策扶持/产业变革/重大事件催化，纯题材炒作直接剔除
                # 代理指标：综合评分高 + 有分析理由 + 非金融板块
                if base_score >= 70:
                    special_score += 5
                    special_reasons.append(f"综合评分{base_score}分（逻辑较硬）")
                elif base_score >= 60:
                    special_score += 3
                    special_reasons.append(f"综合评分{base_score}分")
                
                # 有明确的涨停模式（逻辑清晰）
                if pattern and pattern != "未知":
                    special_score += 5
                    special_reasons.append(f"模式：{pattern}")
                
                # 保存陈小群风格评分和原因
                stock["chen_xiaoqun_score"] = special_score
                stock["chen_xiaoqun_reasons"] = special_reasons[:4]  # 最多显示4个原因
                stock["is_chen_xiaoqun_pick"] = False
                
                special_picks.append((special_score, stock))
            except Exception as e:
                logger.debug(f"陈小群风格评分失败 {stock.get('code', '')}: {e}")
                # 即使评分失败，也给基础分，确保不会因为异常而丢失股票
                if isinstance(stock, dict):
                    stock["chen_xiaoqun_score"] = 20
                    stock["chen_xiaoqun_reasons"] = ["基础分"]
                    stock["is_chen_xiaoqun_pick"] = False
                    special_picks.append((20, stock))
                continue
        
        # 按陈小群风格评分排序，取前5只
        # 深度优化：确保评分都不为0，真正基于陈小群选股思路筛选
        special_picks.sort(key=lambda x: x[0], reverse=True)
        if special_picks:
            special_picks = [sp[1] for sp in special_picks[:5]]
            logger.info(f"陈小群风格特别推荐评分: 最高{special_picks[0].get('chen_xiaoqun_score', 0)}分, 最低{special_picks[-1].get('chen_xiaoqun_score', 0)}分")
        else:
            special_picks = all_picks[:5] if len(all_picks) >= 5 else all_picks
        
        # 标记陈小群风格特别推荐股票
        for i, stock in enumerate(special_picks):
            if isinstance(stock, dict):
                stock["is_chen_xiaoqun_pick"] = True
                stock["chen_xiaoqun_rank"] = i + 1
        
        logger.info(f"陈小群风格特别推荐: {len(special_picks)}只")
        
        return {
            "all_picks": all_picks,  # 全部30支
            "top_picks": top_picks,  # 精选10支
            "special_picks": special_picks,  # 陈小群风格特别推荐5支
            "total_count": len(all_picks),
            "top_count": len(top_picks),
            "special_count": len(special_picks),
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
            score += 15  # 连板股基础加分（从10增加到15，连板股更容易继续涨停）
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

        # 2.6 换手率评分（8分）- 基于2026-09-08回测优化：涨停股平均换手率8.9%，7-15%占42.5%
        # 换手率高的股票资金关注度高，更容易涨停
        turnover = stock.get("turnover", 0)
        if turnover >= 10:
            score += 8
            reasons.append(f"换手率极高({turnover:.1f}%)，资金关注度极高")
        elif turnover >= 7:
            score += 6
            reasons.append(f"换手率高({turnover:.1f}%)，资金关注度高")
        elif turnover >= 5:
            score += 5
            reasons.append(f"换手率较高({turnover:.1f}%)，资金关注度较高")
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
            limit_up_prob += 12  # 连板股基础加分（从8增加到12，连板股更容易继续涨停）
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
        # 2026-09-05近一个月回测发现：3-7%占33.8%，7-15%占32.7%，两者差不多
        # 17.2%涨停股换手率<3%，11.4%在15-25%，4.9%>25%
        if turnover <= 0:
            pass  # 无换手率数据，不评分
        elif turnover < 3:
            limit_up_prob -= 3  # 换手率太低，股性不活跃，很难涨停（17.2%涨停股<3%）
            limit_up_reasons.append(f"换手率过低({turnover:.1f}%)，股性不活跃")
        elif 3 <= turnover <= 7:
            limit_up_prob += 8  # 换手率适中最容易涨停（33.8%涨停股在这个区间）
            limit_up_reasons.append(f"换手率适中({turnover:.1f}%)，资金关注度高")
        elif 7 < turnover <= 15:
            limit_up_prob += 8  # 从6增加到8，与3-7%涨停数量差不多（32.7%涨停股在这个区间）
            limit_up_reasons.append(f"换手率良好({turnover:.1f}%)，交投活跃")
        elif 15 < turnover <= 25:
            limit_up_prob += 4  # 从2增加到4，换手率偏高也有一定机会（11.4%涨停股在这个区间）
            limit_up_reasons.append(f"换手率偏高({turnover:.1f}%)，注意风险")
        else:  # turnover > 25
            limit_up_prob += 0  # 从-2增加到0，换手率过高但仍有机会（4.9%涨停股>25%）
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
        
        # 8.6 价格特征（基于2026-09-07回测优化：市场环境变化，中高价股涨停增多）
        # 2026-09-05近一个月回测：10-20元最多(30.2%)，5-10元其次(24.8%)，20元以下占65.8%
        # 2026-09-07今日回测：10-20元最多(28.0%)，20-50元其次(24.7%)，50元以上21.5%（科技股价格高）
        if 3 <= current_price < 5:
            limit_up_prob += 7  # 3-5元占9.5%
            limit_up_reasons.append(f"低价股({current_price}元)，弹性好易涨停")
        elif 5 <= current_price < 10:
            limit_up_prob += 8  # 5-10元占24.8%
            limit_up_reasons.append(f"中低价股({current_price}元)，弹性好易涨停")
        elif 10 <= current_price < 20:
            limit_up_prob += 9  # 10-20元是涨停最多的区间(28.0%)
            limit_up_reasons.append(f"中价股({current_price}元)，价格适中易涨停")
        elif current_price < 3:
            limit_up_prob += 6  # 2-3元占1.1%
            limit_up_reasons.append(f"超低价股({current_price}元)，波动大弹性足")
        elif current_price < 50:
            limit_up_prob += 7  # 从4增加到7，20-50元占24.7%（市场环境变化，中高价股增多）
            limit_up_reasons.append(f"中高价股({current_price}元)，科技股集中易涨停")
        else:
            limit_up_prob += 5  # 从0增加到5，>=50元占21.5%（今日高价股涨停很多，主要是科技股）
            limit_up_reasons.append(f"高价股({current_price}元)，科技龙头有涨停机会")
        
        # 8.6.1 成交额特征（基于2026-09-07回测优化：大成交额股涨停增多）
        # 2026-09-05近一个月回测：1-5亿最多(49.8%)，5-10亿其次(19.3%)，10亿以下占78.0%
        # 2026-09-07今日回测：1-5亿最多(43.0%)，5-10亿其次(25.8%)，10亿以上28.0%（大成交额科技股）
        amount = stock.get("amount", 0)
        amount_yi = amount / 100000000 if amount > 0 else 0
        if amount_yi > 0:
            if 1 <= amount_yi < 5:
                limit_up_prob += 10  # 1-5亿是涨停最多的区间(43.0%)
                limit_up_reasons.append(f"成交额适中({amount_yi:.1f}亿)，小盘股易拉升")
            elif 5 <= amount_yi < 10:
                limit_up_prob += 8  # 从7增加到8，5-10亿占25.8%
                limit_up_reasons.append(f"成交额良好({amount_yi:.1f}亿)，中盘股有机会")
            elif 0.5 <= amount_yi < 1:
                limit_up_prob += 6  # 0.5-1亿占6.5%
                limit_up_reasons.append(f"成交额偏小({amount_yi:.1f}亿)，流动性一般")
            elif 10 <= amount_yi < 20:
                limit_up_prob += 7  # 从4增加到7，10-20亿占15.1%（大成交额科技股增多）
                limit_up_reasons.append(f"成交额较大({amount_yi:.1f}亿)，科技龙头有资金关注")
            elif amount_yi >= 20:
                limit_up_prob += 5  # 从0增加到5，>=20亿占12.9%（今日大成交额股涨停很多）
                limit_up_reasons.append(f"成交额大({amount_yi:.1f}亿)，大资金抱团龙头")
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
        
        # 8.8.1 首板股特征评分（优化：2026-09-05基于涨停前夕回测分析）
        # 涨停前夕特征：60%涨幅在-3%到3%，横盘整理(-1%到1%)占23.3%最多
        # 23.5%量比0.5-0.8（缩量整理），29.6%量比1.0-1.5（温和放量）
        first_board_score = 0
        first_board_reasons = []
        
        # 1. 涨幅评分（优化：增加横盘整理评分，减少已涨幅较大的评分）
        # 涨停前夕通常是横盘整理，而不是已经涨幅5-9%
        pct_change = stock.get("pct_change", 0)
        if -1 <= pct_change <= 1:
            first_board_score += 6  # 横盘整理，蓄势待发（23.3%涨停股在此区间）
            first_board_reasons.append(f"横盘整理({pct_change:.1f}%)蓄势待发")
        elif -3 <= pct_change < -1 or 1 < pct_change <= 3:
            first_board_score += 4  # 小幅波动，也可能涨停前夕（60%涨停股在-3%到3%）
            first_board_reasons.append(f"小幅波动({pct_change:.1f}%)")
        elif 3 < pct_change < 5:
            first_board_score += 3  # 开始启动
            first_board_reasons.append(f"涨幅{pct_change:.1f}%开始启动")
        elif 5 <= pct_change < 9:
            first_board_score += 2  # 已经涨幅较大，追高风险增加
            first_board_reasons.append(f"涨幅{pct_change:.1f}%追高风险")
        elif pct_change >= 9:
            first_board_score += 0  # 已经接近涨停，错过最佳买入时机
            first_board_reasons.append(f"涨幅{pct_change:.1f}%已接近涨停")
        
        # 2. 量比评分（优化：增加缩量整理和温和放量评分，减少显著放量评分）
        # 涨停前夕通常是缩量整理（洗盘）或温和放量（资金开始关注）
        if 0.5 <= vol_ratio < 0.8:
            first_board_score += 5  # 缩量整理，洗盘后可能放量涨停（23.5%涨停股在此区间）
            first_board_reasons.append(f"缩量整理(量比{vol_ratio:.1f})洗盘")
        elif 1.0 <= vol_ratio <= 1.5:
            first_board_score += 5  # 温和放量，资金开始关注（29.6%涨停股在此区间）
            first_board_reasons.append(f"温和放量(量比{vol_ratio:.1f})资金关注")
        elif 0.8 <= vol_ratio < 1.0:
            first_board_score += 3  # 量能平稳
            first_board_reasons.append(f"量能平稳(量比{vol_ratio:.1f})")
        elif 1.5 < vol_ratio <= 2.0:
            first_board_score += 2  # 明显放量
            first_board_reasons.append(f"明显放量(量比{vol_ratio:.1f})")
        elif vol_ratio > 2.0:
            first_board_score += 1  # 显著放量，可能追高
            first_board_reasons.append(f"显著放量(量比{vol_ratio:.1f})追高风险")
        
        # 3. 换手率适中（3-15%，股性活跃但不过度）
        if 3 <= turnover <= 15:
            first_board_score += 4
            first_board_reasons.append(f"换手率{turnover:.1f}%适中活跃")
        
        # 4. 价格在10-20元之间（首板股涨停最多的区间，占28.3%）
        if 10 <= current_price < 20:
            first_board_score += 3
            first_board_reasons.append(f"价格{current_price}元首板黄金区间")
        
        # 5. 成交额在1-5亿之间（首板股涨停最多的区间，占52.1%）
        amount = stock.get("amount", 0)
        amount_yi = amount / 100000000 if amount > 0 else 0
        if 1 <= amount_yi < 5:
            first_board_score += 3
            first_board_reasons.append(f"成交额{amount_yi:.1f}亿小盘易拉升")
        
        # 6. 技术形态突破（突破近20日高点）
        try:
            if kline is not None and len(kline) >= 20:
                close = kline["close"]
                high_20 = close.tail(20).max()
                if current_price >= high_20 * 0.98:
                    first_board_score += 4
                    first_board_reasons.append("逼近20日高点突破在即")
        except Exception:
            pass
        
        # 7. 缩量整理后放量（新增：洗盘后放量涨停特征）
        # 涨停前夕通常是前几天缩量整理（洗盘），今天开始放量（资金关注）
        try:
            if kline is not None and len(kline) >= 10:
                volume = kline["volume"]
                # 前5天平均成交量（不含今天）
                prev_5_avg = volume.iloc[-6:-1].mean()
                # 今天成交量
                today_vol = volume.iloc[-1]
                # 前3天平均成交量（不含今天）
                prev_3_avg = volume.iloc[-4:-1].mean()
                
                # 缩量整理后放量：前3天缩量（低于5日均量），今天放量（高于5日均量）
                if prev_3_avg < prev_5_avg * 0.9 and today_vol > prev_5_avg * 1.1:
                    first_board_score += 5  # 缩量整理后放量，洗盘结束信号
                    first_board_reasons.append("缩量整理后放量，洗盘结束")
                elif prev_3_avg < prev_5_avg * 0.95 and today_vol > prev_5_avg * 1.05:
                    first_board_score += 3  # 轻微缩量后放量
                    first_board_reasons.append("轻微缩量后放量，资金关注")
                elif today_vol > prev_5_avg * 1.3:
                    first_board_score += 2  # 显著放量
                    first_board_reasons.append("显著放量，资金涌入")
        except Exception:
            pass
        
        # 首板股特征总分（最高35分）
        if first_board_score > 0:
            limit_up_prob += first_board_score
            limit_up_reasons.extend(first_board_reasons[:3])  # 最多显示3个原因
        
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
            fundamental_data_acquired = False
            try:
                from backend.data.collector import DataCollector
                fundamental_collector = DataCollector()
                fundamental_data = fundamental_collector.get_fundamental(code)
                if fundamental_data:
                    fundamental_changes.append("基本面数据已获取")
                    fundamental_data_acquired = True
                else:
                    fundamental_changes.append("基本面数据获取失败，使用中性评分")
            except Exception as e:
                logger.debug(f"获取基本面数据失败 {code}: {e}")
                fundamental_data = {}
                fundamental_changes.append("基本面数据获取异常，使用中性评分")
            
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
        
        # 对于无法获取基本面数据的股票，使用中性评分30分（避免0分造成误解）
        if not fundamental_data_acquired and fundamental_score == 0:
            fundamental_score = 30
            fundamental_changes.append("无基本面数据，使用中性评分30分")
        
        # 将基本面评分加入总分（占20%权重）
        score += fundamental_score * 0.2
        
        # 更新results列表中对应元素的基本面评分（修复：之前没有保存到结果中，导致都是0分）
        if 'result_index' in locals() and result_index < len(results):
            results[result_index]["fundamental_score"] = fundamental_score
            results[result_index]["fundamental"] = {
                "score": fundamental_score,
                "data": fundamental_data,
                "changes": fundamental_changes,
                "research": fundamental_research,
            }
            # 同时更新总分（因为基本面评分加入了总分）
            results[result_index]["base_score"] = score
            results[result_index]["score"] = min(95, int(score * 0.8 + results[result_index].get("three_locks_score", 0)))
        
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
