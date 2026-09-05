"""
LLM 深度分析模块
基于 OpenAI 兼容接口，将五维分析结果交给 LLM 做综合解读和操作建议
"""
import logging
import json
from typing import Dict, Optional
from backend.config import Config

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("openai 库未安装，LLM 分析不可用")


SYSTEM_PROMPT = """你是一位资深A股投资分析师，擅长技术分析、基本面研究和资金面解读。
请基于提供的五维分析数据，给出客观、理性的投资分析。
要求：
1. 综合技术面、基本面、资金面、概念热点给出整体判断
2. 给出明确的操作建议（买入/持有/观望/卖出）和理由
3. 指出关键风险点
4. 语言简洁专业，不超过300字
5. 不要承诺收益，提醒投资有风险
"""


def build_user_prompt(stock_info: Dict, technical: Dict, fundamental: Dict,
                      capital: Dict, concept: Dict) -> str:
    """构建给 LLM 的分析数据"""
    return f"""
【股票基本信息】
代码：{stock_info.get('code', '')}
名称：{stock_info.get('name', '')}
现价：{stock_info.get('price', '')}
涨跌幅：{stock_info.get('pct_change', '')}%

【技术面分析】
趋势：{technical.get('trend', {}).get('trend', '未知')}
技术评分：{technical.get('technical_score', 50)}/100
MACD：DIF={technical.get('macd', {}).get('dif', 0):.4f}, DEA={technical.get('macd', {}).get('dea', 0):.4f}
RSI：{technical.get('rsi', {}).get('rsi6', technical.get('rsi', {}).get('value', 0))}
KDJ：K={technical.get('kdj', {}).get('k', 0):.1f}, D={technical.get('kdj', {}).get('d', 0):.1f}
支撑位：{technical.get('support_resistance', {}).get('support_1', 'N/A')}
压力位：{technical.get('support_resistance', {}).get('resistance_1', 'N/A')}
量能：{technical.get('volume', {}).get('volume_status', '未知')}
技术面结论：{'；'.join(technical.get('conclusions', [])[:5])}

【基本面分析】
基本面评分：{fundamental.get('score', 50)}/100
PE：{fundamental.get('data', {}).get('pe', 'N/A')}
PB：{fundamental.get('data', {}).get('pb', 'N/A')}
ROE：{fundamental.get('data', {}).get('roe', 'N/A')}%
营收同比：{fundamental.get('data', {}).get('revenue_yoy', 'N/A')}%
净利润同比：{fundamental.get('data', {}).get('profit_yoy', 'N/A')}%
基本面结论：{'；'.join(fundamental.get('conclusions', [])[:5])}

【资金面分析】
资金评分：{capital.get('score', 50)}/100
主力净流入：{capital.get('data', {}).get('main_net_inflow', 0)/1e4:.0f}万
主力净占比：{capital.get('data', {}).get('main_net_pct', 0)}%
近5日主力净流入：{capital.get('data', {}).get('main_net_inflow_5d', 0)/1e4:.0f}万
资金面结论：{'；'.join(capital.get('conclusions', [])[:3])}

【概念热点分析】
概念评分：{concept.get('score', 50)}/100
所属概念：{'、'.join(concept.get('concepts', []))}
热门概念匹配：{json.dumps(concept.get('matched_hot', []), ensure_ascii=False)}
概念结论：{'；'.join(concept.get('conclusions', [])[:3])}

请综合以上五维数据，给出你的分析和操作建议。
"""


def llm_deep_analyze(stock_info: Dict, technical: Dict, fundamental: Dict,
                     capital: Dict, concept: Dict) -> Optional[Dict[str, str]]:
    """
    LLM 深度分析
    返回 {"summary": "...", "suggestion": "...", "risk": "..."} 或 None（失败时）
    """
    if not Config.ENABLE_LLM or not Config.LLM_API_KEY or not OPENAI_AVAILABLE:
        logger.info("LLM 分析未启用或缺少配置")
        return None

    try:
        client = OpenAI(
            api_key=Config.LLM_API_KEY,
            base_url=Config.LLM_BASE_URL,
        )

        user_prompt = build_user_prompt(stock_info, technical, fundamental, capital, concept)

        response = client.chat.completions.create(
            model=Config.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=800,
        )

        content = response.choices[0].message.content.strip()

        # 尝试结构化解析，如果失败则整体作为 summary
        result = {"raw": content}
        lines = content.split("\n")
        result["summary"] = content

        # 简单分段
        for line in lines:
            if "操作建议" in line or "建议" in line:
                result["suggestion"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            if "风险" in line:
                result["risk"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()

        return result

    except Exception as e:
        logger.error(f"LLM 分析失败: {e}")
        return None
