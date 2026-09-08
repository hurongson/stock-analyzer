"""
反向筛选模块（空头模式）
基于博主"WorkBuddy股票淘汰器"逻辑实现

核心思想：不是寻找值得买的股票，而是想办法淘汰股票
AI最适合普通散户的用法：不是帮你发现更多机会，而是帮你少犯"什么都想买"的错

七大淘汰规则：
1. 真实变化检查：只有价格变化没有新事实的淘汰
2. 变化量级检查：订单/营收、回购/市值等比例太小的淘汰
3. 市场预期检查：已经人尽皆知的降级
4. 财务验证检查：财务数据不支持故事的降级
5. 历史兑现检查：管理层画饼不兑现的降级
6. 可理解性检查：看不懂的降级
7. 反证检查：至少3条反证

风险专家一票否决权：
- 重要财务数据无法解释
- 核心信息来源无法验证
- 管理层承诺连续明显失信
- 重大风险尚未弄清
- 交易逻辑完全依赖单一传闻

三级漏斗：
- 观察池：有一点变化
- 研究池：有明确基本面问题值得继续验证
- 核心池：真正看得懂的几家
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class ReverseScreener:
    """反向筛选器（空头模式）"""

    def __init__(self):
        self.data_dir = "data"
        self.elimination_history_file = os.path.join(self.data_dir, "reverse_elimination_history.json")
        self.elimination_history = self._load_elimination_history()

    def _load_elimination_history(self) -> Dict:
        """加载淘汰历史记录"""
        if os.path.exists(self.elimination_history_file):
            try:
                with open(self.elimination_history_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载淘汰历史失败: {e}")
        return {}

    def _save_elimination_history(self):
        """保存淘汰历史记录"""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.elimination_history_file, "w") as f:
                json.dump(self.elimination_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存淘汰历史失败: {e}")

    def screen(self, stocks: List[Dict], date: Optional[str] = None) -> Dict:
        """
        执行反向筛选（空头模式）

        Args:
            stocks: 候选股票列表
            date: 分析日期

        Returns:
            反向筛选结果，包含淘汰股、保留股、淘汰原因统计
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"开始反向筛选（空头模式）: {len(stocks)}只候选股票")

        result = {
            "date": date,
            "total_candidates": len(stocks),
            "eliminated": [],      # 被淘汰的股票
            "downgraded": [],      # 被降级的股票
            "kept": [],            # 保留的股票
            "elimination_reasons": {},  # 淘汰原因统计
            "veto_stocks": [],     # 风险一票否决的股票
            "three_level_funnel": {
                "observation_pool": [],   # 观察池
                "research_pool": [],      # 研究池
                "core_pool": [],          # 核心池
            },
            "summary": "",
        }

        # 对每只股票执行7大淘汰规则检查
        for stock in stocks:
            if not isinstance(stock, dict):
                continue

            code = stock.get("code", "")
            name = stock.get("name", "")

            # 执行7大淘汰规则检查
            check_result = self._check_elimination_rules(stock, date)

            # 风险一票否决检查
            veto_result = self._check_veto(stock, check_result)

            stock["reverse_screen"] = check_result
            stock["reverse_veto"] = veto_result

            # 分类
            if veto_result["vetoed"]:
                # 风险一票否决
                result["veto_stocks"].append(stock)
                result["eliminated"].append(stock)
                for reason in veto_result["veto_reasons"]:
                    result["elimination_reasons"][reason] = result["elimination_reasons"].get(reason, 0) + 1
            elif check_result["elimination_score"] >= 60:
                # 高淘汰分，直接淘汰
                result["eliminated"].append(stock)
                for reason in check_result["elimination_reasons"]:
                    result["elimination_reasons"][reason] = result["elimination_reasons"].get(reason, 0) + 1
            elif check_result["elimination_score"] >= 30:
                # 中等淘汰分，降级
                result["downgraded"].append(stock)
            else:
                # 低淘汰分，保留
                result["kept"].append(stock)

        # 三级漏斗分类
        self._classify_three_level_funnel(result)

        # 生成总结
        result["summary"] = self._generate_summary(result)

        # 保存淘汰历史
        self._update_elimination_history(result, date)

        logger.info(f"反向筛选完成: 淘汰{len(result['eliminated'])}只, 降级{len(result['downgraded'])}只, 保留{len(result['kept'])}只")
        return result

    def _check_elimination_rules(self, stock: Dict, date: str) -> Dict:
        """
        执行7大淘汰规则检查

        Returns:
            检查结果，包含淘汰分、淘汰原因、各规则得分
        """
        result = {
            "elimination_score": 0,  # 淘汰分，越高越应该淘汰
            "elimination_reasons": [],
            "rule_scores": {},
            "details": {},
        }

        code = stock.get("code", "")
        name = stock.get("name", "")

        # 规则1：真实变化检查（只有价格变化没有新事实的淘汰）
        rule1_score = self._check_real_change(stock)
        result["rule_scores"]["real_change"] = rule1_score
        if rule1_score >= 20:
            result["elimination_reasons"].append("纯价格异动，无新增可验证事实")
        result["elimination_score"] += rule1_score

        # 规则2：变化量级检查（比例太小的淘汰）
        rule2_score = self._check_change_magnitude(stock)
        result["rule_scores"]["change_magnitude"] = rule2_score
        if rule2_score >= 15:
            result["elimination_reasons"].append("信息量级太小，对公司影响有限")
        result["elimination_score"] += rule2_score

        # 规则3：市场预期检查（已经人尽皆知的降级）
        rule3_score = self._check_market_expectation(stock)
        result["rule_scores"]["market_expectation"] = rule3_score
        if rule3_score >= 15:
            result["elimination_reasons"].append("市场预期已经很高，好公司≠好价格")
        result["elimination_score"] += rule3_score

        # 规则4：财务验证检查（财务不支持故事的降级）
        rule4_score = self._check_financial_validation(stock)
        result["rule_scores"]["financial_validation"] = rule4_score
        if rule4_score >= 15:
            result["elimination_reasons"].append("财务数据不支持当前叙事")
        result["elimination_score"] += rule4_score

        # 规则5：历史兑现检查（管理层画饼不兑现的降级）
        rule5_score = self._check_history_fulfillment(stock, code)
        result["rule_scores"]["history_fulfillment"] = rule5_score
        if rule5_score >= 10:
            result["elimination_reasons"].append("管理层历史兑现率低")
        result["elimination_score"] += rule5_score

        # 规则6：可理解性检查（看不懂的降级）
        rule6_score = self._check_understandability(stock)
        result["rule_scores"]["understandability"] = rule6_score
        if rule6_score >= 10:
            result["elimination_reasons"].append("业务/财务复杂，难以形成清晰认知")
        result["elimination_score"] += rule6_score

        # 规则7：反证检查（至少3条反证）
        rule7_score = self._check_counter_evidence(stock)
        result["rule_scores"]["counter_evidence"] = rule7_score
        if rule7_score >= 10:
            result["elimination_reasons"].append("存在较多反证，乐观假设存疑")
        result["elimination_score"] += rule7_score

        return result

    def _check_real_change(self, stock: Dict) -> int:
        """
        规则1：真实变化检查
        只有价格变化没有新事实的淘汰（20分）

        检查：
        - 是否有新公告
        - 是否有业绩变化
        - 是否有新订单
        - 是否有客户变化
        - 是否有行业新数据
        """
        score = 0

        # 检查是否有公告/新闻（简化：基于股票数据中的news字段）
        has_news = stock.get("has_news", False)
        has_announcement = stock.get("has_announcement", False)
        has_order_change = stock.get("has_order_change", False)
        has_performance_change = stock.get("has_performance_change", False)

        # 如果没有任何新信息，只有价格变化，给高分
        if not any([has_news, has_announcement, has_order_change, has_performance_change]):
            score += 20

        # 检查是否是纯概念炒作（没有基本面支撑）
        is_pure_concept = stock.get("is_pure_concept", False)
        if is_pure_concept:
            score += 10

        return min(score, 25)

    def _check_change_magnitude(self, stock: Dict) -> int:
        """
        规则2：变化量级检查
        比例太小的淘汰（15分）

        检查：
        - 订单/营收比例
        - 回购/市值比例
        - 减持/总股本比例
        - 新增利润/历史利润比例
        - 新业务收入/总收入比例
        """
        score = 0

        # 订单占营收比例
        order_revenue_ratio = stock.get("order_revenue_ratio", None)
        if order_revenue_ratio is not None:
            if order_revenue_ratio < 0.01:  # 小于1%
                score += 15
            elif order_revenue_ratio < 0.05:  # 小于5%
                score += 8

        # 回购占市值比例
        buyback_market_ratio = stock.get("buyback_market_ratio", None)
        if buyback_market_ratio is not None:
            if buyback_market_ratio < 0.005:  # 小于0.5%
                score += 10

        # 新业务收入占比
        new_business_ratio = stock.get("new_business_ratio", None)
        if new_business_ratio is not None:
            if new_business_ratio < 0.03:  # 小于3%
                score += 10
            elif new_business_ratio < 0.1:  # 小于10%
                score += 5

        return min(score, 20)

    def _check_market_expectation(self, stock: Dict) -> int:
        """
        规则3：市场预期检查
        已经人尽皆知的降级（15分）

        检查：
        - 机构调研数量
        - 研报数量
        - 股价涨幅
        - 估值水平
        - 成交量异常
        """
        score = 0

        # 近期涨幅（30天）
        price_change_30d = stock.get("price_change_30d", None)
        if price_change_30d is not None:
            if price_change_30d > 0.5:  # 涨幅超过50%
                score += 10
            elif price_change_30d > 0.3:  # 涨幅超过30%
                score += 5

        # 估值水平（PE）
        pe_ratio = stock.get("pe_ratio", None)
        if pe_ratio is not None:
            if pe_ratio > 100:  # PE超过100
                score += 8
            elif pe_ratio > 50:  # PE超过50
                score += 4

        # 机构关注度
        institution_attention = stock.get("institution_attention", None)
        if institution_attention is not None:
            if institution_attention == "极高":
                score += 8
            elif institution_attention == "高":
                score += 4

        # 换手率异常（过高说明交易拥挤）
        turnover = stock.get("turnover", 0)
        if turnover > 25:  # 换手率超过25%
            score += 5

        return min(score, 20)

    def _check_financial_validation(self, stock: Dict) -> int:
        """
        规则4：财务验证检查
        财务数据不支持故事的降级（15分）

        检查：
        - 收入增长 vs 利润增长
        - 扣非利润 vs 净利润
        - 经营现金流 vs 利润
        - 应收账款变化
        - 存货变化
        - 毛利率变化
        """
        score = 0

        # 净利润增长但扣非利润不增长
        net_profit_growth = stock.get("net_profit_growth", None)
        deducted_profit_growth = stock.get("deducted_profit_growth", None)
        if net_profit_growth is not None and deducted_profit_growth is not None:
            if net_profit_growth > 0.3 and deducted_profit_growth < 0.1:
                score += 10  # 净利润增长30%+，但扣非只增长10%以下

        # 经营现金流下降
        operating_cashflow_change = stock.get("operating_cashflow_change", None)
        if operating_cashflow_change is not None:
            if operating_cashflow_change < -0.2:  # 经营现金流下降20%+
                score += 8

        # 应收账款增长快于收入增长
        receivables_growth = stock.get("receivables_growth", None)
        revenue_growth = stock.get("revenue_growth", None)
        if receivables_growth is not None and revenue_growth is not None:
            if receivables_growth > revenue_growth * 2:
                score += 6  # 应收增长是收入增长的2倍以上

        # 存货增长快于收入增长
        inventory_growth = stock.get("inventory_growth", None)
        if inventory_growth is not None and revenue_growth is not None:
            if inventory_growth > revenue_growth * 1.5:
                score += 5  # 存货增长是收入增长的1.5倍以上

        # 毛利率下降
        gross_margin_change = stock.get("gross_margin_change", None)
        if gross_margin_change is not None:
            if gross_margin_change < -0.02:  # 毛利率下降2个百分点以上
                score += 5

        return min(score, 20)

    def _check_history_fulfillment(self, stock: Dict, code: str) -> int:
        """
        规则5：历史兑现检查
        管理层画饼不兑现的降级（10分）

        检查：
        - 管理层过去承诺的兑现情况
        - 产能投产是否延期
        - 新客户放量是否兑现
        - 毛利率改善是否兑现
        """
        score = 0

        # 从淘汰历史中查询该股票的历史兑现记录
        if code in self.elimination_history:
            history = self.elimination_history[code]
            fulfillment_rate = history.get("fulfillment_rate", None)
            if fulfillment_rate is not None:
                if fulfillment_rate < 0.3:  # 兑现率低于30%
                    score += 10
                elif fulfillment_rate < 0.5:  # 兑现率低于50%
                    score += 5

            # 延迟次数
            delay_count = history.get("delay_count", 0)
            if delay_count >= 3:
                score += 8
            elif delay_count >= 2:
                score += 4

        return min(score, 15)

    def _check_understandability(self, stock: Dict) -> int:
        """
        规则6：可理解性检查
        看不懂的降级（10分）

        检查：
        - 业务复杂度
        - 财务复杂度
        - 关联交易数量
        - 收入确认难度
        """
        score = 0

        # 业务复杂度
        business_complexity = stock.get("business_complexity", None)
        if business_complexity == "非常复杂":
            score += 8
        elif business_complexity == "复杂":
            score += 4

        # 关联交易占比
        related_party_ratio = stock.get("related_party_ratio", None)
        if related_party_ratio is not None:
            if related_party_ratio > 0.3:  # 关联交易占比超过30%
                score += 6

        # 业务板块数量（太多说明不聚焦）
        business_segments = stock.get("business_segments", None)
        if business_segments is not None:
            if business_segments > 5:  # 超过5个业务板块
                score += 4

        return min(score, 15)

    def _check_counter_evidence(self, stock: Dict) -> int:
        """
        规则7：反证检查
        至少3条反证（10分）

        检查：
        - 乐观假设的反证
        - 行业竞争加剧
        - 客户集中度风险
        - 技术替代风险
        - 政策风险
        """
        score = 0

        # 反证数量
        counter_evidence_count = stock.get("counter_evidence_count", 0)
        if counter_evidence_count >= 5:
            score += 10
        elif counter_evidence_count >= 3:
            score += 6
        elif counter_evidence_count >= 2:
            score += 3

        # 客户集中度
        top_customer_ratio = stock.get("top_customer_ratio", None)
        if top_customer_ratio is not None:
            if top_customer_ratio > 0.5:  # 第一大客户占比超过50%
                score += 5

        # 行业竞争加剧
        industry_competition = stock.get("industry_competition", None)
        if industry_competition == "非常激烈":
            score += 5
        elif industry_competition == "激烈":
            score += 3

        return min(score, 15)

    def _check_veto(self, stock: Dict, check_result: Dict) -> Dict:
        """
        风险专家一票否决检查

        否决条件：
        - 重要财务数据无法解释
        - 核心信息来源无法验证
        - 管理层承诺连续明显失信
        - 重大风险尚未弄清
        - 交易逻辑完全依赖单一传闻
        """
        result = {
            "vetoed": False,
            "veto_reasons": [],
        }

        # 重要财务数据无法解释（财务验证分极高）
        if check_result["rule_scores"].get("financial_validation", 0) >= 18:
            result["vetoed"] = True
            result["veto_reasons"].append("重要财务数据无法解释，风险一票否决")

        # 管理层承诺连续明显失信（历史兑现分极高）
        if check_result["rule_scores"].get("history_fulfillment", 0) >= 13:
            result["vetoed"] = True
            result["veto_reasons"].append("管理层承诺连续明显失信，风险一票否决")

        # 交易逻辑完全依赖单一传闻（真实变化分极高且没有任何可验证事实）
        if check_result["rule_scores"].get("real_change", 0) >= 23:
            result["vetoed"] = True
            result["veto_reasons"].append("交易逻辑完全依赖单一传闻，无可验证事实，风险一票否决")

        # 重大风险尚未弄清（反证分极高）
        if check_result["rule_scores"].get("counter_evidence", 0) >= 13:
            result["vetoed"] = True
            result["veto_reasons"].append("存在重大风险尚未弄清，反证较多，风险一票否决")

        return result

    def _classify_three_level_funnel(self, result: Dict):
        """
        三级漏斗分类

        - 观察池：有一点变化（保留+降级）
        - 研究池：有明确基本面问题值得继续验证（保留中淘汰分较低的）
        - 核心池：真正看得懂的几家（保留中淘汰分最低的3-5只）
        """
        # 观察池：保留+降级的股票
        observation_pool = result["kept"] + result["downgraded"]
        result["three_level_funnel"]["observation_pool"] = observation_pool[:50]  # 最多50只

        # 研究池：保留中淘汰分较低的10-15只
        research_pool = sorted(result["kept"], key=lambda x: x.get("reverse_screen", {}).get("elimination_score", 100))
        result["three_level_funnel"]["research_pool"] = research_pool[:15]  # 最多15只

        # 核心池：保留中淘汰分最低的3-5只
        core_pool = research_pool[:5]  # 最多5只
        result["three_level_funnel"]["core_pool"] = core_pool

    def _generate_summary(self, result: Dict) -> str:
        """生成反向筛选总结"""
        total = result["total_candidates"]
        eliminated = len(result["eliminated"])
        downgraded = len(result["downgraded"])
        kept = len(result["kept"])
        vetoed = len(result["veto_stocks"])

        summary = f"反向筛选（空头模式）: {total}只候选 → 淘汰{eliminated}只(含{vetoed}只风险否决) → 降级{downgraded}只 → 保留{kept}只"

        # 淘汰原因TOP3
        if result["elimination_reasons"]:
            top_reasons = sorted(result["elimination_reasons"].items(), key=lambda x: -x[1])[:3]
            reason_str = ", ".join([f"{r}({c}只)" for r, c in top_reasons])
            summary += f"。主要淘汰原因: {reason_str}"

        # 三级漏斗
        funnel = result["three_level_funnel"]
        summary += f"。三级漏斗: 观察池{len(funnel['observation_pool'])}只 → 研究池{len(funnel['research_pool'])}只 → 核心池{len(funnel['core_pool'])}只"

        return summary

    def _update_elimination_history(self, result: Dict, date: str):
        """更新淘汰历史记录"""
        for stock in result["eliminated"]:
            code = stock.get("code", "")
            if code:
                if code not in self.elimination_history:
                    self.elimination_history[code] = {
                        "name": stock.get("name", ""),
                        "elimination_count": 0,
                        "last_elimination_date": "",
                        "fulfillment_rate": 0.5,  # 默认50%
                        "delay_count": 0,
                    }
                self.elimination_history[code]["elimination_count"] += 1
                self.elimination_history[code]["last_elimination_date"] = date

        self._save_elimination_history()

    def generate_report(self, result: Dict) -> str:
        """生成反向筛选报告"""
        report = []

        report.append("🔍 反向筛选报告（空头模式）")
        report.append("=" * 40)
        report.append(f"候选股票: {result['total_candidates']}只")
        report.append(f"淘汰: {len(result['eliminated'])}只（含风险否决{len(result['veto_stocks'])}只）")
        report.append(f"降级: {len(result['downgraded'])}只")
        report.append(f"保留: {len(result['kept'])}只")
        report.append("")

        # 淘汰原因统计
        if result["elimination_reasons"]:
            report.append("【淘汰原因统计】")
            for reason, count in sorted(result["elimination_reasons"].items(), key=lambda x: -x[1]):
                report.append(f"  • {reason}: {count}只")
            report.append("")

        # 风险一票否决股票
        if result["veto_stocks"]:
            report.append("【风险一票否决股票】")
            for stock in result["veto_stocks"][:10]:
                name = stock.get("name", "")
                code = stock.get("code", "")
                veto = stock.get("reverse_veto", {})
                reasons = ", ".join(veto.get("veto_reasons", []))
                report.append(f"  ⛔ {name}({code}): {reasons}")
            report.append("")

        # 被淘汰股票（前10只）
        if result["eliminated"]:
            report.append("【被淘汰股票（前10只）】")
            for stock in result["eliminated"][:10]:
                name = stock.get("name", "")
                code = stock.get("code", "")
                rs = stock.get("reverse_screen", {})
                score = rs.get("elimination_score", 0)
                reasons = ", ".join(rs.get("elimination_reasons", [])[:2])
                report.append(f"  ❌ {name}({code}): 淘汰分{score}, {reasons}")
            report.append("")

        # 三级漏斗
        funnel = result["three_level_funnel"]
        report.append("【三级漏斗】")
        report.append(f"  观察池: {len(funnel['observation_pool'])}只（有一点变化）")
        report.append(f"  研究池: {len(funnel['research_pool'])}只（值得继续验证）")
        report.append(f"  核心池: {len(funnel['core_pool'])}只（真正看得懂）")
        report.append("")

        # 核心池股票
        if funnel["core_pool"]:
            report.append("【核心池股票】")
            for stock in funnel["core_pool"]:
                name = stock.get("name", "")
                code = stock.get("code", "")
                rs = stock.get("reverse_screen", {})
                score = rs.get("elimination_score", 0)
                report.append(f"  ⭐ {name}({code}): 淘汰分{score}（越低越安全）")
            report.append("")

        report.append("=" * 40)
        report.append("反向筛选核心思想：不是寻找值得买的股票，而是想办法淘汰股票")
        report.append("AI最适合散户的用法：不是帮你发现更多机会，而是帮你少犯'什么都想买'的错")

        return "\n".join(report)


# 全局实例
reverse_screener = ReverseScreener()


if __name__ == "__main__":
    # 测试反向筛选
    screener = ReverseScreener()
    test_stocks = [
        {"code": "000001", "name": "测试股票1", "turnover": 5},
        {"code": "000002", "name": "测试股票2", "turnover": 30, "price_change_30d": 0.6},
    ]
    result = screener.screen(test_stocks)
    report = screener.generate_report(result)
    print(report)
