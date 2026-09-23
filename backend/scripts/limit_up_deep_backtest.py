"""
涨停股票深度回测分析
收集前6个月涨停股票，分析涨停前2天的各项数据特征
包括：技术面、资金面、基本面、消息面
"""
import os
import sys
import time
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from data.collector import collector
from analysis.news_analyzer import NewsAnalyzer

class LimitUpBacktest:
    def __init__(self):
        self.news_analyzer = NewsAnalyzer()
        self.results = []
        
    def get_limit_up_stocks(self, days=180):
        """获取最近N天的涨停股票列表"""
        print(f"正在获取最近{days}天的涨停股票...")
        
        # 从已有的CSV文件读取
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'data', 'limit_up_6months.csv')
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            print(f"从CSV文件读取到涨停股票: {len(df)}条记录")
            return df
        
        print("未找到涨停股票数据文件")
        return None
    
    def analyze_stock_before_limit_up(self, code, name, limit_up_date, days_before=2):
        """分析涨停前N天的股票数据"""
        try:
            # 转换日期格式
            if isinstance(limit_up_date, (int, float)):
                limit_up_dt = datetime.strptime(str(int(limit_up_date)), "%Y%m%d")
            elif isinstance(limit_up_date, str):
                if len(limit_up_date) == 8:
                    limit_up_dt = datetime.strptime(limit_up_date, "%Y%m%d")
                else:
                    limit_up_dt = datetime.strptime(limit_up_date, "%Y-%m-%d")
            else:
                limit_up_dt = limit_up_date
            
            # 获取K线数据（获取60天数据，足够分析前2天）
            kline = collector.get_daily_kline(code, days=60)
            
            if kline is None or len(kline) < days_before + 5:
                return None
            
            # 转换为DataFrame
            df = pd.DataFrame(kline)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            else:
                return None
            
            # 只使用涨停前的数据
            df = df[df['date'] < limit_up_dt].copy()
            df = df.sort_values('date').reset_index(drop=True)
            
            if len(df) < days_before:
                return None
            
            result = {
                'code': code,
                'name': name,
                'limit_up_date': limit_up_dt.strftime("%Y-%m-%d"),
                'industry': '',
            }
            
            # 分析涨停前N天的数据
            for i in range(1, days_before + 1):
                if len(df) < i:
                    break
                    
                day_data = df.iloc[-i]
                prev_data = df.iloc[-i-1] if len(df) > i else None
                
                prefix = f'd{i}_'
                
                # 基本价格数据
                result[prefix + 'close'] = float(day_data.get('close', 0))
                result[prefix + 'open'] = float(day_data.get('open', 0))
                result[prefix + 'high'] = float(day_data.get('high', 0))
                result[prefix + 'low'] = float(day_data.get('low', 0))
                result[prefix + 'volume'] = float(day_data.get('vol', day_data.get('volume', 0)))
                result[prefix + 'amount'] = float(day_data.get('amount', 0))
                
                # 涨跌幅
                if prev_data is not None:
                    prev_close = float(prev_data.get('close', 0))
                    if prev_close > 0:
                        result[prefix + 'pct_change'] = (float(day_data['close']) - prev_close) / prev_close * 100
                        result[prefix + 'amplitude'] = (float(day_data['high']) - float(day_data['low'])) / prev_close * 100
                    else:
                        result[prefix + 'pct_change'] = 0
                        result[prefix + 'amplitude'] = 0
                else:
                    result[prefix + 'pct_change'] = 0
                    result[prefix + 'amplitude'] = 0
                
                # 换手率
                result[prefix + 'turnover'] = float(day_data.get('turnover_rate', day_data.get('turnover', 0)))
                
                # 量比（当日成交量 / 前5日均量）
                if len(df) >= i + 5:
                    prev_5_vol = df.iloc[-i-5:-i]['vol'].mean() if 'vol' in df.columns else df.iloc[-i-5:-i]['volume'].mean()
                    if prev_5_vol > 0:
                        result[prefix + 'volume_ratio'] = result[prefix + 'volume'] / prev_5_vol
                    else:
                        result[prefix + 'volume_ratio'] = 1
                else:
                    result[prefix + 'volume_ratio'] = 1
                
                # 均线
                for ma_period in [5, 10, 20, 60]:
                    if len(df) >= i + ma_period:
                        ma_col = 'vol' if 'vol' in df.columns else 'volume'
                        # 这里应该是收盘价的均线，不是成交量
                        closes = df.iloc[-i-ma_period:-i]['close'].astype(float)
                        result[prefix + f'ma{ma_period}'] = closes.mean()
                    else:
                        result[prefix + f'ma{ma_period}'] = 0
                
                # 均线多头排列
                if result[prefix + 'ma5'] > 0 and result[prefix + 'ma10'] > 0 and result[prefix + 'ma20'] > 0:
                    result[prefix + 'ma_bullish'] = result[prefix + 'ma5'] > result[prefix + 'ma10'] > result[prefix + 'ma20']
                else:
                    result[prefix + 'ma_bullish'] = False
                
                # 股价在MA20上方
                result[prefix + 'above_ma20'] = result[prefix + 'close'] > result[prefix + 'ma20'] if result[prefix + 'ma20'] > 0 else False
                
                # MACD
                if len(df) >= i + 26:
                    closes = df.iloc[:-i]['close'].astype(float).values if i > 0 else df['close'].astype(float).values
                    if len(closes) >= 26:
                        ema12 = pd.Series(closes).ewm(span=12).mean().iloc[-1]
                        ema26 = pd.Series(closes).ewm(span=26).mean().iloc[-1]
                        dif = ema12 - ema26
                        dea = pd.Series([dif]).ewm(span=9).mean().iloc[-1]
                        result[prefix + 'macd_dif'] = dif
                        result[prefix + 'macd_dea'] = dea
                        result[prefix + 'macd_gold'] = dif > dea
                    else:
                        result[prefix + 'macd_dif'] = 0
                        result[prefix + 'macd_dea'] = 0
                        result[prefix + 'macd_gold'] = False
                else:
                    result[prefix + 'macd_dif'] = 0
                    result[prefix + 'macd_dea'] = 0
                    result[prefix + 'macd_gold'] = False
                
                # 连续上涨天数
                up_days = 0
                for j in range(i, min(i + 5, len(df))):
                    if j < len(df) - 1:
                        curr_close = float(df.iloc[-j]['close'])
                        prev_close = float(df.iloc[-j-1]['close'])
                        if curr_close > prev_close:
                            up_days += 1
                        else:
                            break
                result[prefix + 'up_days'] = up_days
                
                # 近3日/5日涨幅
                if len(df) >= i + 3:
                    close_3d = float(df.iloc[-i-3]['close'])
                    if close_3d > 0:
                        result[prefix + 'pct_3d'] = (result[prefix + 'close'] - close_3d) / close_3d * 100
                    else:
                        result[prefix + 'pct_3d'] = 0
                else:
                    result[prefix + 'pct_3d'] = 0
                    
                if len(df) >= i + 5:
                    close_5d = float(df.iloc[-i-5]['close'])
                    if close_5d > 0:
                        result[prefix + 'pct_5d'] = (result[prefix + 'close'] - close_5d) / close_5d * 100
                    else:
                        result[prefix + 'pct_5d'] = 0
                else:
                    result[prefix + 'pct_5d'] = 0
            
            # 消息面分析（涨停前3天内的新闻）
            try:
                news_start = (limit_up_dt - timedelta(days=5)).strftime("%Y-%m-%d")
                news_end = (limit_up_dt - timedelta(days=1)).strftime("%Y-%m-%d")
                news_impact = self.news_analyzer.get_news_impact_score(code, name)
                result['news_score'] = news_impact.get('score', 50)
                result['news_level'] = news_impact.get('level', '中性')
                result['news_reasons'] = '; '.join(news_impact.get('reasons', [])[:3])
            except Exception as e:
                result['news_score'] = 50
                result['news_level'] = '无数据'
                result['news_reasons'] = ''
            
            return result
            
        except Exception as e:
            print(f"分析 {name}({code}) 失败: {e}")
            return None
    
    def run_backtest(self, max_stocks=500):
        """运行回测分析"""
        print("=" * 60)
        print("涨停股票深度回测分析")
        print("=" * 60)
        
        # 获取涨停股票列表
        df = self.get_limit_up_stocks(days=180)
        if df is None or len(df) == 0:
            print("未获取到涨停股票数据")
            return
        
        print(f"\n共获取到 {len(df)} 条涨停记录")
        
        # 去重（同一股票多次涨停只取最近一次）
        if '代码' in df.columns:
            df = df.drop_duplicates(subset=['代码'], keep='first')
        elif 'code' in df.columns:
            df = df.drop_duplicates(subset=['code'], keep='first')
        
        print(f"去重后共 {len(df)} 只涨停股票")
        
        # 限制分析数量
        if len(df) > max_stocks:
            df = df.head(max_stocks)
            print(f"限制分析数量为 {max_stocks} 只")
        
        # 逐只分析
        results = []
        for idx, row in df.iterrows():
            if '代码' in row:
                code = str(row['代码']).zfill(6)
                name = row.get('名称', '')
                limit_up_date = row.get('date', row.get('涨停日期', ''))
            else:
                code = str(row.get('code', '')).zfill(6)
                name = row.get('name', '')
                limit_up_date = row.get('date', row.get('limit_up_date', ''))
            
            if not code or code == '000000':
                continue
            
            print(f"\n[{idx+1}/{len(df)}] 分析 {name}({code}) 涨停日期: {limit_up_date}")
            
            result = self.analyze_stock_before_limit_up(code, name, limit_up_date, days_before=2)
            if result:
                results.append(result)
                print(f"  ✓ 分析完成，涨停前1天涨幅: {result.get('d1_pct_change', 0):.2f}%, "
                      f"涨停前2天涨幅: {result.get('d2_pct_change', 0):.2f}%")
            
            # 避免请求过快
            time.sleep(0.3)
        
        # 保存结果
        if results:
            df_result = pd.DataFrame(results)
            output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      'data', 'limit_up_6months_deep_analysis.csv')
            df_result.to_csv(output_path, index=False, encoding='utf-8-sig')
            print(f"\n✓ 分析结果已保存到: {output_path}")
            print(f"  共分析 {len(results)} 只股票")
            
            # 生成统计报告
            self.generate_statistics(df_result)
        else:
            print("\n✗ 未分析到任何股票")
    
    def generate_statistics(self, df):
        """生成统计报告"""
        print("\n" + "=" * 60)
        print("涨停股票涨停前夕特征统计")
        print("=" * 60)
        
        print(f"\n总样本数: {len(df)}")
        
        # 涨停前1天统计
        print("\n【涨停前1天特征】")
        if 'd1_pct_change' in df.columns:
            print(f"  涨幅: 均值{df['d1_pct_change'].mean():.2f}%, 中位数{df['d1_pct_change'].median():.2f}%")
            print(f"    涨幅分布: <-3%占{(df['d1_pct_change'] < -3).mean()*100:.1f}%, "
                  f"-3%~0%占{((df['d1_pct_change'] >= -3) & (df['d1_pct_change'] < 0)).mean()*100:.1f}%, "
                  f"0%~3%占{((df['d1_pct_change'] >= 0) & (df['d1_pct_change'] < 3)).mean()*100:.1f}%, "
                  f">3%占{(df['d1_pct_change'] >= 3).mean()*100:.1f}%")
        
        if 'd1_amplitude' in df.columns:
            print(f"  振幅: 均值{df['d1_amplitude'].mean():.2f}%, 中位数{df['d1_amplitude'].median():.2f}%")
        
        if 'd1_turnover' in df.columns:
            print(f"  换手率: 均值{df['d1_turnover'].mean():.2f}%, 中位数{df['d1_turnover'].median():.2f}%")
        
        if 'd1_volume_ratio' in df.columns:
            print(f"  量比: 均值{df['d1_volume_ratio'].mean():.2f}, 中位数{df['d1_volume_ratio'].median():.2f}")
            print(f"    量比分布: <0.5占{(df['d1_volume_ratio'] < 0.5).mean()*100:.1f}%, "
                  f"0.5~1占{((df['d1_volume_ratio'] >= 0.5) & (df['d1_volume_ratio'] < 1)).mean()*100:.1f}%, "
                  f"1~2占{((df['d1_volume_ratio'] >= 1) & (df['d1_volume_ratio'] < 2)).mean()*100:.1f}%, "
                  f">2占{(df['d1_volume_ratio'] >= 2).mean()*100:.1f}%")
        
        if 'd1_ma_bullish' in df.columns:
            print(f"  均线多头排列: {(df['d1_ma_bullish']).mean()*100:.1f}%")
        
        if 'd1_above_ma20' in df.columns:
            print(f"  股价在MA20上方: {(df['d1_above_ma20']).mean()*100:.1f}%")
        
        if 'd1_macd_gold' in df.columns:
            print(f"  MACD金叉: {(df['d1_macd_gold']).mean()*100:.1f}%")
        
        if 'd1_up_days' in df.columns:
            print(f"  连续上涨天数: 均值{df['d1_up_days'].mean():.1f}天")
        
        # 涨停前2天统计
        print("\n【涨停前2天特征】")
        if 'd2_pct_change' in df.columns:
            print(f"  涨幅: 均值{df['d2_pct_change'].mean():.2f}%, 中位数{df['d2_pct_change'].median():.2f}%")
        
        if 'd2_amplitude' in df.columns:
            print(f"  振幅: 均值{df['d2_amplitude'].mean():.2f}%, 中位数{df['d2_amplitude'].median():.2f}%")
        
        if 'd2_turnover' in df.columns:
            print(f"  换手率: 均值{df['d2_turnover'].mean():.2f}%, 中位数{df['d2_turnover'].median():.2f}%")
        
        if 'd2_volume_ratio' in df.columns:
            print(f"  量比: 均值{df['d2_volume_ratio'].mean():.2f}, 中位数{df['d2_volume_ratio'].median():.2f}")
        
        # 消息面统计
        print("\n【消息面特征】")
        if 'news_score' in df.columns:
            print(f"  消息面评分: 均值{df['news_score'].mean():.1f}分")
            print(f"  消息面分布:")
            for level in ['利好', '偏利好', '中性', '偏利空', '利空', '无数据']:
                count = (df['news_level'] == level).sum()
                if count > 0:
                    print(f"    {level}: {count}只 ({count/len(df)*100:.1f}%)")
        
        # 价格分布
        print("\n【价格分布】")
        if 'd1_close' in df.columns:
            print(f"  涨停前1天收盘价: 均值{df['d1_close'].mean():.2f}元, 中位数{df['d1_close'].median():.2f}元")
            print(f"    价格分布: <5元占{(df['d1_close'] < 5).mean()*100:.1f}%, "
                  f"5~10元占{((df['d1_close'] >= 5) & (df['d1_close'] < 10)).mean()*100:.1f}%, "
                  f"10~20元占{((df['d1_close'] >= 10) & (df['d1_close'] < 20)).mean()*100:.1f}%, "
                  f">20元占{(df['d1_close'] >= 20).mean()*100:.1f}%")
        
        print("\n" + "=" * 60)
        print("回测分析完成！")
        print("=" * 60)


if __name__ == "__main__":
    backtest = LimitUpBacktest()
    backtest.run_backtest(max_stocks=300)
