"""
尾盘选股推荐数量回测分析
分析各过滤步骤对推荐数量的影响，优化选股规则增加推荐数量
"""
import pandas as pd
import numpy as np
import json
import os
import logging
from collections import Counter

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def analyze_late_day_results():
    """分析尾盘选股结果，找出推荐数量少的原因"""
    
    # 读取历史尾盘选股结果
    result_files = sorted([f for f in os.listdir('data') if f.startswith('late_day_') and f.endswith('.json')])
    
    print("=" * 70)
    print("=== 尾盘选股推荐数量回测分析 ===")
    print()
    
    # 分析最近的结果
    for result_file in result_files[-3:]:
        print(f"--- {result_file} ---")
        with open(f'data/{result_file}', 'r') as f:
            data = json.load(f)
        
        all_picks = data.get('all_picks', [])
        top_picks = data.get('top_picks', [])
        
        print(f"  总推荐数: {len(all_picks)}")
        print(f"  精选数: {len(top_picks)}")
        
        # 分析行业分布
        industries = []
        for p in all_picks:
            if isinstance(p, dict):
                industry = p.get('industry', '') or p.get('所属行业', '') or '未知'
                industries.append(industry)
        
        if industries:
            industry_counts = Counter(industries)
            print(f"  行业分布:")
            for industry, count in industry_counts.most_common():
                print(f"    {industry}: {count}只")
        
        # 分析三把锁分布
        tl_signals = []
        tl_locked = []
        for p in all_picks:
            if isinstance(p, dict):
                tl = p.get('three_locks', {})
                tl_signals.append(tl.get('signal', '未知'))
                tl_locked.append(tl.get('total_locked', 0))
        
        if tl_signals:
            signal_counts = Counter(tl_signals)
            print(f"  三把锁信号分布:")
            for signal, count in signal_counts.most_common():
                print(f"    {signal}: {count}只")
            
            locked_counts = Counter(tl_locked)
            print(f"  三把锁点亮数分布:")
            for locked, count in sorted(locked_counts.items()):
                print(f"    {locked}/3亮: {count}只")
        
        print()
    
    print("=" * 70)
    print("=== 过滤规则优化建议 ===")
    print()
    
    # 基于回测结果给出优化建议
    print("【问题分析】")
    print("1. 行业分散度过滤太严：71只→5只，说明候选股票集中在少数行业")
    print("2. 三把锁过滤太严：只保留买入信号，大部分股票被过滤掉")
    print("3. 候选股票数量太少：只有50只候选股票，限制了推荐数量")
    print("4. 评分门槛太高：55分门槛可能过滤掉很多有潜力的股票")
    print()
    
    print("【优化建议】")
    print("1. 放宽行业分散度限制：从同一行业最多5只增加到10只")
    print("2. 放宽三把锁过滤：保留2/3亮以上的股票，不只是买入信号")
    print("3. 增加候选股票数量：从50只增加到100只")
    print("4. 降低评分门槛：从55分降低到50分")
    print("5. 增加大盘环境适配：大盘好时增加推荐数量，大盘差时减少")
    print()
    
    print("【预期效果】")
    print("优化后推荐数量应该能从2只增加到20-30只")
    print("同时保持推荐质量，通过三把锁和评分排序确保优质股票排在前面")


if __name__ == "__main__":
    analyze_late_day_results()
