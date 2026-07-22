import warnings; warnings.filterwarnings('ignore')
import pandas as pd; import numpy as np; import pickle

data = pickle.load(open('C:/Users/myq28/Documents/Codex/2026-07-21/hello-2/work/etf_data.pkl','rb'))
names = pickle.load(open('C:/Users/myq28/Documents/Codex/2026-07-21/hello-2/work/etf_names.pkl','rb'))
print('Loaded', len(data), 'ETFs')

# 20 carefully selected A-share ETFs, categorized
SYMBOLS = [
    '510050.SH','510300.SH','510500.SH','159915.SZ','512100.SH',  # 宽基
    '512760.SH','512480.SH','515050.SH','515000.SH',               # 科技
    '159928.SZ','512010.SH',                                        # 消费医药
    '515030.SH','512880.SH','512400.SH','515220.SH','512660.SH',    # 周期
    '510880.SH','518880.SH',                                        # 防御
    '513050.SH','159941.SZ',                                         # 跨境
]
etf_list = [{'symbol':s,'name':names.get(s,s),'data':data[s]} for s in SYMBOLS if s in data]
print('Universe:', len(etf_list), 'ETFs')

# Strategy config (v3 - balanced optimization)
TOP_N=5; COMM=0.0003; SLIP=0.001; CAP=1000000
WINS=[21,63,126,252]; WTS=[0.4,0.3,0.2,0.1]  # raw returns, same as v1
SL=-0.15; TP=0.30; TRAIL=-0.12; MHD=80         # looser risk mgmt
BENCH='510300.SH'

# Build price matrix
all_dates = pd.DatetimeIndex([])
for item in etf_list:
    all_dates = all_dates.union(item['data']['date'])
all_dates = pd.DatetimeIndex(sorted(set(all_dates)))
pdct = {}
for item in etf_list:
    pdct[item['symbol']] = item['data'].set_index('date')['close']
prices = pd.DataFrame(pdct).reindex(all_dates).ffill()

bench_df = None
for item in etf_list:
    if item['symbol']==BENCH: bench_df=item['data'].set_index('date'); break
if bench_df is None: bench_df=etf_list[0]['data'].set_index('date')
bstart = float(bench_df['close'].iloc[0])
bench_200ma = bench_df['close'].rolling(200).mean()

# Backtest range
earliest = max(item['data']['date'].min() for item in etf_list)
latest = min(item['data']['date'].max() for item in etf_list)
sd = earliest + pd.Timedelta(days=500)
btd = all_dates[(all_dates>=sd)&(all_dates<=latest)]
if len(btd)>5*252: btd = btd[-5*252:]
print('Backtest:', str(btd[0])[:10], 'to', str(btd[-1])[:10], '| Days:', len(btd))

def calc_mom(d):
    scores={}
    for item in etf_list:
        df=item['data']; sub=df[df['date']<=d]; c=sub['close'].values
        if len(c)<max(WINS)+5: continue
        sc=0.0
        for w,wt in zip(WINS,WTS):
            if w<len(c): sc+=wt*(c[-1]/c[-w-1]-1)
        if sc!=0: scores[item['symbol']]=sc
    if not scores: return None
    r=pd.DataFrame([{'s':s,'n':names.get(s,s),'m':v} for s,v in scores.items()])
    r=r.sort_values('m',ascending=False).reset_index(drop=True)
    r['rk']=range(1,len(r)+1); return r

cash=CAP; held={}; nh=[]; tl=[]; tdc=0
for idx,date in enumerate(btd):
    tdc+=1
    if date not in prices.index: continue
    tp=prices.loc[date]
    # Mark positions
    pv=0
    for sym in list(held.keys()):
        pos=held[sym]; pos['hd']=pos.get('hd',0)+1
        if sym in tp.index and not pd.isna(tp[sym]):
            cp=float(tp[sym]); pos['cp']=cp; pos['mv']=pos['s']*cp; pv+=pos['mv']
            # Update peak
            if cp/pos['entry']-1>0: pos['peak']=max(pos.get('peak',pos['entry']),cp)
            # Check stop-loss
            pnl=cp/pos['entry']-1
            if pnl<=SL:
                sp=cp*(1-SLIP); val=pos['s']*sp*(1-COMM); cash+=val
                pp=(sp/pos['entry']-1)*100
                tl.append({'d':str(date)[:10],'sym':sym,'act':'STOP','pr':round(sp,4),'v':round(val,2),'pnl':round(pp,2)})
                del held[sym]
            # Check trailing stop
            elif pnl>=TP:
                pk=pos.get('peak',pos['entry'])
                if cp/pk-1<=TRAIL:
                    sp=cp*(1-SLIP); val=pos['s']*sp*(1-COMM); cash+=val
                    pp=(sp/pos['entry']-1)*100
                    tl.append({'d':str(date)[:10],'sym':sym,'act':'TRAIL','pr':round(sp,4),'v':round(val,2),'pnl':round(pp,2)})
                    del held[sym]
            # Check max hold
            elif pos['hd']>=MHD:
                sp=cp*(1-SLIP); val=pos['s']*sp*(1-COMM); cash+=val
                pp=(sp/pos['entry']-1)*100
                tl.append({'d':str(date)[:10],'sym':sym,'act':'MAXH','pr':round(sp,4),'v':round(val,2),'pnl':round(pp,2)})
                del held[sym]
        else: del held[sym]
    total=cash+pv
    if date in bench_df.index: bp=float(bench_df.loc[date,'close'])
    else: bp=float(bench_df['close'].iloc[-1])
    nh.append({'d':date,'t':total,'c':cash,'p':pv,'b':bp/bstart})
    # Weekly rebalance (every 5 days)
    if (tdc%5==0 or tdc==1) and idx>0:
        r=calc_mom(date)
        if r is not None:
            ts=set(r.head(TOP_N)['s'].tolist())
            cs=set(held.keys())
            # Sell positions not in top 5
            for sym in list(held.keys()):
                if sym not in ts and sym in tp.index and not pd.isna(tp[sym]):
                    pos=held[sym]; cp=float(tp[sym])
                    sp=cp*(1-SLIP); val=pos['s']*sp*(1-COMM); cash+=val
                    pp=(sp/pos['entry']-1)*100
                    tl.append({'d':str(date)[:10],'sym':sym,'act':'SELL','pr':round(sp,4),'v':round(val,2),'pnl':round(pp,2)})
                    del held[sym]
            # Buy new positions
            slots=TOP_N-len(held)
            if slots>0 and cash>1000:
                cands=[s for s in r.head(TOP_N+3)['s'] if s not in held][:slots]
                if cands:
                    per=cash/len(cands)
                    for sym in cands:
                        if sym in tp.index and not pd.isna(tp[sym]):
                            bp2=float(tp[sym])*(1+SLIP); sh=int(per/bp2/100)*100
                            if sh>0:
                                cost=sh*bp2*(1+COMM)
                                if cost<=cash:
                                    cash-=cost
                                    held[sym]={'s':sh,'entry':bp2,'ed':str(date)[:10],'hd':0,'peak':bp2,'cp':bp2,'mv':sh*bp2}
                                    tl.append({'d':str(date)[:10],'sym':sym,'act':'BUY','pr':round(bp2,4),'v':round(cost,2),'pnl':0})
        tdc=0
    if idx%200==0 and idx>0:
        v=nh[-1]['t']/CAP; print(' ',str(date)[:10],'NAV:',round(v,4),'|Held:',len(held))

# Metrics
nv=nh[-1]['t']/CAP; nd=len(btd)-1; ny=nd/252
tr=(nv-1)*100; ar=(nv**(1/max(ny,0.01))-1)*100
bv=[float(bench_df['close'].iloc[0])]
for d in btd[1:]:
    bv.append(float(bench_df.loc[d,'close']) if d in bench_df.index else bv[-1])
bn=[v/bv[0] for v in bv]; btr=(bn[-1]-1)*100; bar=(bn[-1]**(1/max(ny,0.01))-1)*100
dr=[]
for i in range(1,len(nh)):
    if nh[i-1]['t']>0: dr.append(nh[i]['t']/nh[i-1]['t']-1)
    else: dr.append(0)
dr=np.array(dr)
ns=np.array([n['t']/CAP for n in nh])
pk2=np.maximum.accumulate(ns); dd=(ns-pk2)/pk2; mdd=dd.min()*100
if len(dr)>20:
    rf=0.025/252; ex=dr-rf
    if len(ex)>63: rs=pd.Series(ex).rolling(63).std().iloc[-1]; sp=np.sqrt(252)*np.mean(ex)/rs if rs>0 else 0
    else: sp=np.sqrt(252)*np.mean(ex)/np.std(ex) if np.std(ex)>0 else 0
else: sp=0
neg_ex=ex[ex<0] if len(ex)>0 else ex
dsd=np.std(neg_ex) if len(neg_ex)>1 else np.std(ex)
sortino=np.sqrt(252)*np.mean(ex)/dsd if dsd>0 else 0
cal=ar/abs(mdd) if mdd!=0 else 0
st=[t for t in tl if t['act']!='BUY']
if st:
    w=[t for t in st if t['pnl']>0]; l=[t for t in st if t['pnl']<=0]
    wr=len(w)/len(st)*100; aw=sum(t['pnl'] for t in w)/len(w) if w else 0
    al=sum(t['pnl'] for t in l)/len(l) if l else 0; plr=abs(aw/al) if al!=0 else float('inf')
    stops_=[t for t in st if t['act']=='STOP']; trails_=[t for t in st if t['act']=='TRAIL']
    mh_=[t for t in st if t['act']=='MAXH']; sell_=[t for t in st if t['act']=='SELL']
else: wr=aw=al=plr=0; stops_=trails_=mh_=sell_=[]
ds2=pd.Series(dr,index=btd[1:]); mr=ds2.resample('ME').apply(lambda x:(1+x).prod()-1)*100
mw=(mr>0).mean()*100 if len(mr)>0 else 0
mcl=0; cl=0
for t in st:
    if t['pnl']<=0: cl+=1; mcl=max(mcl,cl)
    else: cl=0
avg_hold_days = sum(s.get('hd',0) for s in held.values())/len(held) if held else 0

print()
print('='*60)
print('  OPTIMIZED STRATEGY v3 - PERFORMANCE')
print('='*60)
print('  Period:', str(btd[0])[:10], '~', str(btd[-1])[:10])
print('  Days:', nd, '('+str(round(ny,2))+'yrs)')
print('  Universe:', len(etf_list), 'ETFs | Hold Top', TOP_N)
print()
print('  [Returns]')
print('    Strategy Total:     '+'%+.2f'%tr+'%')
print('    Strategy Annual:    '+'%+.2f'%ar+'%')
print('    Benchmark Total:    '+'%+.2f'%btr+'%')
print('    Benchmark Annual:   '+'%+.2f'%bar+'%')
print('    Excess Annual:      '+'%+.2f'%(ar-bar)+'%')
print()
print('  [Risk]')
print('    Max Drawdown:       '+'%.2f'%mdd+'%')
print('    Sharpe Ratio:       '+'%.2f'%sp)
print('    Sortino Ratio:      '+'%.2f'%sortino)
print('    Calmar Ratio:       '+'%.2f'%cal)
print()
print('  [Trade Stats] (Total:', len(st), 'exits)')
print('    Win Rate:           '+'%.1f'%wr+'%')
print('    Avg Win:            '+'%+.2f'%aw+'%')
print('    Avg Loss:           '+'%+.2f'%al+'%')
print('    Profit/Loss:        '+'%.2f'%plr)
print('    Max Consec Losses:  '+str(mcl))
print()
print('  [Exit Reasons]')
print('    Stop Loss (-15%):   '+str(len(stops_))+' ('+('%.1f'%(len(stops_)/len(st)*100 if st else 0))+'%)')
print('    Trailing (+30/-12): '+str(len(trails_))+' ('+('%.1f'%(len(trails_)/len(st)*100 if st else 0))+'%)')
print('    Max Hold (80d):     '+str(len(mh_))+' ('+('%.1f'%(len(mh_)/len(st)*100 if st else 0))+'%)')
print('    Weekly Rebalance:   '+str(len(sell_))+' ('+('%.1f'%(len(sell_)/len(st)*100 if st else 0))+'%)')
print()
print('  [Monthly]')
print('    Monthly Win Rate:    '+'%.1f'%mw+'%')
print('    Final Capital:      '+'%.0f'%nh[-1]['t'])
print('='*60)

# Current signals
print()
print('[SIGNALS - '+str(btd[-1])[:10]+']')
print('='*60)
r2=calc_mom(btd[-1])
if r2 is not None:
    print('  {:>4s} {:>10s} {:<16s} {:>8s} {:>6s}'.format('Rank','Code','Name','Momentum','Action'))
    print('  '+'-'*50)
    for _,row in r2.head(10).iterrows():
        act='BUY >>' if row['rk']<=TOP_N else 'watch'
        print('  {:>4d} {:>10s} {:<16s} {:>8.2f} {:>6s}'.format(row['rk'],row['s'],row['n'],row['m']*100,act))
