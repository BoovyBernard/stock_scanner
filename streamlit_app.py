# streamlit_app.py
"""
Advanced Readiness Scanner — single-file Streamlit app
Features:
 - Defensive scanner (yfinance)
 - Multi-timeframe scoring (1d, 4h, 1h)
 - Candlestick + RSI + OBV charts
 - Rule-based "AI" commentary for each ticker
 - SQLite history storage and trend gauge + history charts
 - Download CSV export
"""
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import sqlite3
import os
import math
import warnings
warnings.filterwarnings("ignore")

# ----------------------------
# Configuration
# ----------------------------
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

# Score config (kept simple)
SCORES_CONFIG = {
    "STOCK": {"price": 0.45, "flow": 0.35, "fund": 0.20},
}

# ----------------------------
# Utilities: SQLite history
# ----------------------------
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

def persist_scan(ticker, score, signal, price, conn=DB_CONN):
    cur = conn.cursor()
    cur.execute("INSERT INTO scans (ts,ticker,score,signal,price) VALUES (?,?,?,?,?)",
                (datetime.utcnow().isoformat(), ticker, float(score) if score is not None else None, str(signal), float(price) if price is not None else None))
    conn.commit()

def read_history(ticker=None, limit=200, conn=DB_CONN):
    cur = conn.cursor()
    if ticker:
        cur.execute("SELECT ts,ticker,score,signal,price FROM scans WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit))
    else:
        cur.execute("SELECT ts,ticker,score,signal,price FROM scans ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts","ticker","score","signal","price"])
    return df

# ----------------------------
# Safe wrappers around yfinance
# ----------------------------
def safe_ticker(t):
    try:
        return yf.Ticker(t)
    except Exception:
        return None

def safe_history(ticker, interval, period):
    try:
        t = safe_ticker(ticker)
        if t is None:
            return pd.DataFrame()
        df = t.history(period=period, interval=interval, actions=False)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.dropna(subset=["Close"])
    except Exception:
        return pd.DataFrame()

# ----------------------------
# Indicator helpers
# ----------------------------
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.rolling(period, min_periods=period).mean()
    ma_down = down.rolling(period, min_periods=period).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def obv(series, volume):
    if series.empty:
        return pd.Series(dtype=float)
    obv_values = [0]
    for i in range(1, len(series)):
        if series.iat[i] > series.iat[i-1]:
            obv_values.append(obv_values[-1] + (0 if volume.isna().iat[i] else volume.iat[i]))
        elif series.iat[i] < series.iat[i-1]:
            obv_values.append(obv_values[-1] - (0 if volume.isna().iat[i] else volume.iat[i]))
        else:
            obv_values.append(obv_values[-1])
    return pd.Series(obv_values, index=series.index)

def safe_div(a,b):
    try:
        if b == 0 or pd.isna(b):
            return np.nan
        return a/b
    except:
        return np.nan

# ----------------------------
# Defensive technical metrics
# ----------------------------
def compute_technical_metrics(hist):
    tech = {
        "last_close": np.nan,
        "ema_fast": np.nan,
        "ema_slow": np.nan,
        "ema_cross": 0,
        "price_above_ema_slow": 0,
        "rsi": np.nan,
        "rsi_rising": 0,
        "higher_lows_3": 0,
        "obv_latest": np.nan,
        "obv_slope": 0.0,
        "obv_slope_pos": 0,
        "avg_vol_30": 0.0,
        "today_vol": 0.0,
        "vol_spike_up": 0
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
        tech["rsi_rising"] = int(r.iloc[-1] > r.iloc[-3]) if len(r) >= 3 else 0
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

# ----------------------------
# Options metrics (defensive)
# ----------------------------
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

# ----------------------------
# Scoring helpers
# ----------------------------
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
    if score >= 82:
        return "STRONG BUY"
    if score >= 74:
        return "BUY"
    if score >= 66:
        return "WATCHLIST"
    return "NO TRADE"

# ----------------------------
# Buy-the-dip simple detector
# ----------------------------
def detect_buy_the_dip(hist):
    if hist.empty:
        return False, np.nan, np.nan
    try:
        look = hist["Close"].iloc[-20:]
        recent_high = float(look.max())
        last = float(look.iloc[-1])
        pullback = (recent_high - last) / recent_high if recent_high>0 else 0.0
        is_btd = (pullback >= 0.02) and (pullback <= 0.12)
        return bool(is_btd), float(round(pullback*100,3)), recent_high
    except:
        return False, np.nan, np.nan

# ----------------------------
# MTF confirmation
# ----------------------------
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

# ----------------------------
# Rule-based AI commentary (deterministic)
# ----------------------------
def ai_commentary(result):
    # result contains keys like final, price_score, flow_score, inst_flow, btd, mtf_details
    score = result.get("final_score", None)
    parts = []
    if score is None:
        return "No score available to generate commentary."
    # High-level sentiment
    if score >= 82:
        parts.append("Strong conviction — multiple indicators aligned.")
    elif score >= 74:
        parts.append("Positive bias — favorable technicals, verify multi-timeframe confirmation.")
    elif score >= 66:
        parts.append("Neutral-to-positive — worth watchlist monitoring; wait for confirmation.")
    else:
        parts.append("Not a trade currently — consider waiting for clearer setups.")

    # Explain price subscore
    ps = result.get("price_score", 0)
    if ps >= 60:
        parts.append("Price momentum is positive (EMA cross / higher lows / rising RSI).")
    else:
        parts.append("Price momentum is weak or neutral.")

    # Explain flow
    fs = result.get("flow_score", 0)
    if fs >= 50:
        parts.append("Options/volume flow supports direction (notable call activity or volume spikes).")
    else:
        parts.append("Flow signals are weak or neutral.")

    # MTF
    mtf = result.get("mtf_details", {})
    if isinstance(mtf, dict):
        pos = sum(1 for v in mtf.values() if isinstance(v, (int,float)) and v >= MTF_POSITIVE_PRICE_SCORE)
        parts.append(f"Multi-timeframe positive count: {pos} (threshold {MTF_CONFIRM_THRESHOLD}).")

    # BTD
    if result.get("btd", False):
        parts.append(f"Buy-the-dip detected (pullback {result.get('btd_pullback','N/A')}%). This can be a lower-risk entry if trend holds.")

    # Final actionable hint
    if score >= 74 and pos >= MTF_CONFIRM_THRESHOLD:
        parts.append("Action: Consider size/entries aligned with risk plan (confirm with volume & option flow).")
    elif score >= 74 and pos < MTF_CONFIRM_THRESHOLD:
        parts.append("Action: Wait for additional timeframe confirmation, or look for BTD entry.")
    else:
        parts.append("Action: Monitor; no immediate entry recommended.")

    return " ".join(parts)

# ----------------------------
# Top-level analyze (returns dict)
# ----------------------------
def analyze_ticker_full(ticker, include_options=True):
    out = {"ticker": ticker, "error": None}
    try:
        # daily history
        daily = safe_history(ticker, "1d", f"{HIST_DAYS}d")

        tech_daily = compute_technical_metrics(daily)
        opt = compute_options_metrics(ticker) if include_options else {"opt_expiry": None, "call_put_vol_ratio": np.nan, "call_put_oi_ratio": np.nan}
        price_score = score_price_momentum(tech_daily)
        flow_score = score_volume_flow(tech_daily, opt)
        inst_score = inst_flow_proxy(tech_daily, opt)

        # weighting: use simple weights + inst_flow
        p_w = SCORES_CONFIG["STOCK"]["price"]
        f_w = SCORES_CONFIG["STOCK"]["flow"]
        inst_w = INST_FLOW_WEIGHT
        final = price_score * p_w + flow_score * f_w + inst_score * inst_w

        # mtf
        mtf_count, mtf_confirm, mtf_details = compute_mtf_scores(ticker)

        # btd
        btd_flag, btd_pull, btd_high = detect_buy_the_dip(daily)

        out.update({
            "last_close": tech_daily.get("last_close"),
            "price_score": round(price_score,2),
            "flow_score": round(flow_score,2),
            "inst_score": round(inst_score,2),
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

# ----------------------------
# UI: layout & interactions
# ----------------------------
st.set_page_config(page_title="Advanced Readiness Scanner (All-in-one)", layout="wide")
st.title("📈 Advanced Readiness Scanner — Charts, MTF, AI Commentary & History")

# Sidebar controls
st.sidebar.header("Controls")
ticker_input = st.sidebar.text_area("Tickers (comma separated)", value="AAPL, NVDA, MSFT")
mode = st.sidebar.selectbox("Mode", ["Single/Manual", "Prebuilt Group"])
group_choice = st.sidebar.selectbox("Group (when using group mode)", ["DOW30","NAS100_SAMPLE","CRYPTO_SAMPLE","FOREX_SAMPLE"])
include_options = st.sidebar.checkbox("Include options metrics", True)
workers = st.sidebar.slider("Parallel workers", min_value=1, max_value=12, value=min(MAX_WORKERS,8))
run_btn = st.sidebar.button("Run Scan")

# groups
GROUPS = {
    "DOW30": ["AAPL","AMGN","AXP","BA","CAT","CRM","CSCO","CVX","DIS","DOW","GS","HD","HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","PG","TRV","UNH","V","VZ","WBA","WMT"],
    "NAS100_SAMPLE": ["AAPL","MSFT","NVDA","TSLA","AMZN","META","GOOGL","ADBE"],
    "CRYPTO_SAMPLE": ["BTC-USD","ETH-USD","SOL-USD","ADA-USD"],
    "FOREX_SAMPLE": ["EURUSD=X","GBPUSD=X","USDJPY=X","USDCAD=X"]
}

# Results storage in session
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []

if run_btn:
    st.session_state.scan_results = []
    if mode == "Single/Manual":
        tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]
    else:
        tickers = GROUPS.get(group_choice, [])
    if not tickers:
        st.warning("No tickers provided.")
    else:
        st.info(f"Starting scan for {len(tickers)} tickers...")
        progress = st.progress(0)
        results = []
        total = len(tickers)
        with ThreadPoolExecutor(max_workers=min(workers, total)) as ex:
            futures = {ex.submit(analyze_ticker_full, t, include_options): t for t in tickers}
            done = 0
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"ticker": t, "error": str(e)}
                results.append(r)
                done += 1
                progress.progress(done/total)
        st.session_state.scan_results = results
        # persist to sqlite
        for r in results:
            try:
                persist_scan(r.get("ticker"), r.get("final_score"), r.get("signal"), r.get("last_close"))
            except:
                pass
        st.success("Scan complete!")

# Show Results summary
st.header("Results Summary")
if not st.session_state.scan_results:
    st.info("No scan results available. Run a scan from the sidebar.")
else:
    df = pd.json_normalize(st.session_state.scan_results)
    # friendly column names
    if "ticker" in df.columns:
        df = df.rename(columns={"ticker":"Ticker"})
    display_cols = ["Ticker","final_score","signal","price_score","flow_score","inst_score","mtf_count","mtf_confirm","btd","btd_pullback"]
    existing = [c for c in display_cols if c in df.columns]
    st.dataframe(df[existing].sort_values("final_score", ascending=False).reset_index(drop=True), use_container_width=True)

    # mini top cards
    top3 = df.sort_values("final_score", ascending=False).head(3)
    cols = st.columns(3)
    for i, (_, row) in enumerate(top3.iterrows()):
        cols[i].metric(label=row.get("ticker") or row.get("Ticker"), value=row.get("final_score"), delta=row.get("signal"))

    # Distribution
    if "final_score" in df.columns:
        fig = px.histogram(df, x="final_score", nbins=20, title="Score distribution")
        st.plotly_chart(fig, use_container_width=True)

    # allow user to choose ticker for detail
    tickers_list = sorted([r.get("ticker") for r in st.session_state.scan_results])
    sel = st.selectbox("Open Detail for ticker", options=tickers_list)
    if st.button("Open Detail"):
        st.session_state.detail_ticker = sel

# Ticker Detail section
detail_ticker = st.session_state.get("detail_ticker", None)
st.header("Ticker Detail")
if detail_ticker is None:
    st.info("Open a ticker detail from the Results Summary or run a single ticker scan.")
else:
    st.subheader(f"Details — {detail_ticker}")
    # recompute live single
    single_res = analyze_ticker_full(detail_ticker, include_options=include_options)
    if single_res.get("error"):
        st.error("Error computing details: " + str(single_res.get("error")))
    else:
        # top metrics
        c1, c2, c3 = st.columns([2,1,1])
        c1.metric("Ticker", detail_ticker)
        c2.metric("Score", single_res.get("final_score"))
        c3.metric("Signal", single_res.get("signal"))

        # AI commentary
        commentary = ai_commentary({
            "final_score": single_res.get("final_score"),
            "price_score": single_res.get("price_score"),
            "flow_score": single_res.get("flow_score"),
            "inst_score": single_res.get("inst_score"),
            "mtf_details": single_res.get("mtf_details"),
            "btd": single_res.get("btd"),
            "btd_pullback": single_res.get("btd_pullback")
        })
        st.markdown("**AI-style commentary (rule-based)**")
        st.info(commentary)

        # charts: daily candlestick + RSI + OBV
        try:
            histd = safe_history(detail_ticker, "1d", f"{HIST_DAYS}d")
            if not histd.empty:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=histd.index, open=histd["Open"], high=histd["High"], low=histd["Low"], close=histd["Close"], name="Price"))
                fig.update_layout(title=f"{detail_ticker} — Daily", height=450, margin=dict(t=25))
                st.plotly_chart(fig, use_container_width=True)

                # RSI
                r = rsi(histd["Close"])
                fig2 = px.line(x=r.index, y=r.values, labels={"x":"Date","y":"RSI"}, title="RSI")
                fig2.add_hline(y=70, line_dash="dash", line_color="red")
                fig2.add_hline(y=30, line_dash="dash", line_color="green")
                fig2.update_layout(height=250)
                st.plotly_chart(fig2, use_container_width=True)

                # OBV + volume
                obv_series = obv(histd["Close"], histd["Volume"] if "Volume" in histd.columns else pd.Series([0]*len(histd), index=histd.index))
                vol_fig = go.Figure()
                vol_fig.add_trace(go.Bar(x=histd.index, y=histd["Volume"], name="Volume"))
                vol_fig.add_trace(go.Scatter(x=obv_series.index, y=obv_series, name="OBV", yaxis="y2"))
                vol_fig.update_layout(title="Volume & OBV", height=300, yaxis=dict(title="Volume"), yaxis2=dict(title="OBV", overlaying="y", side="right"))
                st.plotly_chart(vol_fig, use_container_width=True)
            else:
                st.info("No daily history available for charts.")
        except Exception as e:
            st.info("Could not render charts: " + str(e))

        # MTF breakdown
        st.subheader("Multi-timeframe breakdown")
        positives, confirmed, mtf_details = compute_mtf_scores(detail_ticker)
        st.write("Positive count:", positives, "Confirmed across MTF:", confirmed)
        st.write("MTF details:", mtf_details)

        # Options snapshot
        st.subheader("Options snapshot (nearest expiry)")
        st.json({"expiry": single_res.get("opt_expiry"), "call_put_vol_ratio": single_res.get("opt_call_put_vol_ratio"), "call_put_oi_ratio": single_res.get("opt_call_put_oi_ratio")})

        # Trend gauge (based on recent history in DB)
        st.subheader("Trend gauge (based on persisted history)")
        hist_df = read_history(detail_ticker, limit=200)
        if not hist_df.empty:
            hist_df["score"] = pd.to_numeric(hist_df["score"], errors="coerce")
            recent = hist_df.head(30).sort_values("ts")
            fig_hist = px.line(recent, x="ts", y="score", title=f"Recent scores for {detail_ticker}")
            st.plotly_chart(fig_hist, use_container_width=True)
            avg_score = recent["score"].mean()
            st.metric("Average recent score", round(avg_score,2))
            # simple gauge substitute (plotly doesn't have a native gauge in free version reliably)
            gauge = go.Figure(go.Indicator(mode="gauge+number", value=single_res.get("final_score",0), gauge={'axis':{'range':[0,100]}}))
            gauge.update_layout(height=250)
            st.plotly_chart(gauge, use_container_width=True)
        else:
            st.info("No persisted history for this ticker yet.")

# History page: overall persisted scans
st.header("Global Scan History (persisted)")
hist_all = read_history(limit=500)
if hist_all.empty:
    st.info("No persisted history. Run some scans to populate.")
else:
    # latest per ticker
    latest = hist_all.groupby("ticker").first().reset_index()
    st.dataframe(latest.sort_values("score", ascending=False).reset_index(drop=True).head(100), use_container_width=True)
    # top average
    avg = hist_all.groupby("ticker")["score"].mean().reset_index().rename(columns={"score":"avg_score"}).sort_values("avg_score", ascending=False).head(20)
    fig_avg = px.bar(avg, x="ticker", y="avg_score", title="Top tickers by average score (persisted history)")
    st.plotly_chart(fig_avg, use_container_width=True)

# Export last session results
st.header("Export / Download")
if st.session_state.get("scan_results"):
    export_df = pd.json_normalize(st.session_state["scan_results"])
    st.download_button("Download latest results CSV", data=export_df.to_csv(index=False).encode("utf-8"), file_name="latest_scan.csv", mime="text/csv")
else:
    st.info("No session results to export.")

st.sidebar.markdown("---")
st.sidebar.write("Built: single-file app — charts, MTF, commentary, SQLite history")
