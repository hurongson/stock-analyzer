"""
运行每日复盘分析并推送飞书
"""
import sys
import os
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.daily_review import daily_review_analyzer


def run_daily_review():
    """运行每日复盘分析"""
    # 运行复盘分析
    print('开始每日复盘分析...')
    result = daily_review_analyzer.analyze()
    report = daily_review_analyzer.generate_report(result)

    # 保存报告到文件
    os.makedirs('data', exist_ok=True)
    with open('data/review_report.txt', 'w', encoding='utf-8') as f:
        f.write(report)

    print('复盘分析完成')
    print(f'报告长度: {len(report)}字符')

    # 飞书推送
    no_push = os.environ.get('NO_PUSH', 'false')
    if no_push != 'true':
        try:
            webhook = os.environ.get('FEISHU_WEBHOOK_URL', '')
            if webhook:
                # 分段发送（飞书消息长度限制）
                max_length = 4000
                segments = []
                current = ''
                for line in report.split('\n'):
                    if len(current) + len(line) + 1 > max_length:
                        segments.append(current)
                        current = line
                    else:
                        current += '\n' + line
                if current:
                    segments.append(current)

                for i, seg in enumerate(segments):
                    if len(segments) > 1:
                        title = f'📊 每日复盘分析报告 ({i+1}/{len(segments)})'
                    else:
                        title = '📊 每日复盘分析报告'

                    payload = {
                        'msg_type': 'text',
                        'content': {
                            'text': f'{title}\n\n{seg}'
                        }
                    }
                    resp = requests.post(webhook, json=payload, timeout=10)
                    print(f'飞书推送段{i+1}: {resp.status_code}')

                print('飞书推送完成')
            else:
                print('未配置飞书Webhook，跳过推送')
        except Exception as e:
            print(f'飞书推送失败: {e}')
    else:
        print('已禁用飞书推送')

    return result


if __name__ == '__main__':
    run_daily_review()
