#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ETF动量策略 - 云端运行版（AlphaFeed数据源，自动推送通知）"""
import os, sys, json, smtplib, time, io, csv, warnings
from pathlib import Path
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.header import Header

warnings.filterwarnings("ignore")
ALPHAFEED_KEY = os.environ.get("ALPHAFEED_API_KEY", "")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_TO = os.environ.get("SMTP_TO", "")
PORTFOLIO_FILE = "portfolio.json"

ETF_POOL = {
    "510050.SH": {"name": "上证50ETF", "sector": "宽基"},
    "510300.SH": {"name": "沪深300ETF", "sector": "宽基"},
    "510500.SH": {"name": "中证500ETF", "sector": "宽基"},
    "159915.SZ": {"name": "创业板ETF", "sector": "宽基"},
    "512100.SH": {"name": "中证1000ETF", "sector": "宽基"},
    "512760.SH": {"name": "芯片ETF", "sector": "科技"},
    "512480.SH": {"name": "半导体ETF", "sector": "科技"},
    "515050.SH": {"name": "5GETF", "sector": "科技"},
    "512880.SH": {"name": "证券ETF", "sector": "金融"},
    "512660.SH": {"name": "军工ETF", "sector": "军工"},
    "512010.SH": {"name": "医药ETF", "sector": "医药"},
    "159928.SZ": {"name": "消费ETF", "sector": "消费"},
    "510880.SH": {"name": "红利ETF", "sector": "红利"},
    "515030.SH": {"name": "新能源车ETF", "sector": "新能源"},
    "512400.SH": {"name": "有色ETF", "sector": "周期"},
    "515220.SH": {"name": "煤炭ETF", "sector": "周期"},
    "518880.SH": {"name": "黄金ETF", "sector": "商品"},
    "159985.SZ": {"name": "豆粕ETF", "sector": "商品"},
    "513050.SH": {"name": "中概互联", "sector": "跨境"},
    "159941.SZ": {"name": "纳指ETF", "sector": "跨境"},
}

MOMENTUM_WINDOWS = [21, 63, 126, 252]
MOMENTUM_WEIGHTS = [0.4, 0.3, 0.2, 0.1]
TOP_N = 2; STOP_PCT = -12; MAX_HOLD = 30

def fetch_data(force_refresh=False):
    """获取全部ETF最新行情"""
    from alphafeed import AlphaFeed
    import pandas as pd, pickle

    cache_dir = Path(__file__).parent / "data_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    all_data = {}
    todo = list(ETF_POOL.keys())

    if not force_refresh:
        for sym in todo:
            cf = cache_dir / f"{sym.replace(".", "_")}.pkl"
            if cf.exists():
                try:
                    df = pd.read_pickle(str(cf))
                    if len(df) > 200: all_data[sym] = df
                except: pass

    todo = [s for s in todo if s not in all_data]
    if todo:
        print(f"从API获取 {len(todo)} 只ETF数据...")
        client = AlphaFeed(api_key=ALPHAFEED_KEY)
        for i, sym in enumerate(todo):
            print(f"  [{i+1}/{len(todo)}]", sym, end=" ", flush=True)
            try:
                df = client.klines.get(sym, period="1d", count=300,
                    adjust="forward", to_dataframe=True)
                if df is not None and len(df) > 50:
                    df["trade_date"] = pd.to_datetime(df["trade_date"])
                    df = df.sort_values("trade_date").reset_index(drop=True)
                    df["date"] = df["trade_date"]
                    all_data[sym] = df
                    df.to_pickle(str(cache_dir / f"{sym.replace(".", "_")}.pkl"))
                    print(f"{len(df)}行")
                else: print("数据不足")
            except Exception as e: print(f"错误: {e}")
            time.sleep(0.5)
    return all_data


def calc_momentum(data):
    """计算动量排名（含行业分散）"""
    import numpy as np
    import pandas as pd

    scores = {}
    for sym, df in data.items():
        close = df["close"].values
        if len(close) < max(MOMENTUM_WINDOWS) + 5: continue
        score = 0.0
        for w, wt in zip(MOMENTUM_WINDOWS, MOMENTUM_WEIGHTS):
            if w < len(close):
                score += wt * (close[-1] / close[-w-1] - 1)
        if score != 0:
            info = ETF_POOL.get(sym, {})
            scores[sym] = {"score": score, "sector": info.get("sector", ""),
                          "name": info.get("name", sym)}

    si = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    picks = []; seen = set()
    for sym, info in si:
        sec = info["sector"]
        if len(picks) == 0:
            picks.append(sym); seen.add(sec)
        elif len(picks) < TOP_N and sec not in seen:
            picks.append(sym); seen.add(sec)
        else: break
    return si, picks


def get_live_prices(data):
    """获取实时行情"""
    from alphafeed import AlphaFeed
    try:
        client = AlphaFeed(api_key=ALPHAFEED_KEY)
        quotes = client.quotes.get(symbols=list(data.keys()), to_dataframe=True)
        return {sym: float(quotes.loc[sym, "last_price"])
                for sym in data if sym in quotes.index}
    except:
        return {sym: float(df["close"].iloc[-1]) for sym, df in data.items()}


def load_portfolio():
    """加载持仓记录"""
    pf = Path(PORTFOLIO_FILE)
    if not pf.exists():
        return {"entries": [], "cash": 0, "last_update": ""}
    try:
        return json.loads(pf.read_text(encoding="utf-8"))
    except:
        return {"entries": [], "cash": 0, "last_update": ""}

def build_signal_msg(si, picks, prices):
    """生成买入信号文本"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["=" * 40,
             f" ETF动量策略 - 周度信号  {now}",
             "=" * 40, ""]
    lines.append("| 买入持仓 Top 2（行业分散）|")
    lines.append("-" * 40)
    for i, (sym, info) in enumerate(si[:8]):
        price = prices.get(sym, 0)
        tag = ">> BUY" if sym in picks else "  watch"
        lines.append(f" #{i+1} {info['name']} ({sym})  "
                    f"动量{info['score']*100:.1f}  "
                    f"{info['sector']}  {tag}")
    lines.append("")
    if picks:
        lines.append("| 建议操作 |")
        for sym in picks:
            info = ETF_POOL.get(sym, {})
            price = prices.get(sym, 0)
            lines.append(f" 买入 {info.get('name', sym)} ({sym})  现价{price:.3f}")
        lines.append("")
    lines.append("| 风控规则 |")
    lines.append(f" 止损: -{abs(STOP_PCT)}% | 最长持有: {MAX_HOLD}天 | 建议留10%现金")
    lines.append("=" * 40)
    return chr(10).join(lines)


def build_portfolio_msg(data, prices):
    """生成持仓盈亏报告"""
    portfolio = load_portfolio()
    if not portfolio["entries"]:
        return "当前无持仓记录。请在 portfolio.json 中填写持仓信息。"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["=" * 40,
             f" ETF持仓报告  {now}",
             "=" * 40, ""]
    lines.append("| 持仓明细 |")
    lines.append(f"{'ETF':<18s} {'现价':>8s} {'成本':>8s} {'盈亏':>10s} {'天数':>6s}")
    lines.append("-" * 50)

    total_pnl = 0.0
    total_cost = 0.0
    for entry in portfolio["entries"]:
        sym = entry["etf"]
        shares = entry["shares"]
        cost_price = entry["price"]
        entry_date = entry.get("date", "")
        name = ETF_POOL.get(sym, {}).get("name", sym)
        current_price = prices.get(sym, 0)

        cost_value = shares * cost_price
        current_value = shares * current_price
        pnl_pct = (current_price / cost_price - 1) * 100
        pnl_value = current_value - cost_value

        if entry_date:
            try:
                hold_days = (datetime.now() - datetime.strptime(entry_date, "%Y-%m-%d")).days
            except:
                hold_days = 0
        else:
            hold_days = 0

        lines.append(f"{name:<8s} {current_price:>8.3f} {cost_price:>8.3f} "
                    f"{pnl_pct:>+8.2f}% {hold_days:>4d}d")
        total_pnl += pnl_value
        total_cost += cost_value

    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    lines.append("-" * 50)
    lines.append(f"总投入: {total_cost:>.0f}")
    lines.append(f"总盈亏: {total_pnl:>+.0f} ({total_pnl_pct:>+.2f}%)")
    lines.append(f"现金: {portfolio.get('cash', 0):>.0f}")
    total_assets = total_cost + total_pnl + portfolio.get("cash", 0)
    lines.append(f"总资产: {total_assets:>.0f}")

    # 止损检查
    stop_alerts = []
    for entry in portfolio["entries"]:
        sym = entry["etf"]
        cost_price = entry["price"]
        current_price = prices.get(sym, 0)
        pnl = (current_price / cost_price - 1) * 100
        if pnl <= STOP_PCT:
            name = ETF_POOL.get(sym, {}).get("name", sym)
            stop_alerts.append(f"  {name} 触发止损线! 盈亏{pnl:.1f}% (止损线{STOP_PCT}%)")

    if stop_alerts:
        lines.append("")
        lines.append("| 风险警告 |")
        lines.extend(stop_alerts)
    lines.append("=" * 40)
    return chr(10).join(lines)

def send_email(subject, body):
    """发送邮件通知"""
    if not SMTP_USER or not SMTP_PASS or not SMTP_TO:
        print("[邮件] 未配置SMTP，跳过")
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = SMTP_TO
        host = "smtp.qq.com"
        port = 587
        # 自动识别邮箱类型
        if "gmail" in SMTP_USER.lower():
            host = "smtp.gmail.com"
        elif "163" in SMTP_USER.lower():
            host = "smtp.163.com"
            port = 25
        with smtplib.SMTP(host, port, timeout=10) as s:
            if port == 587: s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print(f"[邮件] 已发送到 {SMTP_TO}")
        return True
    except Exception as e:
        print(f"[邮件] 发送失败: {e}")
        return False


def send_serverchan(title, body):
    """微信推送 (ServerChan，免费)"""
    import requests
    key = os.environ.get("SERVERCHAN_KEY", "")
    if not key:
        print("[微信] 未配置 ServerChan，跳过")
        return
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                         data={"title": title, "desp": body}, timeout=10)
        if r.json().get("code") == 0:
            print("[微信] 已发送")
        else:
            print(f"[微信] 失败: {r.text}")
    except Exception as e:
        print(f"[微信] 错误: {e}")


def update_portfolio_signals(picks, prices):
    """将信号写入持仓文件（供参考）"""
    portfolio = load_portfolio()
    if not portfolio["entries"]:
        portfolio["entries"] = []
    portfolio["last_signal"] = datetime.now().strftime("%Y-%m-%d")
    portfolio["signals"] = []
    for sym in picks:
        price = prices.get(sym, 0)
        portfolio["signals"].append({
            "etf": sym,
            "name": ETF_POOL.get(sym, {}).get("name", sym),
            "signal_price": price,
            "date": datetime.now().strftime("%Y-%m-%d")
        })
    Path(PORTFOLIO_FILE).write_text(
        json.dumps(portfolio, indent=2, ensure_ascii=False), encoding="utf-8")

def main():
    import argparse, pickle
    parser = argparse.ArgumentParser(description="ETF动量策略云端版")
    parser.add_argument("--signal", action="store_true", help="生成周度信号")
    parser.add_argument("--report", action="store_true", help="生成持仓报告")
    parser.add_argument("--refresh", action="store_true", help="刷新数据")
    parser.add_argument("--email", action="store_true", help="邮件推送")
    parser.add_argument("--wechat", action="store_true", help="微信推送")
    args = parser.parse_args()

    if not (args.signal or args.report):
        args.signal = True
        args.report = True

    # 获取数据
    data = fetch_data(force_refresh=args.refresh)
    if not data:
        print("错误: 无法获取数据")
        return 1
    print(f"获取到 {len(data)} 只ETF数据")

    # 获取实时价格
    prices = get_live_prices(data)

    email_body_parts = []

    # 生成信号
    if args.signal:
        print("生成周度信号...")
        si, picks = calc_momentum(data)
        msg = build_signal_msg(si, picks, prices)
        print(msg)
        email_body_parts.append(msg)
        update_portfolio_signals(picks, prices)

    # 生成持仓报告
    if args.report:
        print("生成持仓报告...")
        msg2 = build_portfolio_msg(data, prices)
        print(msg2)
        email_body_parts.append(msg2)

    # 发送通知
    full_body = chr(10).join(email_body_parts)
    title = f"ETF策略 {'信号' if args.signal else ''} {'报告' if args.report else ''}"

    if args.email:
        send_email(title, full_body)
    if args.wechat:
        send_serverchan(title, full_body)
    if not args.email and not args.wechat:
        print("添加 --email 或 --wechat 参数推送通知")


if __name__ == "__main__":
    main()
