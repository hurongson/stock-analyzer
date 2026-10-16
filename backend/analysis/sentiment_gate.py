"""
复合情绪闸门（陈小群情绪周期 · 五档）

把尾盘 late_day.py 中已经回测验证的"退潮 / 高潮 / 强分歧 / 分歧 / 健康"判定抽成独立可复用模块，
让每日分析(engine)与尾盘(late_day)共用同一套阈值，修复"每日分析只看涨停家数、在退潮/高潮日仍
推荐反包票"的问题。

关键设计：
- 只有在炸板/跌停/指数数据取全、判定可信时才给出 退潮/高潮；数据不足时 risk_regime="未知"、
  enabled=False，调用方【不得】据此拦截推荐——宁可不拦，也不能因数据问题把推荐误清空。
- 阈值与 backend/screener/late_day.py 完全一致（经 9/07、9/22-24、9/28-30、10/8-14 回测验证）。
  任何阈值调整必须两边同步并重新回测。
"""
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# ===== 五档阈值（与 late_day.py 保持一致）=====
ZHABAN_RATE_CRASH = 30.0      # 炸板率≥30% → 退潮
INDEX_CRASH_PCT = -1.5        # 最弱指数≤-1.5% → 退潮
DIETING_COLLAPSE = 10         # 跌停≥10 且共振 → 退潮
ZHABAN_RATE_DT_RESON = 20.0   # 跌停扩散共振：炸板率≥20%
INDEX_DT_RESON = -0.8         # 跌停扩散共振：最弱指数≤-0.8%
CLIMAX_MAX_LB = 7             # 最高连板≥7
CLIMAX_ZHABAN = 15.0          # 高潮分化：炸板率≥15%
CLIMAX_DIETING = 8            # 高潮分化：跌停≥8
STRONG_DIV_ZHABAN = 22.0      # 强分歧：炸板率≥22%
DIV_ZHABAN = 15.0             # 分歧：炸板率≥15%
DIV_DIETING = 5               # 分歧：跌停≥5
DIV_INDEX = -0.8              # 分歧：最弱指数≤-0.8%

# 每日买入推荐在这两档清空（陈小群：退潮空仓、高潮不追、卖在一致）
NO_BUY_REGIMES = ("退潮", "高潮")
# 强分歧/分歧是"买在分歧"的窗口，保留陈小群反包真龙（10-13 强分歧日次日修复，+6.76% 验证）


def classify_risk_regime(limit_up_count, zhaban_count, dieting_count,
                         idx_weak_pct, max_lb, lb_count=0):
    """纯函数：依据涨停/炸板/跌停/最弱指数/最高连板，判定五档情绪。

    返回 dict：risk_regime、zhaban_rate、limit_up_count、zhaban_count、dieting_count、
    idx_weak_pct、max_lb、lb_count、signals(命中信号列表)、note。
    """
    denom = (limit_up_count or 0) + (zhaban_count or 0)
    zhaban_rate = (zhaban_count / denom * 100) if denom else 0.0

    hard_crash = (zhaban_rate >= ZHABAN_RATE_CRASH) or (idx_weak_pct <= INDEX_CRASH_PCT)
    dt_collapse = ((dieting_count or 0) >= DIETING_COLLAPSE and
                   (zhaban_rate >= ZHABAN_RATE_DT_RESON or idx_weak_pct <= INDEX_DT_RESON))
    climax = ((max_lb or 0) >= CLIMAX_MAX_LB and
              (zhaban_rate >= CLIMAX_ZHABAN or (dieting_count or 0) >= CLIMAX_DIETING))
    strong_div = zhaban_rate >= STRONG_DIV_ZHABAN

    signals = []
    if hard_crash:
        signals.append("炸板潮或指数暴跌")
    if dt_collapse:
        signals.append("跌停扩散")
    if climax:
        signals.append("高潮末端分化")
    if strong_div:
        signals.append("封板成功率大降")

    if hard_crash or dt_collapse:
        regime = "退潮"
        note = (f"炸板率{zhaban_rate:.0f}%、跌停{dieting_count}只、最弱指数{idx_weak_pct:.2f}%，"
                f"情绪退潮，亏钱效应扩散，按陈小群纪律空仓等待冰点，不抄底、不做反包。")
    elif climax:
        regime = "高潮"
        note = (f"最高{max_lb}板、炸板率{zhaban_rate:.0f}%、跌停{dieting_count}只，情绪打到高位并开始分化，"
                f"卖在一致、高潮不追，只宜止盈不开新仓。")
    elif strong_div:
        regime = "强分歧"
        note = (f"炸板率{zhaban_rate:.0f}%（封板成功率明显下降）、跌停{dieting_count}只，"
                f"分歧加剧但未退潮；可只在盘后低吸主线真龙做次日修复，不打板、不追高。")
    elif zhaban_rate >= DIV_ZHABAN or (dieting_count or 0) >= DIV_DIETING or idx_weak_pct <= DIV_INDEX:
        regime = "分歧"
        note = "情绪分歧，控制仓位、只做主线真龙。"
    else:
        regime = "健康"
        note = "情绪健康，可按既定策略选股。"

    return {
        "risk_regime": regime,
        "limit_up_count": int(limit_up_count or 0),
        "zhaban_count": int(zhaban_count or 0),
        "zhaban_rate": round(zhaban_rate, 1),
        "dieting_count": int(dieting_count or 0),
        "idx_weak_pct": round(float(idx_weak_pct), 2),
        "max_lb": int(max_lb or 0),
        "lb_count": int(lb_count or 0),
        "signals": signals,
        "note": note,
    }


def _idx_daily_pct_on(ak, date_yyyymmdd):
    """取指定历史交易日(YYYYMMDD)深证/创业板当日涨跌幅，用较弱者（指数日线，用于回退日期对齐）。"""
    target = f"{date_yyyymmdd[:4]}-{date_yyyymmdd[4:6]}-{date_yyyymmdd[6:8]}"
    vals = {}
    for sym in ('sz399001', 'sz399006'):
        try:
            df = ak.stock_zh_index_daily(symbol=sym).sort_values('date').reset_index(drop=True)
            df['date'] = df['date'].astype(str).str[:10]
            hit = df.index[df['date'] == target].tolist()
            if hit and hit[0] >= 1:
                i = hit[0]
                pre, cur = float(df.loc[i - 1, 'close']), float(df.loc[i, 'close'])
                vals[sym] = (cur - pre) / pre * 100 if pre else 0.0
        except Exception:
            continue
    return min(vals.values()) if len(vals) == 2 else None


def _idx_weak_pct(ak):
    """取深证成指、创业板指当日涨跌幅，用较弱者。盘中/盘后以实时为准，日线兜底。"""
    try:
        sp = ak.stock_zh_index_spot_sina()
        sz = sp[sp['代码'] == 'sz399001']
        cy = sp[sp['代码'] == 'sz399006']
        if len(sz) and len(cy):
            return min(float(sz.iloc[0]['涨跌幅']), float(cy.iloc[0]['涨跌幅']))
    except Exception:
        pass
    try:
        import requests as rq, re as rmod
        r = rq.get('http://hq.sinajs.cn/list=sz399001,sz399006',
                   headers={'Referer': 'https://finance.sina.com.cn'}, timeout=8)
        r.encoding = 'gbk'
        vals = {}
        for line in r.text.strip().split('\n'):
            m = rmod.search(r'hq_str_(\w+)=="([^"]*)"', line)
            if m and m.group(2):
                a = m.group(2).split(',')
                cur, pre = float(a[3]), float(a[2])
                vals[m.group(1)] = (cur - pre) / pre * 100 if pre else 0.0
        if 'sz399001' in vals and 'sz399006' in vals:
            return min(vals['sz399001'], vals['sz399006'])
    except Exception:
        pass
    try:
        szd = ak.stock_zh_index_daily(symbol='sz399001').sort_values('date').tail(2)['close'].values
        cyd = ak.stock_zh_index_daily(symbol='sz399006').sort_values('date').tail(2)['close'].values
        sz_p = (szd[1] - szd[0]) / szd[0] * 100
        cy_p = (cyd[1] - cyd[0]) / cyd[0] * 100
        return min(sz_p, cy_p)
    except Exception:
        return None


def assess_market_regime(zt_df=None, dt_df=None, data_date=None):
    """评估当前复合情绪。

    可传入已取好的涨停/跌停 DataFrame 及其日期(YYYYMMDD)（engine 已取时复用，减少请求）；
    否则自取（带最近交易日回退）。
    数据不足时返回 enabled=False、risk_regime='未知'，调用方不得据此拦截。
    """
    unknown = {"risk_regime": "未知", "enabled": False, "blocked": False,
               "note": "复合情绪数据不足，闸门未启用，按常规策略出票。"}
    try:
        import akshare as ak
        beijing = datetime.utcnow() + timedelta(hours=8)
        if not data_date:
            data_date = beijing.strftime('%Y%m%d')

        if zt_df is None or zt_df.empty:
            data_date = ""

            zt_df = None
            for back in range(0, 12):
                d = beijing - timedelta(days=back)
                if d.weekday() >= 5:
                    continue
                ds = d.strftime('%Y%m%d')
                try:
                    ex = ThreadPoolExecutor(max_workers=1)
                    fut = ex.submit(ak.stock_zt_pool_em, date=ds)
                    cand = fut.result(timeout=25)
                    ex.shutdown(wait=False)
                except Exception:
                    cand = None
                if cand is not None and not cand.empty:
                    zt_df, data_date = cand, ds
                    break
        if zt_df is None or zt_df.empty:
            logger.warning("情绪闸门：涨停池取不到，无法判定（不拦截）")
            return unknown

        limit_up_count = len(zt_df)
        max_lb, lb_count = 0, 0
        try:
            if '连板数' in zt_df.columns:
                lb = __import__('pandas').to_numeric(zt_df['连板数'], errors='coerce').fillna(1)
                max_lb = int(lb.max())
                lb_count = int((lb >= 2).sum())
        except Exception:
            pass

        # 炸板池（同日期）
        zhaban_count = 0
        if data_date:
            try:
                ex = ThreadPoolExecutor(max_workers=1)
                zb = ex.submit(ak.stock_zt_pool_zbgc_em, date=data_date).result(timeout=20)
                ex.shutdown(wait=False)
                zhaban_count = 0 if zb is None else len(zb)
            except Exception:
                zhaban_count = 0
        # 跌停池：优先用传入/同日期
        dieting_count = 0 if dt_df is None else len(dt_df)
        if dieting_count == 0 and data_date:
            try:
                ex = ThreadPoolExecutor(max_workers=1)
                dt2 = ex.submit(ak.stock_zt_pool_dtgc_em, date=data_date).result(timeout=20)
                ex.shutdown(wait=False)
                dieting_count = 0 if dt2 is None else len(dt2)
            except Exception:
                dieting_count = 0

        today_bj = beijing.strftime('%Y%m%d')
        if data_date == today_bj:
            # 当天（盘中/盘后）：取实时指数
            idx_weak_pct = _idx_weak_pct(ak)
        else:
            # 涨停数据回退到历史交易日（盘前/周末/补跑/回测）：指数取同一交易日，避免日期错配
            logger.info(f"情绪闸门：涨停数据为回退日{data_date}，指数按该交易日日线对齐")
            idx_weak_pct = _idx_daily_pct_on(ak, data_date)
            if idx_weak_pct is None:
                idx_weak_pct = _idx_weak_pct(ak)  # 日线取不到再兜底实时
        if idx_weak_pct is None:
            # 指数是退潮/分歧判定的关键之一，取不到则不做拦截（避免误杀）
            logger.warning("情绪闸门：指数涨跌取不到，无法判定（不拦截）")
            return unknown

        result = classify_risk_regime(limit_up_count, zhaban_count, dieting_count,
                                      idx_weak_pct, max_lb, lb_count)
        result["enabled"] = True
        result["data_date"] = data_date or beijing.strftime('%Y%m%d')
        result["blocked"] = result["risk_regime"] in NO_BUY_REGIMES
        logger.info(f"情绪闸门: 【{result['risk_regime']}】 炸板{zhaban_count}"
                    f"({result['zhaban_rate']:.0f}%) 跌停{dieting_count} "
                    f"最弱指数{idx_weak_pct:.2f}% 最高板{max_lb} -> 拦截={result['blocked']}")
        return result
    except Exception as e:
        logger.warning(f"情绪闸门计算异常（不拦截）: {str(e)[:100]}")
        return unknown
