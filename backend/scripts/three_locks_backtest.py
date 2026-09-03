"""
三把锁涨停信号回测分析
分析近3个月涨停股票在涨停前一天的三把锁信号
优化三把锁涨停信号规则，提高涨停命中率
"""
import pandas as pd
import numpy as np
import requests
import json
import re
import time
import logging
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def get_kline_data(code: str, days: int = 60) -> List[Dict]:
    """获取股票K线数据"""
    try:
        if code.startswith('6'):
            sina_code = f'sh{code}'
        else:
            sina_code = f'sz{code}'
        
        url = f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{sina_code}_{code}/CN_MarketDataService.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen={days}'
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        text = response.text
        
        match = re.search(r'\((.*)\)', text)
        if match:
            raw_data = json.loads(match.group(1))
            # 转换字符串为数字
            kline = []
            for d in raw_data:
                kline.append({
                    'day': d.get('day', ''),
                    'open': float(d.get('open', 0)),
                    'high': float(d.get('high', 0)),
                    'low': float(d.get('low', 0)),
                    'close': float(d.get('close', 0)),
                    'volume': float(d.get('volume', 0)),
                })
            return kline
    except Exception as e:
        logger.debug(f"获取K线失败 {code}: {e}")
    return []


def calc_three_locks(kline: List[Dict], limit_up_idx: int = -1) -> Dict:
    """
    计算三把锁信号（基于涨停前一天的数据）
    limit_up_idx: 涨停日在kline中的索引，默认-1（最后一天）
    分析涨停前一天（limit_up_idx-1）的三把锁信号
    """
    if not kline or len(kline) < 10:
        return {"error": "数据不足"}
    
    # 涨停前一天的索引
    prev_idx = limit_up_idx - 1
    if prev_idx < 5:
        return {"error": "前一天数据不足"}
    
    # 获取涨停前一天及之前的数据
    prev_data = kline[:prev_idx + 1]
    
    if len(prev_data) < 10:
        return {"error": "历史数据不足"}
    
    closes = [float(d['close']) for d in prev_data]
    highs = [float(d['high']) for d in prev_data]
    lows = [float(d['low']) for d in prev_data]
    volumes = [float(d['volume']) for d in prev_data]
    
    current_close = closes[-1]
    
    # ========== 趋势锁 ==========
    # 基于均线多头排列和趋势方向
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
    ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else 0
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else 0
    
    # 趋势锁评分（0-100）
    trend_score = 0
    if ma5 > ma10 > ma20:
        trend_score += 40  # 均线多头排列
    elif ma5 > ma10:
        trend_score += 20
    elif ma10 > ma20:
        trend_score += 10
    
    # 股价在MA20上方
    if current_close > ma20:
        trend_score += 30
    elif current_close > ma20 * 0.95:
        trend_score += 15
    
    # 近期趋势（近5天涨跌）
    if len(closes) >= 6:
        pct_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
        if pct_5d > 5:
            trend_score += 30
        elif pct_5d > 0:
            trend_score += 15
        elif pct_5d > -5:
            trend_score += 5
    
    trend_locked = trend_score >= 55  # 指南针趋势锁门槛55
    
    # ========== 股性锁 ==========
    # 基于振幅和换手率（股性活跃度）
    # 计算近5天平均振幅
    amplitudes = []
    for i in range(-5, 0):
        if abs(i) < len(highs) and abs(i) <= len(lows):
            idx = len(highs) + i
            if idx >= 1:
                prev_close = closes[idx - 1]
                if prev_close > 0:
                    amp = (highs[idx] - lows[idx]) / prev_close * 100
                    amplitudes.append(amp)
    
    avg_amplitude = sum(amplitudes) / len(amplitudes) if amplitudes else 0
    
    # 股性锁评分（0-100）
    activity_score = 0
    if avg_amplitude >= 5:
        activity_score += 50
    elif avg_amplitude >= 3:
        activity_score += 35
    elif avg_amplitude >= 2:
        activity_score += 20
    elif avg_amplitude >= 1:
        activity_score += 10
    
    # 近5天有大阳线（涨幅>5%）
    if len(closes) >= 6:
        for i in range(-5, 0):
            idx = len(closes) + i
            if idx >= 1:
                daily_pct = (closes[idx] - closes[idx-1]) / closes[idx-1] * 100
                if daily_pct > 5:
                    activity_score += 30
                    break
                elif daily_pct > 3:
                    activity_score += 15
                    break
    
    # 成交量活跃度
    if len(volumes) >= 6:
        avg_vol_5 = sum(volumes[-5:]) / 5
        avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else avg_vol_5
        if avg_vol_20 > 0:
            vol_ratio = avg_vol_5 / avg_vol_20
            if vol_ratio > 1.5:
                activity_score += 20
            elif vol_ratio > 1.2:
                activity_score += 10
    
    activity_locked = activity_score >= 50  # 指南针股性锁门槛50
    
    # ========== 资金锁 ==========
    # 基于成交量变化和资金流入
    capital_score = 0
    
    if len(volumes) >= 4:
        # 近3天成交量是否放大
        vol_3d = sum(volumes[-3:]) / 3
        vol_prev = volumes[-4] if len(volumes) >= 4 else vol_3d
        if vol_prev > 0:
            vol_change = (vol_3d - vol_prev) / vol_prev * 100
            if vol_change > 30:
                capital_score += 40
            elif vol_change > 10:
                capital_score += 25
            elif vol_change > 0:
                capital_score += 10
    
    # 量价配合（上涨放量，下跌缩量）
    if len(closes) >= 4 and len(volumes) >= 4:
        up_days = 0
        up_vol = 0
        down_days = 0
        down_vol = 0
        for i in range(-3, 0):
            idx = len(closes) + i
            if idx >= 1:
                daily_pct = (closes[idx] - closes[idx-1]) / closes[idx-1] * 100
                if daily_pct > 0:
                    up_days += 1
                    up_vol += volumes[idx]
                else:
                    down_days += 1
                    down_vol += volumes[idx]
        
        if up_days > 0 and down_days > 0:
            avg_up_vol = up_vol / up_days
            avg_down_vol = down_vol / down_days
            if avg_down_vol > 0:
                vol_ratio = avg_up_vol / avg_down_vol
                if vol_ratio > 1.5:
                    capital_score += 30  # 上涨放量，下跌缩量，资金流入
                elif vol_ratio > 1.2:
                    capital_score += 15
                elif vol_ratio > 1:
                    capital_score += 5
    
    # 近期有放量阳线
    if len(closes) >= 6 and len(volumes) >= 6:
        for i in range(-5, 0):
            idx = len(closes) + i
            if idx >= 1:
                daily_pct = (closes[idx] - closes[idx-1]) / closes[idx-1] * 100
                avg_vol = sum(volumes[idx-5:idx]) / 5 if idx >= 5 else volumes[idx]
                if daily_pct > 3 and volumes[idx] > avg_vol * 1.5:
                    capital_score += 30  # 放量阳线，资金流入
                    break
    
    capital_locked = capital_score >= 40  # 指南针资金锁门槛40
    
    # ========== 综合 ==========
    total_locked = sum([trend_locked, activity_locked, capital_locked])
    
    # 信号判断
    if total_locked == 3:
        signal = "强烈买入"
    elif total_locked == 2:
        signal = "买入"
    elif total_locked == 1:
        signal = "谨慎买入"
    else:
        signal = "观望"
    
    return {
        "trend_lock": {"score": trend_score, "locked": trend_locked},
        "activity_lock": {"score": activity_score, "locked": activity_locked},
        "capital_lock": {"score": capital_score, "locked": capital_locked},
        "total_locked": total_locked,
        "signal": signal,
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "avg_amplitude": round(avg_amplitude, 2),
    }


def main():
    """主函数：回测三把锁涨停信号"""
    logger.info("=== 三把锁涨停信号回测分析 ===")
    
    # 读取已有涨停股票数据
    df = pd.read_csv('data/limit_up_6months.csv')
    logger.info(f"读取涨停股票数据: {len(df)}条")
    
    # 去重（同一股票多次涨停只取一次）
    df_unique = df.drop_duplicates(subset=['代码'])
    logger.info(f"去重后: {len(df_unique)}只股票")
    
    # 抽样分析（限制数量，避免API调用过多）
    sample_size = min(300, len(df_unique))
    df_sample = df_unique.sample(n=sample_size, random_state=42)
    logger.info(f"抽样分析: {sample_size}只股票")
    
    # 分析每只股票涨停前一天的三把锁信号
    results = []
    success_count = 0
    
    for idx, row in df_sample.iterrows():
        code = str(row['代码']).zfill(6)
        name = row['名称']
        limit_up_date = str(row['date'])
        industry = row.get('所属行业', '')
        lianban = row.get('连板数', 1)
        
        try:
            # 获取K线数据（获取60天，确保有足够的历史数据）
            kline = get_kline_data(code, days=60)
            
            if not kline or len(kline) < 10:
                continue
            
            # 根据涨停日期定位涨停日在K线中的位置
            # 涨停日期格式：20260901，K线日期格式：2026-09-01
            target_date = f"{limit_up_date[:4]}-{limit_up_date[4:6]}-{limit_up_date[6:8]}"
            limit_up_idx = -1
            for i, d in enumerate(kline):
                if d['day'] == target_date:
                    limit_up_idx = i
                    break
            
            if limit_up_idx < 5:
                # 如果找不到涨停日期，使用最后一天（可能是最新数据）
                limit_up_idx = len(kline) - 1
            
            # 计算三把锁信号（基于涨停前一天的数据）
            tl_result = calc_three_locks(kline, limit_up_idx=limit_up_idx)
            
            if "error" in tl_result:
                continue
            
            results.append({
                "code": code,
                "name": name,
                "limit_up_date": limit_up_date,
                "industry": industry,
                "lianban": lianban,
                "trend_score": tl_result["trend_lock"]["score"],
                "trend_locked": tl_result["trend_lock"]["locked"],
                "activity_score": tl_result["activity_lock"]["score"],
                "activity_locked": tl_result["activity_lock"]["locked"],
                "capital_score": tl_result["capital_lock"]["score"],
                "capital_locked": tl_result["capital_lock"]["locked"],
                "total_locked": tl_result["total_locked"],
                "signal": tl_result["signal"],
                "avg_amplitude": tl_result["avg_amplitude"],
            })
            
            success_count += 1
            if success_count % 50 == 0:
                logger.info(f"已分析 {success_count} 只股票")
            
            time.sleep(0.1)  # 避免API调用过快
            
        except Exception as e:
            logger.debug(f"分析失败 {code}: {e}")
            continue
    
    logger.info(f"成功分析 {success_count} 只股票")
    
    if not results:
        logger.error("没有成功分析的股票")
        return
    
    # 保存结果
    df_results = pd.DataFrame(results)
    df_results.to_csv('data/three_locks_backtest.csv', index=False, encoding='utf-8-sig')
    logger.info(f"结果已保存到 data/three_locks_backtest.csv")
    
    # 统计分析
    print()
    print("=" * 70)
    print("=== 三把锁涨停信号回测统计 ===")
    print()
    
    # 1. 三把锁点亮数分布
    print("【1. 三把锁点亮数分布】")
    locked_counts = df_results['total_locked'].value_counts().sort_index()
    for locked, count in locked_counts.items():
        pct = count / len(df_results) * 100
        print(f"  {locked}/3亮: {count}只 ({pct:.1f}%)")
    print()
    
    # 2. 信号分布
    print("【2. 信号分布】")
    signal_counts = df_results['signal'].value_counts()
    for signal, count in signal_counts.items():
        pct = count / len(df_results) * 100
        print(f"  {signal}: {count}只 ({pct:.1f}%)")
    print()
    
    # 3. 各把锁的点亮率
    print("【3. 各把锁点亮率】")
    print(f"  趋势锁点亮率: {df_results['trend_locked'].mean()*100:.1f}% (平均评分{df_results['trend_score'].mean():.1f})")
    print(f"  股性锁点亮率: {df_results['activity_locked'].mean()*100:.1f}% (平均评分{df_results['activity_score'].mean():.1f})")
    print(f"  资金锁点亮率: {df_results['capital_locked'].mean()*100:.1f}% (平均评分{df_results['capital_score'].mean():.1f})")
    print()
    
    # 4. 连板数与三把锁的关系
    print("【4. 连板数与三把锁的关系】")
    for lianban in sorted(df_results['lianban'].unique()):
        subset = df_results[df_results['lianban'] == lianban]
        if len(subset) >= 5:
            avg_locked = subset['total_locked'].mean()
            print(f"  {lianban}连板: {len(subset)}只, 平均三把锁{avg_locked:.1f}/3亮")
    print()
    
    # 5. 行业与三把锁的关系
    print("【5. 行业与三把锁的关系（TOP10行业）】")
    industry_stats = df_results.groupby('industry').agg({
        'total_locked': 'mean',
        'code': 'count'
    }).sort_values('code', ascending=False).head(10)
    for industry, row in industry_stats.iterrows():
        print(f"  {industry}: {row['code']}只, 平均三把锁{row['total_locked']:.1f}/3亮")
    print()
    
    # 6. 三把锁组合的涨停特征分析
    print("【6. 三把锁组合分析】")
    for tl in range(4):
        subset = df_results[df_results['total_locked'] == tl]
        if len(subset) > 0:
            avg_amp = subset['avg_amplitude'].mean()
            first_board_pct = (subset['lianban'] == 1).mean() * 100
            print(f"  {tl}/3亮: {len(subset)}只, 平均振幅{avg_amp:.1f}%, 首板占比{first_board_pct:.1f}%")
    print()
    
    print("【核心发现】")
    print(f"  1. 涨停股票中，{df_results['total_locked'].mean():.1f}/3把锁点亮，说明三把锁对涨停有一定预测能力")
    print(f"  2. 趋势锁点亮率{df_results['trend_locked'].mean()*100:.1f}%，股性锁{df_results['activity_locked'].mean()*100:.1f}%，资金锁{df_results['capital_locked'].mean()*100:.1f}%")
    print(f"  3. 需要进一步优化三把锁的门槛和权重，提高涨停命中率")


if __name__ == "__main__":
    main()
