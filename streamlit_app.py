# streamlit_app.py
"""
Advanced Readiness Scanner — Bloomberg-style UI + Watchlist + SQLite persistence
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
import warnings
warnings.filterwarnings("ignore")

# ------------------------------------
# CONFIG VALUES
# ------------------------------------
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

# ------------------------------------
# INIT DB (scans + watchlist)
# ------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()

    # SCANS TABLE
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

    # WATCHLIST TABLE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT UNIQUE,
        added_ts TEXT
    )
    """)

    conn.commit()
    return conn

DB_CONN = init_db()


# ------------------------------------
# WATCHLIST — SQLite persistence
# ------------------------------------
def load_watchlist():
    cur = DB_CONN.cursor()
    cur.execute("SELECT ticker FROM watchlist ORDER BY ticker ASC")
    rows = cur.fetchall()
    return [r[0] for r in rows]

def add_to_watchlist(ticker):
    try:
        cur = DB_CONN.cursor()
        cur.execute("INSERT OR IGNORE INTO watchlist (ticker, added_ts) VALUES (?,?)",
                    (ticker, datetime.utcnow().isoformat()))
        DB_CONN.commit()
    except:
        pass

def remove_from_watchlist(ticker):
    try:
        cur = DB_CONN.cursor()
        cur.execute("DELETE FROM watchlist WHERE ticker=?", (ticker,))
        DB_CONN.commit()
    except:
        pass


# ------------------------------------
# Persist Scans
# ------------------------------------
def persist_scan(ticker, score, signal, price):
    try:
        cur = DB_CONN.cursor()
        cur.execute("INSERT INTO scans (ts,ticker,score,signal,price) VALUES (?,?,?,?,?)",
                    (datetime.utcnow().isoformat(), ticker,
                     float(score) if score is not None else None,
                     str(signal),
                     float(price) if price is not None else None))
        DB_CONN.commit()
    except:
        pass

def read_history(ticker=None, limit=200):
    cur = DB_CONN.cursor()
    if ticker:
        cur.execute("SELECT ts,ticker,score,signal,price FROM scans WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit))
    else:
        cur.execute("SELECT ts,ticker,score,signal,price FROM scans ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["ts","ticker","score","signal","price"])


# ------------------------------------
# SAFE YFINANCE HELPERS
# ------------------------------------
def safe_ticker(sym):
    try: return yf.Ticker(sym)
    except: return None

def safe_history(sym, interval, period):
    try:
        t = safe_ticker(sym)
        if t is None:
            return pd.DataFrame()
        df = t.history(period=period, interval=interval, actions=False)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.dropna(subset=["Close"])
    except:
        return pd.DataFrame()


# ------------------------------------
# INDICATORS (EMA, RSI, OBV)
# ------------------------------------
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
    if close.empty: return pd.Series(dtype=float)
    out = [0]
    for i in range(1, len(close)):
        if close.iat[i] > close.iat[i-1]:
            out.append(out[-1] + volume.iat[i])
        elif close.iat[i] < close.iat[i-1]:
            out.append(out[-1] - volume.iat[i])
        else:
            out.append(out[-1])
    return pd.Series(out, index=close.index)


# ------------------------------------
# METRICS + SCORING
# ------------------------------------
def compute_technical_metrics(hist):
    tech = {
        "last_close": np.nan, "ema_fast": np.nan, "ema_slow": np.nan,
        "ema_cross": 0, "price_above_ema_slow": 0, "rsi": np.nan,
        "rsi_rising": 0, "higher_lows_3": 0, "obv_latest": np.nan,
        "obv_slope": 0.0, "obv_slope_pos": 0, "avg_vol_30": 0.0,
        "today_vol": 0.0, "vol_spike_up": 0
    }

    if hist.empty:
        return tech

    close = hist["Close"]
    tech["last_close"] = float(close.iloc[-1])

    # EMA CROSS + PRICE ABOVE SLOW EMA
    try:
        tech["ema_fast"] = float(ema(close, EMA_FAST).iloc[-1])
        tech["ema_slow"] = float(ema(close, EMA_SLOW).iloc[-1])
        tech["ema_cross"] = int(tech["ema_fast"] > tech["ema_slow"])
        tech["price_above_ema_slow"] = int(close.iloc[-1] > tech["ema_slow"])
    except:
        pass

    # RSI
    try:
        r = rsi(close)
        tech["rsi"] = float(r.iloc[-1])
        if len(r) >= 3:
            tech["rsi_rising"] = int(r.iloc[-1] > r.iloc[-3])
    except:
        pass

    # HIGHER LOWS
    try:
        lows = hist["Low"]
        if len(lows) >= 3:
            tech["higher_lows_3"] = int(lows.iloc[-1] > lows.iloc[-2] > lows.iloc[-3])
    except:
        pass

    # VOLUME
    try:
        vol = hist["Volume"]
        tech["today_vol"] = float(vol.iloc[-1])
        tech["avg_vol_30"] = float(vol.rolling(30).mean().iloc[-1])
        tech["vol_spike_up"] = int(
            (tech["today_vol"] > VOLUME_SPIKE_MULT * tech["avg_vol_30"])
            and (close.iloc[-1] > close.iloc[-2])
        )
    except:
        pass

    # OBV
    try:
        obv_series = obv(close, hist["Volume"])
        tech["obv_latest"] = float(obv_series.iloc[-1])
        if len(obv_series) >= OBV_LOOKBACK:
            y = obv_series.iloc[-OBV_LOOKBACK:].values
            x = np.arange(len(y))
            slope = np.polyfit(x, y, 1)[0]
            tech["obv_slope"] = slope
            tech["obv_slope_pos"] = int(slope > 0)
    except:
        pass

    return tech


def score_price_momentum(tech):
    s = 0
    s += tech["ema_cross"] * 25
    s += tech["price_above_ema_slow"] * 25
    s += tech["rsi_rising"] * 15
    s += tech["higher_lows_3"] * 15
    s += tech["obv_slope_pos"] * 20
    return float(s)

def score_volume_flow(tech, opt):
    s = 0
    if tech["vol_spike_up"]: s += 40
    if opt.get("call_put_vol_ratio",0) > 1.2: s += 30
    if opt.get("call_put_oi_ratio",0) > 1.2: s += 30
    return float(s)

def inst_flow_proxy(tech, opt):
    s = 50.0
    if tech["obv_slope_pos"]: s += 12
    if tech["vol_spike_up"]: s += 8
    if opt.get("call_put_oi_ratio",0) > 1.1: s += 10
    return float(s)

def get_buy_signal(score):
    if score >= 82: return "STRONG BUY"
    if score >= 74: return "BUY"
    if score >= 66: return "WATCHLIST"
    return "NO TRADE"


# ------------------------------------
# BUY-THE-DIP
# ------------------------------------
def detect_buy_the_dip(hist):
    if hist.empty: return False, np.nan, np.nan
    look = hist["Close"].iloc[-20:]
    recent_high = float(look.max())
    last = float(look.iloc[-1])
    pullback = (recent_high - last) / recent_high if recent_high > 0 else 0
    is_btd = 0.02 <= pullback <= 0.12
    return is_btd, round(pullback*100, 2), recent_high


# ------------------------------------
# MULTI TIMEFRAME SCORING
# ------------------------------------
def compute_mtf_scores(ticker):
    details = {}
    positives = 0
    for tf in MTF_TIMEFRAMES:
        period = f"{HIST_DAYS}d" if tf == "1d" else "120d" if tf == "4h" else "60d"
        hist = safe_history(ticker, tf, period)
        tech = compute_technical_metrics(hist)
        score = score_price_momentum(tech)
        details[tf] = round(score, 2)
        if score >= MTF_POSITIVE_PRICE_SCORE:
            positives += 1
    confirmed = positives >= MTF_CONFIRM_THRESHOLD
    return positives, confirmed, details


# ------------------------------------
# FULL TICKER ANALYSIS
# ------------------------------------
def analyze_ticker_full(ticker, include_options=True):
    out = {"ticker": ticker, "error": None}
    try:
        daily = safe_history(ticker, "1d", f"{HIST_DAYS}d")
        tech = compute_technical_metrics(daily)

        opt = {"call_put_vol_ratio": np.nan, "call_put_oi_ratio": np.nan}
        try:
            t = safe_ticker(ticker)
            if include_options and t and t.options:
                exp = t.options[0]
                chain = t.option_chain(exp)
                cv = chain.calls["volume"].sum()
                pv = chain.puts["volume"].sum()
                coi = chain.calls["openInterest"].sum()
                poi = chain.puts["openInterest"].sum()
                opt["call_put_vol_ratio"] = cv / pv if pv > 0 else np.nan
                opt["call_put_oi_ratio"] = coi / poi if poi > 0 else np.nan
        except:
            pass

        price_sc = score_price_momentum(tech)
        flow_sc = score_volume_flow(tech, opt)
        inst_sc = inst_flow_proxy(tech, opt)

        final = (price_sc * SCORES_CONFIG["STOCK"]["price"] +
                 flow_sc * SCORES_CONFIG["STOCK"]["flow"] +
                 inst_sc * INST_FLOW_WEIGHT)

        mtf_count, mtf_confirm, mtf_details = compute_mtf_scores(ticker)
        btd_flag, btd_pull, btd_high = detect_buy_the_dip(daily)

        out.update({
            "last_close": tech["last_close"],
            "price_score": price_sc, "flow_score": flow_sc, "inst_score": inst_sc,
            "final_score": round(final, 2),
            "signal": get_buy_signal(final),
            "mtf_count": mtf_count, "mtf_confirm": mtf_confirm,
            "mtf_details": mtf_details,
            "btd": btd_flag, "btd_pullback": btd_pull,
            "opt_call_put_vol_ratio": opt["call_put_vol_ratio"],
            "opt_call_put_oi_ratio": opt["call_put_oi_ratio"]
        })

    except Exception as e:
        out["error"] = str(e)

    return out


# ------------------------------------
# STREAMLIT UI START
# ------------------------------------
st.set_page_config(page_title="Readiness Scanner", layout="wide")

# Load Watchlist at startup
if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# -------------------------
# SIDEBAR
# -------------------------
st.sidebar.header("Scanner Controls")

mode = st.sidebar.selectbox("Mode", ["Manual tickers", "Prebuilt group"])

if mode == "Manual tickers":
    raw = st.sidebar.text_area("Tickers", "AAPL, NVDA, MSFT, TSLA")
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
else:
    GROUPS = {
        "CRYPTO": ["BTC-USD","ETH-USD","SOL-USD","ADA-USD"],
        "FOREX": ["EURUSD=X","GBPUSD=X","USDJPY=X","USDCAD=X"],
    }
    grp = st.sidebar.selectbox("Group", list(GROUPS.keys()))
    tickers = GROUPS[grp]

include_options = st.sidebar.checkbox("Include Options Data", True)
workers = st.sidebar.slider("Parallel Workers", 1, 12, 6)
run_now = st.sidebar.button("Run Scan")

# -------------------------
# RUN SCAN FUNCTION
# -------------------------
def run_scan(ticker_list):
    results = []
    if not ticker_list: return results
    with st.spinner("Scanning..."):
        with ThreadPoolExecutor(max_workers=min(workers, len(ticker_list))) as ex:
            futures = {ex.submit(analyze_ticker_full, t, include_options): t for t in ticker_list}
            for fut in as_completed(futures):
                r = fut.result() if fut else None
                results.append(r)
                persist_scan(r["ticker"], r["final_score"], r["signal"], r["last_close"])
    return results

# Run scan
if run_now:
    st.session_state.scan_results = run_scan(tickers)

if "scan_results" not in st.session_state:
    st.session_state.scan_results = []

# ------------------------------------
# RESULTS SUMMARY
# ------------------------------------
st.header("Scan Results")

if st.session_state.scan_results:
    df = pd.json_normalize(st.session_state.scan_results)
    df = df.sort_values("final_score", ascending=False)
    st.dataframe(df)
else:
    st.warning("No scan yet.")

# ------------------------------------
# WATCHLIST PANEL
# ------------------------------------
st.markdown("---")
st.subheader("📌 Watchlist (SQLite Persistent)")

watchlist = st.session_state.watchlist

# Display watchlist
if not watchlist:
    st.info("Watchlist is empty.")
else:
    col_a, col_b = st.columns([3, 1])

    with col_a:
        st.write(", ".join(watchlist))

    with col_b:
        if st.button("🔄 Scan Watchlist"):
            wl_results = run_scan(watchlist)
            st.session_state.wl_results = wl_results

    # Display watchlist scan results
    if "wl_results" in st.session_state and st.session_state.wl_results:
        df_wl = pd.json_normalize(st.session_state.wl_results)
        st.dataframe(df_wl[["ticker","final_score","signal","mtf_count","btd"]])

    # Remove buttons
    for t in watchlist:
        if st.button(f"❌ Remove {t}", key=f"rm_{t}"):
            remove_from_watchlist(t)
            st.session_state.watchlist = load_watchlist()
            st.experimental_rerun()

# ------------------------------------
# DETAIL VIEW
# ------------------------------------
st.markdown("---")
st.subheader("Ticker Detail")

detail_choice = st.selectbox("Select ticker", tickers)

if detail_choice:
    res = analyze_ticker_full(detail_choice, include_options)

    st.json(res)

    # Add/remove watchlist
    if detail_choice not in watchlist:
        if st.button(f"📌 Add {detail_choice} to Watchlist"):
            add_to_watchlist(detail_choice)
            st.session_state.watchlist = load_watchlist()
            st.success(f"{detail_choice} added.")
    else:
        if st.button(f"❌ Remove {detail_choice} from Watchlist"):
            remove_from_watchlist(detail_choice)
            st.session_state.watchlist = load_watchlist()
            st.warning(f"{detail_choice} removed.")

# ------------------------------------
# HISTORY TABLE
# ------------------------------------
st.markdown("---")
st.subheader("Scan History")

hist = read_history(limit=200)
st.dataframe(hist)

# End
