# -*- coding: utf-8 -*-
"""ETF动量策略 - 通知推送系统 (AlphaFeed + 免费通知)"""
import os, sys, json, smtplib, argparse, time, pickle
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime
import warnings; warnings.filterwarnings("ignore")

# ========== 配置区 ==========
ALPHAFEED_API_KEY = os.environ.get("ALPHAFEED_API_KEY", "")
ETF_POOL = {
    "510050.SH": {"name": "上证50", "sector": "宽基"},
    "510300.SH": {"name": "沪深300", "sector": "宽基"},
    "510500.SH": {"name": "中证500", "sector": "宽基"},
    "159915.SZ": {"name": "创业板", "sector": "宽基"},
    "512100.SH": {"name": "中证1000", "sector": "宽基"},
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
TOP_N = 2; STOP_LOSS_PCT = -12; MAX_HOLD_DAYS = 30

# 邮箱配置
SMTP_CONFIG = {"enabled": False, "host": "smtp.qq.com", "port": 587,
               "user": "", "password": "", "to_addrs": []}
SERVERCHAN_KEY = ""
BARK_URL = ""
# ========== 配置结束 ==========

def fetch_data(force_refresh=False):
    from alphafeed import AlphaFeed
    import pandas as pd
    cache_dir = Path(__file__).parent / "data_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    all_data = {}; todo = list(ETF_POOL.keys())
    if not force_refresh:
        for sym in todo:
            cf = cache_dir / f"{sym.replace('.', '_')}.pkl"
            if cf.exists():
                try:
                    df = pd.read_pickle(str(cf))
                    if len(df) > 200: all_data[sym] = df
                except: pass
    todo = [s for s in todo if s not in all_data]
    if todo:
        print(f"从API获取 {len(todo)} 只ETF数据...")
        client = AlphaFeed(api_key=ALPHAFEED_API_KEY)
        for i, sym in enumerate(todo):
            print(f"  [{i+1}/{len(todo)}] {sym}", end=" ", flush=True)
            try:
                df = client.klines.get(sym, period="1d", count=300, adjust="forward", to_dataframe=True)
                if df is not None and len(df) > 50:
                    df["trade_date"] = pd.to_datetime(df["trade_date"])
                    df = df.sort_values("trade_date").reset_index(drop=True)
                    df["date"] = df["trade_date"]
                    all_data[sym] = df
                    df.to_pickle(str(cache_dir / f"{sym.replace('.', '_')}.pkl"))
                    print(f"{len(df)}行")
                else: print("数据不足")
            except Exception as e: print(f"错误: {e}")
            time.sleep(0.5)
    return all_data

def calc_momentum(data, names):
    import numpy as np; import pandas as pd
    scores = {}
    for sym, df in data.items():
        close = df["close"].values
        if len(close) < max(MOMENTUM_WINDOWS) + 5: continue
        score = 0.0
        for w, wt in zip(MOMENTUM_WINDOWS, MOMENTUM_WEIGHTS):
            if w < len(close): score += wt * (close[-1] / close[-w-1] - 1)
        if score != 0:
            scores[sym] = {"score": score, "sector": ETF_POOL.get(sym,{}).get("sector",""),
                          "name": names.get(sym, sym)}
    si = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    picks = []; seen = set()
    for sym, info in si:
        sec = info["sector"]
        if len(picks) == 0: picks.append(sym); seen.add(sec)
        elif len(picks) < TOP_N and sec not in seen: picks.append(sym); seen.add(sec)
        else: break
    return si, picks

def get_prices(data):
    from alphafeed import AlphaFeed
    try:
        client = AlphaFeed(api_key=ALPHAFEED_API_KEY)
        quotes = client.quotes.get(symbols=list(data.keys()), to_dataframe=True)
        return {sym: float(quotes.loc[sym,"last_price"]) for sym in data if sym in quotes.index}
    except:
        return {sym: float(df["close"].iloc[-1]) for sym, df in data.items()}

def build_msg(si, picks, prices):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"ETF动量策略信号 - {now}", "="*40, ""]
    lines.append("[买入持仓 - Top 2（行业分散）]")
    for i, (sym, info) in enumerate(si[:8]):
        price = prices.get(sym, 0)
        tag = ">> BUY" if sym in picks else "watch"
        lines.append(f"  #{i+1} {info['name']}({sym}) 动量{info['score']*100:.1f} {info['sector']} {tag}")
    lines.append("")
    if picks:
        lines.append("[建议操作]")
        for sym in picks:
            info = ETF_POOL.get(sym, {})
            price = prices.get(sym, 0)
            lines.append(f"  买入 {info.get('name',sym)} ({sym})  现价{price:.3f}  仓位50%")
        lines.append("")
    lines.append("[风控] 止损-12% | 最长30天 | 留10%现金")
    lines.append("="*40)
    return "\n".join(lines)

def send_email(subject, body):
    c = SMTP_CONFIG
    if not c["enabled"] or not c["user"] or not c["to_addrs"]: return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject; msg["From"] = c["user"]; msg["To"] = ",".join(c["to_addrs"])
        with smtplib.SMTP(c["host"], c["port"], timeout=10) as s:
            s.starttls(); s.login(c["user"], c["password"]); s.send_message(msg)
        print("[通知] 邮件已发送")
    except Exception as e: print(f"[通知] 邮件失败: {e}")

def send_wechat(title, body):
    import requests
    if not SERVERCHAN_KEY: return
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send",
                         data={"title": title, "desp": body}, timeout=10)
        if r.json().get("code") == 0: print("[通知] 微信已发送")
        else: print(f"[通知] 微信失败: {r.text}")
    except Exception as e: print(f"[通知] 微信错误: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", action="store_true")
    parser.add_argument("--wechat", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    print("ETF动量策略信号生成器 (AlphaFeed)")
    data = fetch_data(force_refresh=args.refresh)
    print(f"获取到 {len(data)} 只ETF")

    names = {}
    np = Path(__file__).parent.parent / "work" / "etf_names.pkl"
    if np.exists():
        try: names = pickle.loads(np.read_bytes())
        except: pass
    for s in data:
        if s not in names: names[s] = ETF_POOL.get(s,{}).get("name", s)

    si, picks = calc_momentum(data, names)
    prices = get_prices(data)
    msg = build_msg(si, picks, prices)

    print("\n" + msg + "\n")
    title = f"ETF动量信号 {'/'.join(ETF_POOL[s]['name'] for s in picks)}"
    if args.email or args.all: send_email(title, msg)
    if args.wechat or args.all: send_wechat(title, msg)
    if not args.email and not args.wechat and not args.all:
        print("提示: --email 或 --wechat 推送通知")
