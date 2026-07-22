from jqdata import *
import numpy as np
import pandas as pd

def initialize(context):
    # ============================================================
    # ETF 候选池（20只，去重，覆盖9个行业）
    # ============================================================
    g.etf_pool = {
        # 宽基 (5)
        "510050.XSHG": {"name": "上证50", "sector": "宽基"},
        "510300.XSHG": {"name": "沪深300", "sector": "宽基"},
        "510500.XSHG": {"name": "中证500", "sector": "宽基"},
        "159915.XSHE": {"name": "创业板", "sector": "宽基"},
        "512100.XSHG": {"name": "中证1000", "sector": "宽基"},
        # 科技 (3)
        "512760.XSHG": {"name": "芯片ETF", "sector": "科技"},
        "512480.XSHG": {"name": "半导体ETF", "sector": "科技"},
        "515050.XSHG": {"name": "5GETF", "sector": "科技"},
        # 金融/军工 (2)
        "512880.XSHG": {"name": "证券ETF", "sector": "金融"},
        "512660.XSHG": {"name": "军工ETF", "sector": "军工"},
        # 医药/消费 (3)
        "512010.XSHG": {"name": "医药ETF", "sector": "医药"},
        "159928.XSHE": {"name": "消费ETF", "sector": "消费"},
        "510880.XSHG": {"name": "红利ETF", "sector": "红利"},
        # 周期/新能源 (3)
        "515030.XSHG": {"name": "新能源车ETF", "sector": "新能源"},
        "512400.XSHG": {"name": "有色ETF", "sector": "周期"},
        "515220.XSHG": {"name": "煤炭ETF", "sector": "周期"},
        # 商品/跨境 (4)
        "518880.XSHG": {"name": "黄金ETF", "sector": "商品"},
        "159985.XSHE": {"name": "豆粕ETF", "sector": "商品"},
        "513050.XSHG": {"name": "中概互联", "sector": "跨境"},
        "159941.XSHE": {"name": "纳指ETF", "sector": "跨境"},
    }

    # ============================================================
    # 策略参数
    # ============================================================
    g.top_n = 2                             # 每次持有2只
    g.momentum_windows = [21, 63, 126, 252] # 动量周期（交易日）
    g.momentum_weights = [0.4, 0.3, 0.2, 0.1]  # 权重
    g.stop_loss = -0.12                      # -12%止损
    g.max_hold_days = 30                     # 最长持有30个交易日
    g.entry_dates = {}                       # 记录买入日期

    # ============================================================
    # 回测设置
    # ============================================================
    set_option("use_real_price", True)
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0,             # ETF免印花税
        open_commission=0.0003, close_commission=0.0003,
        min_commission=0                      # ETF免最低5元
    ), type="fund")
    set_slippage(PriceRelatedSlippage(0.001))

    # ============================================================
    # 调度
    # ============================================================
    run_weekly(rebalance, 1, time="10:00")   # 周一调仓
    run_daily(stop_check, time="14:30")       # 每日盘中止损检查


def calc_momentum(context):
    """计算全部ETF的多周期动量分数"""
    scores = {}
    end_date = context.previous_date

    for etf, info in g.etf_pool.items():
        try:
            prices = get_price(etf, end_date=end_date, count=300,
                              fields=["close"], skip_paused=False, fq="pre")
            if prices is None or len(prices) < max(g.momentum_windows) + 5:
                continue

            close = prices["close"].values
            score = 0.0
            for w, wt in zip(g.momentum_windows, g.momentum_weights):
                if w < len(close):
                    score += wt * (close[-1] / close[-w-1] - 1)

            if score != 0:
                scores[etf] = {"score": score, "sector": info["sector"],
                              "name": info["name"]}
        except Exception as e:
            continue

    # 按动量排序
    sorted_etfs = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    return sorted_etfs


def pick_diversified(scores, n=2):
    """行业分散选股：先选动量第一，再选第一个不同行业的"""
    picks = []
    seen_sectors = set()
    for etf, data in scores:
        sector = data["sector"]
        if len(picks) == 0:
            picks.append(etf); seen_sectors.add(sector)
        elif len(picks) < n:
            if sector not in seen_sectors:
                picks.append(etf); seen_sectors.add(sector)
        else:
            break
    return picks


def rebalance(context):
    """周度调仓（周一执行）"""
    if context.current_dt.isoweekday() != 1:
        return

    log.info("=== Weekly Rebalance ===")

    current_pos = set(context.portfolio.positions.keys())
    scores = calc_momentum(context)
    if not scores:
        log.warn("No momentum scores, skipping")
        return

    targets = pick_diversified(scores, g.top_n)
    target_set = set(targets)

    log.info("Target: " + ", ".join(
        [f"{t}({g.etf_pool[t]['sector']})" for t in targets]))

    # --- 卖出不在目标中的持仓 ---
    for etf in list(current_pos):
        if etf not in target_set:
            pos = context.portfolio.positions[etf]
            if pos.total_amount > 0:
                order_target(etf, 0)
                log.info(f"SELL {etf} ({g.etf_pool.get(etf,{}).get('name','')})")
                if etf in g.entry_dates:
                    del g.entry_dates[etf]

    # --- 买入目标持仓 ---
    for etf in targets:
        if etf not in current_pos:
            current_data = get_current_data()[etf]
            if current_data.paused or current_data.last_price <= 0:
                continue

            cash_per_pos = context.portfolio.available_cash / len(targets)
            price = current_data.last_price
            max_shares = int(cash_per_pos / (price * 1.0015))
            shares = (max_shares // 100) * 100

            if shares >= 100:
                order(etf, shares)
                g.entry_dates[etf] = context.current_dt
                log.info(f"BUY {etf} ({g.etf_pool[etf]['name']}) "
                        f"x{shares} @ {price:.3f}")

    # --- 打印动量排名 ---
    log.info("=== Momentum Rankings ===")
    for i, (etf, data) in enumerate(scores[:10]):
        tag = "<< PICK" if etf in target_set else ""
        log.info(f"  #{i+1} {etf} ({data['name']}) "
                f"score={data['score']*100:.2f} "
                f"sector={data['sector']} {tag}")


def stop_check(context):
    """每日盘中风控（14:30）"""
    for etf, pos in context.portfolio.positions.items():
        if pos.total_amount <= 0:
            continue

        current_data = get_current_data()[etf]
        if current_data.paused:
            continue

        price = current_data.last_price
        cost = pos.avg_cost
        returns = (price - cost) / cost

        # 止损
        if returns <= g.stop_loss:
            order_target(etf, 0)
            log.info(f"STOP LOSS: {etf} ({g.etf_pool.get(etf,{}).get('name','')}) "
                    f"return={returns*100:.2f}%")
            if etf in g.entry_dates:
                del g.entry_dates[etf]
            continue

        # 持仓超时
        if etf in g.entry_dates:
            hold_days = (context.current_dt - g.entry_dates[etf]).days
            if hold_days >= g.max_hold_days:
                order_target(etf, 0)
                log.info(f"MAX HOLD: {etf} ({g.etf_pool.get(etf,{}).get('name','')}) "
                        f"held {hold_days}d")
                del g.entry_dates[etf]


def after_trading_end(context):
    """记录净值"""
    record(equity=context.portfolio.total_value)
