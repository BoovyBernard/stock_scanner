# streamlit_app.py
"""
Advanced Readiness Scanner — Bloomberg-style UI + in-app scheduled scans
Single-file app: defensive scanning, MTF, charts, rule-based commentary, SQLite history,
Bloomberg-like dark theme, metric cards and scheduled scans (runs while page is open).
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import sqlite3
import time
import os
import warnings
warnings.filterwarnings("ignore")

# -------------------------
# Configuration (tweakable)
# -------------------------
HIST_DAYS = 180
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
OBV_LOOKBACK = 30
VOLUME_SPIKE_MULT = 1.4
MTF_TIMEFRAMES = ["1d", "4h", "1h"]
MTF_POSITIVE_PRICE_SCORE = 60
MTF_CONFIRM_THRESHOLD = 2
INST_FLOW_WEIGHT = 0.35
DB_PATH = "scanner_history.db"
MAX_WORKERS = 8

SCORES_CONFIG = {"STOCK": {"price": 0.45, "flow": 0.35, "fund": 0.20}}

# -------------------------
# Utility: DB
# -------------------------
def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            ticker TEXT,
            score REAL,
            signal TEXT,
            price REAL
        )
    """)
    conn.commit()
    return conn

DB_CONN = init_db()

def persist_scan(ticker, score, signal, price):
    try:
        cur = DB_CONN.cursor()
        cur.execute("INSERT INTO scans (ts,ticker,score,signal,price) VALUES (?,?,?,?,?)",
                    (datetime.utcnow().isoformat(), ticker, float(score) if score is not None else None, str(signal), float(price) if price is not None else None))
        DB_CONN.commit()
    except Exception:
        pass

def read_history(ticker=None, limit=200):
    cur = DB_CONN.cursor()
    if ticker:
        cur.execute("SELECT ts,ticker,score,signal,price FROM scans WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit))
    else:
        cur.execute("SELECT ts,ticker,score,signal,price FROM scans ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts","ticker","score","signal","price"])
    return df

# -------------------------
# YFinance safe helpers
# -------------------------
def safe_ticker(sym):
    try:
        return yf.Ticker(sym)
    except Exception:
        return None

def safe_history(sym, interval, period):
    try:
        t = safe_ticker(sym)
        if t is None:
            return pd.DataFrame()
        df = t.history(period=period, interval=interval, actions=False)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.dropna(subset=["Close"])
    except Exception:
        return pd.DataFrame()

# -------------------------
# Indicators
# -------------------------
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.rolling(period, min_periods=period).mean()
    ma_down = down.rolling(period, min_periods=period).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def obv(close, volume):
    if close.empty:
        return pd.Series(dtype=float)
    out = [0]
    for i in range(1, len(close)):
        try:
            if close.iat[i] > close.iat[i-1]:
                out.append(out[-1] + (0 if pd.isna(volume.iat[i]) else volume.iat[i]))
            elif close.iat[i] < close.iat[i-1]:
                out.append(out[-1] - (0 if pd.isna(volume.iat[i]) else volume.iat[i]))
            else:
                out.append(out[-1])
        except:
            out.append(out[-1])
    return pd.Series(out, index=close.index)

def safe_div(a,b):
    try:
        if b == 0 or pd.isna(b): return np.nan
        return a / b
    except:
        return np.nan

# -------------------------
# Defensive metrics
# -------------------------
def compute_technical_metrics(hist):
    tech = {
        "last_close": np.nan, "ema_fast": np.nan, "ema_slow": np.nan,
        "ema_cross": 0, "price_above_ema_slow": 0, "rsi": np.nan,
        "rsi_rising": 0, "higher_lows_3": 0, "obv_latest": np.nan,
        "obv_slope": 0.0, "obv_slope_pos": 0, "avg_vol_30": 0.0,
        "today_vol": 0.0, "vol_spike_up": 0
    }
    if hist.empty or "Close" not in hist.columns:
        return tech
    close = hist["Close"].astype(float).dropna()
    if close.empty:
        return tech
    tech["last_close"] = float(close.iloc[-1])
    try:
        tech["ema_fast"] = float(ema(close, EMA_FAST).iloc[-1])
        tech["ema_slow"] = float(ema(close, EMA_SLOW).iloc[-1])
        tech["ema_cross"] = int(tech["ema_fast"] > tech["ema_slow"])
        tech["price_above_ema_slow"] = int(close.iloc[-1] > tech["ema_slow"])
    except:
        pass
    try:
        r = rsi(close)
        tech["rsi"] = float(r.iloc[-1])
        tech["rsi_rising"] = int(r.iloc[-1] > r.iloc[-3]) if len(r)>=3 else 0
    except:
        pass
    try:
        lows = hist["Low"].dropna()
        if len(lows) >= 3:
            tech["higher_lows_3"] = int(lows.iloc[-1] > lows.iloc[-2] > lows.iloc[-3])
    except:
        pass
    try:
        vol = hist["Volume"]
        tech["today_vol"] = float(vol.iloc[-1]) if len(vol)>0 else 0.0
        tech["avg_vol_30"] = float(vol.rolling(30).mean().iloc[-1]) if len(vol)>=5 else float(vol.mean() if len(vol)>0 else 0.0)
        tech["vol_spike_up"] = int((tech["today_vol"] > VOLUME_SPIKE_MULT * tech["avg_vol_30"]) and (close.iloc[-1] > close.iloc[-2]))
    except:
        pass
    try:
        obv_series = obv(close, hist["Volume"] if "Volume" in hist.columns else pd.Series([0]*len(hist), index=hist.index))
        tech["obv_latest"] = float(obv_series.iloc[-1]) if not obv_series.empty else np.nan
        if len(obv_series) >= OBV_LOOKBACK:
            y = obv_series.iloc[-OBV_LOOKBACK:].values
            x = np.arange(len(y))
            if np.all(np.isfinite(y)):
                m = np.polyfit(x, y, 1)[0]
                tech["obv_slope"] = float(m)
                tech["obv_slope_pos"] = int(m > 0)
    except:
        pass
    return tech

# -------------------------
# Options (defensive)
# -------------------------
def compute_options_metrics(ticker):
    out = {"opt_expiry": None, "call_put_vol_ratio": np.nan, "call_put_oi_ratio": np.nan}
    try:
        t = safe_ticker(ticker)
        if t is None:
            return out
        exps = []
        try:
            exps = t.options or []
        except:
            exps = []
        if not exps:
            return out
        ne = exps[0]
        try:
            chain = t.option_chain(ne)
            calls = chain.calls if hasattr(chain, "calls") else pd.DataFrame()
            puts = chain.puts if hasattr(chain, "puts") else pd.DataFrame()
            cv = int(calls["volume"].fillna(0).sum()) if not calls.empty and "volume" in calls.columns else 0
            pv = int(puts["volume"].fillna(0).sum()) if not puts.empty and "volume" in puts.columns else 0
            coi = int(calls["openInterest"].fillna(0).sum()) if not calls.empty and "openInterest" in calls.columns else 0
            poi = int(puts["openInterest"].fillna(0).sum()) if not puts.empty and "openInterest" in puts.columns else 0
            out["opt_expiry"] = ne
            out["call_put_vol_ratio"] = safe_div(cv, pv)
            out["call_put_oi_ratio"] = safe_div(coi, poi)
        except:
            pass
    except:
        pass
    return out

# -------------------------
# Scoring
# -------------------------
def score_price_momentum(tech):
    score = 0.0
    try:
        score += tech["ema_cross"] * 25
        score += tech["price_above_ema_slow"] * 25
        score += tech["rsi_rising"] * 15
        score += tech["higher_lows_3"] * 15
        score += tech["obv_slope_pos"] * 20
    except:
        pass
    return float(score)

def score_volume_flow(tech, opt):
    score = 0.0
    try:
        if tech["vol_spike_up"]:
            score += 40
        if opt.get("call_put_vol_ratio") and opt.get("call_put_vol_ratio") > 1.2:
            score += 30
        if opt.get("call_put_oi_ratio") and opt.get("call_put_oi_ratio") > 1.2:
            score += 30
    except:
        pass
    return float(score)

def inst_flow_proxy(tech, opt):
    score = 50.0
    try:
        if tech["obv_slope_pos"]:
            score += 12
        if tech["vol_spike_up"]:
            score += 8
        if opt.get("call_put_oi_ratio") and opt.get("call_put_oi_ratio") > 1.1:
            score += 10
    except:
        pass
    return float(score)

def get_buy_signal(score):
    if score >= 82: return "STRONG BUY"
    if score >= 74: return "BUY"
    if score >= 66: return "WATCHLIST"
    return "NO TRADE"

# -------------------------
# Buy-the-dip
# -------------------------
def detect_buy_the_dip(hist):
    if hist.empty: return False, np.nan, np.nan
    try:
        look = hist["Close"].iloc[-20:]
        recent_high = float(look.max())
        last = float(look.iloc[-1])
        pullback = (recent_high - last) / recent_high if recent_high>0 else 0.0
        is_btd = (pullback >= 0.02) and (pullback <= 0.12)
        return bool(is_btd), float(round(pullback*100,3)), recent_high
    except:
        return False, np.nan, np.nan

# -------------------------
# MTF
# -------------------------
def compute_mtf_scores(ticker):
    details = {}
    positives = 0
    for tf in MTF_TIMEFRAMES:
        period = f"{HIST_DAYS}d" if tf == "1d" else ("120d" if tf == "4h" else "60d")
        hist = safe_history(ticker, tf, period)
        tech = compute_technical_metrics(hist)
        ps = score_price_momentum(tech)
        details[tf] = round(ps,2)
        if ps >= MTF_POSITIVE_PRICE_SCORE:
            positives += 1
    confirmed = positives >= MTF_CONFIRM_THRESHOLD
    return positives, confirmed, details

# -------------------------
# Rule-based commentary
# -------------------------
def ai_commentary(d):
    score = d.get("final_score")
    parts = []
    if score is None:
        return "No score available."
    if score >= 82:
        parts.append("Strong conviction — multiple timeframe alignment.")
    elif score >= 74:
        parts.append("Positive bias — watch for confirmation.")
    elif score >= 66:
        parts.append("Neutral; on the watchlist.")
    else:
        parts.append("No trade recommended.")
    if d.get("price_score",0) >= 60:
        parts.append("Price momentum is favorable.")
    else:
        parts.append("Price momentum is weak.")
    if d.get("flow_score",0) >= 50:
        parts.append("Flow signals supportive.")
    else:
        parts.append("Flow signals quiet.")
    mtf = d.get("mtf_details",{})
    pos = sum(1 for v in mtf.values() if isinstance(v,(int,float)) and v>=MTF_POSITIVE_PRICE_SCORE)
    parts.append(f"MTF positive count: {pos}")
    if d.get("btd"):
        parts.append(f"Buy-the-dip detected (pullback {d.get('btd_pullback')}%).")
    return " ".join(parts)

# -------------------------
# Core analyze function
# -------------------------
def analyze_ticker_full(ticker, include_options=True):
    out = {"ticker":ticker, "error":None}
    try:
        daily = safe_history(ticker, "1d", f"{HIST_DAYS}d")
        tech_daily = compute_technical_metrics(daily)
        opt = compute_options_metrics(ticker) if include_options else {"opt_expiry":None,"call_put_vol_ratio":np.nan,"call_put_oi_ratio":np.nan}
        price_sc = score_price_momentum(tech_daily)
        flow_sc = score_volume_flow(tech_daily,opt)
        inst_sc = inst_flow_proxy(tech_daily,opt)
        p_w = SCORES_CONFIG["STOCK"]["price"]
        f_w = SCORES_CONFIG["STOCK"]["flow"]
        inst_w = INST_FLOW_WEIGHT
        final = price_sc * p_w + flow_sc * f_w + inst_sc * inst_w
        mtf_count, mtf_confirm, mtf_details = compute_mtf_scores(ticker)
        btd_flag, btd_pull, btd_high = detect_buy_the_dip(daily)
        out.update({
            "last_close": tech_daily.get("last_close"),
            "price_score": round(price_sc,2),
            "flow_score": round(flow_sc,2),
            "inst_score": round(inst_sc,2),
            "final_score": round(final,2),
            "signal": get_buy_signal(final),
            "mtf_count": mtf_count,
            "mtf_confirm": bool(mtf_confirm),
            "mtf_details": mtf_details,
            "btd": btd_flag,
            "btd_pullback": btd_pull,
            "btd_recent_high": btd_high,
            "opt_expiry": opt.get("opt_expiry"),
            "opt_call_put_vol_ratio": opt.get("call_put_vol_ratio"),
            "opt_call_put_oi_ratio": opt.get("call_put_oi_ratio"),
            "error": None
        })
    except Exception as e:
        out["error"] = str(e)
    return out

# -------------------------
# UI: styling (Bloomberg look)
# -------------------------
BGC = "#0b1020"        # deep navy black
CARD = "#0f1724"       # slightly lighter card
NEON_GREEN = "#00ff7f" # bullish
AMBER = "#ffb84d"      # neutral/borderline
DANGER = "#ff4d4d"     # bearish
TEXT = "#e6eef5"

st.set_page_config(page_title="Readiness Scanner — Bloomberg UI", layout="wide")
# inject CSS to tighten visuals & apply dark theme
st.markdown(f"""
    <style>
    :root {{
        --bg: {BGC};
        --card: {CARD};
        --neon: {NEON_GREEN};
        --amber: {AMBER};
        --danger: {DANGER};
        --text: {TEXT};
    }}
    .stApp {{
        background: linear-gradient(180deg, #07101a 0%, #0b1020 100%);
        color: var(--text);
    }}
    .card {{
        background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(0,0,0,0.03));
        border-radius: 8px;
        padding: 14px;
        margin: 8px 0;
        box-shadow: 0 6px 18px rgba(0,0,0,0.6);
        border: 1px solid rgba(255,255,255,0.03);
    }}
    .small-muted {{
        color: #9fb0c8;
        font-size:12px;
    }}
    .signal-pill {{
        padding:6px 10px;
        border-radius:999px;
        font-weight:700;
        color:#001411;
    }}
    .sig-strong {{ background: linear-gradient(90deg, #a7ffbf, #00ff7f); color:#04220d; }}
    .sig-buy {{ background: linear-gradient(90deg, #7fffd4, #00cc66); color:#03170f; }}
    .sig-watch {{ background: linear-gradient(90deg, #ffdca8, #ffb84d); color:#2f1a00; }}
    .sig-none {{ background: linear-gradient(90deg, #ff9b9b, #ff4d4d); color:#2a0505; }}
    .metric-card {{"background": "transparent"}}
    .ticker-list-item:hover {{ background: rgba(255,255,255,0.02); }}
    </style>
""", unsafe_allow_html=True)

# -------------------------
# Sidebar controls + scheduler
# -------------------------
st.sidebar.markdown("<div style='padding:8px;background:transparent'><h3 style='color:var(--text)'>Scanner Controls</h3></div>", unsafe_allow_html=True)
mode = st.sidebar.selectbox("Mode", ["Manual tickers", "Prebuilt group"])
if mode == "Manual tickers":
    raw = st.sidebar.text_area("Tickers (comma separated)", value="AAPL, NVDA, MSFT, TSLA")
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
else:
    grp = st.sidebar.selectbox("Group", ["DOW30","NASDAQ","CRYPTO","FOREX","US100","US500","SECTORS","EFTS"])
    GROUPS = {
        "DOW30": ["AAPL","MSFT","JPM","GS","CVX","CAT","MMM","V","DIS","KO","WMT"],
        "NASDAQ": ["AAPL","MSFT","NVDA","TSLA","AMZN","META","ADBE"],
        "CRYPTO": ["BTC-USD","ETH-USD","SOL-USD","ADA-USD"],
        "FOREX": ["EURUSD=X","GBPUSD=X","USDJPY=X","USDCAD=X"],
        "US100": [],
        "US500": [],
        "SECTORS": [],
        "EFTS": [],
    }
    tickers = GROUPS.get(grp, [])

include_options = st.sidebar.checkbox("Include options metrics", value=True)
workers = st.sidebar.slider("Parallel workers", min_value=1, max_value=12, value=min(MAX_WORKERS,6))
run_now = st.sidebar.button("▶️ Run Now")

st.sidebar.markdown("---")
st.sidebar.markdown("<div style='color:var(--text)'>Auto-scan (runs when page is opened & interval reached)</div>", unsafe_allow_html=True)
auto_scan = st.sidebar.checkbox("Enable Auto-scan", value=False)
col1, col2 = st.sidebar.columns([2,1])
with col1:
    interval_min = st.number_input("Interval (minutes)", min_value=5, max_value=1440, value=60, step=5)
with col2:
    start_on_load = st.checkbox("Run on load", value=True)

# initialize scheduler state
if "last_auto_scan" not in st.session_state:
    st.session_state.last_auto_scan = None
if "next_auto_scan" not in st.session_state:
    st.session_state.next_auto_scan = None

# determine if auto-scan should run now (synchronous)
def due_for_auto_run():
    if not auto_scan:
        return False
    now = datetime.utcnow()
    last = st.session_state.get("last_auto_scan")
    if last is None:
        # if user wants run on load -> treat as due
        return start_on_load
    try:
        last_dt = datetime.fromisoformat(last)
    except Exception:
        last_dt = None
    if last_dt is None:
        return start_on_load
    next_dt = last_dt + timedelta(minutes=int(interval_min))
    st.session_state.next_auto_scan = next_dt.isoformat()
    return now >= next_dt

# run scanning function (synchronous, updates session_state)
def run_scan(tickers_list):
    results = []
    total = len(tickers_list) if tickers_list else 0
    if total == 0:
        return results
    with st.spinner(f"Scanning {total} tickers..."):
        progress_bar = st.progress(0)
        with ThreadPoolExecutor(max_workers=min(workers,total)) as ex:
            futures = {ex.submit(analyze_ticker_full, t, include_options): t for t in tickers_list}
            done = 0
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"ticker": t, "error": str(e)}
                results.append(r)
                done += 1
                progress_bar.progress(done/total)
    # persist to DB
    for r in results:
        try:
            persist_scan(r.get("ticker"), r.get("final_score"), r.get("signal"), r.get("last_close"))
        except:
            pass
    # update last_auto_scan
    st.session_state.last_auto_scan = datetime.utcnow().isoformat()
    st.session_state.next_auto_scan = (datetime.utcnow() + timedelta(minutes=int(interval_min))).isoformat()
    st.success(f"Scan finished — {len(results)} tickers scanned.")
    return results

# Trigger run_now or auto-run if due
if run_now:
    st.session_state.scan_results = run_scan(tickers)
    # show results below (page will re-render)
elif auto_scan and due_for_auto_run():
    # run it now (synchronous)
    st.session_state.scan_results = run_scan(tickers)

# Ensure scan_results is present
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []

# top header with last/next auto-run
with st.container():
    left, mid, right = st.columns([1,4,1])
    with left:
        st.markdown(f"<div style='color:var(--text);padding:6px'>Last Auto: <b>{st.session_state.get('last_auto_scan') or 'Never'}</b></div>", unsafe_allow_html=True)
    with mid:
        st.markdown("<h2 style='margin:6px;color:var(--neon)'>READINESS SCANNER — LIVE</h2>", unsafe_allow_html=True)
    with right:
        st.markdown(f"<div style='color:#9fb0c8;padding:6px;text-align:right'>Next Auto: <b>{st.session_state.get('next_auto_scan') or '—'}</b></div>", unsafe_allow_html=True)

# -------------------------
# Results Summary Area
# -------------------------
st.markdown("<div class='card'>", unsafe_allow_html=True)
st.markdown("<div style='display:flex;justify-content:space-between;align-items:center'>", unsafe_allow_html=True)
st.markdown("<div style='font-size:18px;color:var(--text)'><b>Results Summary</b> <span style='color:#9fb0c8;font-size:12px'>&nbsp; (latest session)</span></div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

if not st.session_state.scan_results:
    st.markdown("<div style='padding:18px;color:#9fb0c8'>No scan results — run a scan (Run Now) or enable Auto-scan.</div>", unsafe_allow_html=True)
else:
    df = pd.json_normalize(st.session_state.scan_results)
    # ensure ticker column exists
    if 'ticker' in df.columns and 'ticker' not in df.columns:
        df = df.rename(columns={'ticker':'Ticker'})
    # friendly display table
    display_cols = [c for c in ["ticker","final_score","signal","price_score","flow_score","inst_score","mtf_count","mtf_confirm","btd","btd_pullback"] if c in df.columns]
    df_display = df[display_cols].copy()
    df_display = df_display.sort_values("final_score", ascending=False).reset_index(drop=True)
    # color-coded row style using emojis + badges
    def signal_badge(s):
        if s == "STRONG BUY":
            return f"<span class='signal-pill sig-strong'>{s}</span>"
        if s == "BUY":
            return f"<span class='signal-pill sig-buy'>{s}</span>"
        if s == "WATCHLIST":
            return f"<span class='signal-pill sig-watch'>{s}</span>"
        return f"<span class='signal-pill sig-none'>{s}</span>"
    # display as Streamlit table with HTML in columns (use st.write for safer output)
    # Build a compact card grid for top 6
    top_n = df_display.head(6)
    cards = st.columns(6)
    for i, (_, row) in enumerate(top_n.iterrows()):
        sig_html = signal_badge(row.get("signal","N/A"))
        score = row.get("final_score","N/A")
        tck = row.get("ticker","")
        with cards[i]:
            st.markdown(f"""
                <div style='background:{CARD};padding:10px;border-radius:8px;min-height:110px'>
                    <div style='font-size:14px;color:#9fb0c8'>{tck}</div>
                    <div style='font-size:22px;color:var(--neon);font-weight:700;margin-top:6px'>{score}</div>
                    <div style='margin-top:8px'>{sig_html}</div>
                </div>
            """, unsafe_allow_html=True)
    st.markdown("---")
    # full dataframe
    st.dataframe(df_display.style.format({"final_score":"{:.2f}"}), use_container_width=True)
st.markdown("</div>", unsafe_allow_html=True)

# -------------------------
# Detail viewer / Charts
# -------------------------
st.markdown("<div class='card' style='margin-top:12px'>", unsafe_allow_html=True)
st.markdown("<h3 style='color:var(--text)'>Ticker Detail / Charts</h3>", unsafe_allow_html=True)

detail_cols = st.columns([2,1])
detail_choice = detail_cols[0].selectbox("Pick ticker to inspect", options=sorted({r.get("ticker") for r in st.session_state.scan_results}) if st.session_state.scan_results else tickers)
if st.button("Refresh detail"):
    pass

if detail_choice:
    detail_res = analyze_ticker_full(detail_choice, include_options=include_options)
    if detail_res.get("error"):
        st.error("Detail error: " + str(detail_res.get("error")))
    else:
        # top row metrics
        a,b,c,d = st.columns([2,1,1,1])
        a.metric("Ticker", detail_choice)
        a.write("")  # spacer
        b.metric("Readiness", detail_res.get("final_score"))
        # colored signal pill
        sig = detail_res.get("signal","N/A")
        if sig == "STRONG BUY":
            c.markdown(f"<div class='signal-pill sig-strong'>{sig}</div>", unsafe_allow_html=True)
        elif sig == "BUY":
            c.markdown(f"<div class='signal-pill sig-buy'>{sig}</div>", unsafe_allow_html=True)
        elif sig == "WATCHLIST":
            c.markdown(f"<div class='signal-pill sig-watch'>{sig}</div>", unsafe_allow_html=True)
        else:
            c.markdown(f"<div class='signal-pill sig-none'>{sig}</div>", unsafe_allow_html=True)
        d.metric("MTF +", detail_res.get("mtf_count"))

        # charts
        try:
            histd = safe_history(detail_choice, "1d", f"{HIST_DAYS}d")
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=histd.index, open=histd["Open"], high=histd["High"], low=histd["Low"], close=histd["Close"], name="price"))
            # add ema lines
            try:
                fig.add_trace(go.Scatter(x=histd.index, y=ema(histd["Close"], EMA_FAST), name=f"EMA{EMA_FAST}", line=dict(width=1, dash="dot", color="#7fffd4")))
                fig.add_trace(go.Scatter(x=histd.index, y=ema(histd["Close"], EMA_SLOW), name=f"EMA{EMA_SLOW}", line=dict(width=1, dash="dot", color="#ffb84d")))
            except:
                pass
            fig.update_layout(plot_bgcolor=BGC, paper_bgcolor=BGC, font_color=TEXT, height=420, margin=dict(t=20,b=20))
            st.plotly_chart(fig, use_container_width=True)

            # RSI
            r = rsi(histd["Close"])
            r_fig = px.line(x=r.index, y=r.values, labels={"x":"Date","y":"RSI"})
            r_fig.update_layout(plot_bgcolor=BGC, paper_bgcolor=BGC, font_color=TEXT, height=200)
            r_fig.add_hline(y=70, line_dash="dash", line_color="#ff4d4d")
            r_fig.add_hline(y=30, line_dash="dash", line_color="#00ff7f")
            st.plotly_chart(r_fig, use_container_width=True)

            # volume + obv
            vol = histd["Volume"] if "Volume" in histd.columns else pd.Series([0]*len(histd), index=histd.index)
            obv_series = obv(histd["Close"], vol)
            vol_fig = go.Figure()
            vol_fig.add_trace(go.Bar(x=histd.index, y=vol, name="Volume"))
            vol_fig.add_trace(go.Scatter(x=obv_series.index, y=obv_series, name="OBV", yaxis="y2"))
            vol_fig.update_layout(plot_bgcolor=BGC, paper_bgcolor=BGC, font_color=TEXT, height=260,
                                  yaxis=dict(title="Volume"), yaxis2=dict(title="OBV", overlaying="y", side="right"))
            st.plotly_chart(vol_fig, use_container_width=True)
        except Exception as e:
            st.info("Charts unavailable: " + str(e))

        # options snapshot
        st.markdown("**Options snapshot**")
        st.json({
            "expiry": detail_res.get("opt_expiry"),
            "call_put_vol_ratio": detail_res.get("opt_call_put_vol_ratio"),
            "call_put_oi_ratio": detail_res.get("opt_call_put_oi_ratio")
        })

        # MTF details & commentary
        st.markdown("**Multi-timeframe breakdown**")
        st.write(detail_res.get("mtf_details"))
        st.markdown("**AI-style commentary (rule-based)**")
        st.info(ai_commentary(detail_res))

st.markdown("</div>", unsafe_allow_html=True)

# -------------------------
# Persisted History & export
# -------------------------
st.markdown("<div class='card' style='margin-top:14px'>", unsafe_allow_html=True)
st.markdown("<h3 style='color:var(--text)'>Persisted History & Exports</h3>", unsafe_allow_html=True)
hist_all = read_history(limit=500)
if hist_all.empty:
    st.info("No persisted history yet.")
else:
    st.dataframe(hist_all.head(200), use_container_width=True)
    # aggregated
    agg = hist_all.groupby("ticker")["score"].agg(["mean","count"]).reset_index().sort_values("mean", ascending=False).head(30)
    st.plotly_chart(px.bar(agg, x="ticker", y="mean", title="Top average scores (persisted)"), use_container_width=True)

if st.session_state.get("scan_results"):
    df_export = pd.json_normalize(st.session_state["scan_results"])
    st.download_button("Download last session CSV", df_export.to_csv(index=False).encode("utf-8"), file_name="latest_scan.csv", mime="text/csv")
st.markdown("</div>", unsafe_allow_html=True)

# -------------------------
# Footer guidance
# -------------------------
st.markdown("<div style='padding:14px;color:#9fb0c8;font-size:12px'>Bloomberg-style theme. Auto-scan runs when page is opened and the scheduled interval has been reached. For continuous server-side scheduling, use Streamlit Cloud scheduled jobs or an external cron to call your endpoint.</div>", unsafe_allow_html=True)
