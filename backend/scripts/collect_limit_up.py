"""
收集今日涨停股票数据
"""
import requests
import json
import os
from datetime import datetime

def collect_limit_up_stocks():
    """收集今日涨停股票数据"""
    today = datetime.now().strftime('%Y%m%d')
    url = f'http://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt:asc&date={today}'

    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('data') and data['data'].get('pool'):
            stocks = data['data']['pool']
            print(f'今天涨停股票数量: {len(stocks)}')

            # 确保data目录存在
            os.makedirs('data', exist_ok=True)

            output_file = f'data/limit_up_{today}.json'
            with open(output_file, 'w') as f:
                json.dump(stocks, f, ensure_ascii=False, indent=2)
            print(f'已保存到 {output_file}')
            return stocks
        else:
            print('未获取到涨停股票数据')
            print(f'响应: {json.dumps(data, ensure_ascii=False)[:500]}')
            return []
    except Exception as e:
        print(f'获取涨停股票失败: {e}')
        return []

if __name__ == '__main__':
    collect_limit_up_stocks()
