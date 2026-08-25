#!/usr/bin/env python3
"""
生成股票名称映射表 JSON
从 Tushare 获取全量股票代码和名称，保存为 stock_name_map.json
"""
import os
import json
import sys

def main():
    # 如果映射表已存在，直接使用，避免重复调用接口触发频率限制
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(os.path.dirname(script_dir), "data")
    output_path = os.path.join(data_dir, "stock_name_map.json")
    if os.path.exists(output_path):
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            print(f"映射表已存在，跳过生成: {len(existing)} 只")
            return 0
        except Exception:
            pass

    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        print("未配置 TUSHARE_TOKEN，跳过映射表生成")
        return 0

    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.stock_basic(exchange='', list_status='L', fields='symbol,name')
        name_map = dict(zip(df['symbol'], df['name']))

        os.makedirs(data_dir, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(name_map, f, ensure_ascii=False)
        print(f"生成股票名称映射表: {len(name_map)} 只 -> {output_path}")
        return 0
    except Exception as e:
        print(f"生成映射表失败: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
