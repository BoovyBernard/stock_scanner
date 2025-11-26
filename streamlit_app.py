############################################################
# streamlit_app.py  (COMPLETE — READY TO DEPLOY)
############################################################
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import traceback
import threading
import time
import math
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

############################################################
# ------------------- CONFIGURATION ------------------------
############################################################

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

SCORES_CONFIG = {
    "STOCK": {"price": 0.45, "flow": 0.35, "fund": 0.20},
    "ETF": {"price": 0.50, "flow": 0.40, "fund": 0.10},
    "CRYPTO": {"price": 0.65, "flow": 0.35, "fund": 0.00},
    "FOREX": {"price": 0.70, "flow": 0.30, "fund": 0.00},
    "COMMODITY": {"price": 0.55, "flow": 0.45, "fund": 0.00},
    "INDEX": {"price": 0.60, "flow": 0.40, "fund": 0.00},
    "UNKNOWN": {"price": 0.50, "flow": 0.50, "fund": 0.00},
}



############################################################
# ------------------- SAFE HELPERS -------------------------
############################################################

def safe_ticker(ticker):
    try:
        return yf.Ticker(ticker)
    except:
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
    except:
        return pd.DataFrame()

def ema(series, period):
    try:
        return series.ewm(span=period, adjust=False).mean()
    except:
        return pd.Series([np.nan]*len(series), index=series.index)

def rsi(series, period=14):
    try:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))
    except:
        return pd.Series([np.nan]*len(series), index=series.index)

def compute_obv_safe(df):
    if df.empty:
        return pd.Series([], dtype=float)
    close = df["Close"]
    vol = df["Volume"] if "Volume" in df.columns else pd.Series([0]*len(df), index=df.index)
    obv = [0]
    for i in range(1, len(close)):
        try:
            if close.iloc[i] > close.iloc[i-1]:
                obv.append(obv[-1] + vol.iloc[i])
            elif close.iloc[i] < close.iloc[i-1]:
                obv.append(obv[-1] - vol.iloc[i])
            else:
                obv.append(obv[-1])
        except:
            obv.append(obv[-1])
    return pd.Series(obv, index=df.index)

def safe_div(a, b):
    try:
        if b == 0 or pd.isna(b):
            return np.nan
        return a / b
    except:
        return np.nan



############################################################
# --------------- TECHNICAL METRICS ------------------------
############################################################

def compute_technical_metrics(hist):
    out = {
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
        return out

    close = hist["Close"]

    try:
        out["last_close"] = float(close.iloc[-1])
    except:
        pass

    try:
        out["ema_fast"] = float(ema(close, EMA_FAST).iloc[-1])
        out["ema_slow"] = float(ema(close, EMA_SLOW).iloc[-1])
        out["ema_cross"] = int(out["ema_fast"] > out["ema_slow"])
        out["price_above_ema_slow"] = int(close.iloc[-1] > out["ema_slow"])
    except:
        pass

    try:
        r = rsi(close, RSI_PERIOD)
        out["rsi"] = float(r.iloc[-1])
        out["rsi_rising"] = int(r.iloc[-1] > r.iloc[-3]) if len(r) >= 3 else 0
    except:
        pass

    try:
        lows = hist["Low"].dropna()
        if len(lows) >= 3:
            out["higher_lows_3"] = int(lows.iloc[-1] > lows.iloc[-2] > lows.iloc[-3])
    except:
        pass

    try:
        obv = compute_obv_safe(hist)
        if len(obv) >= OBV_LOOKBACK:
            y = obv.iloc[-OBV_LOOKBACK:].values
            x = np.arange(len(y))
            m = np.polyfit(x, y, 1)[0]
            out["obv_slope"] = float(m)
            out["obv_slope_pos"] = int(m > 0)
    except:
        pass

    try:
        vol = hist["Volume"]
        out["today_vol"] = float(vol.iloc[-1])
        out["avg_vol_30"] = float(vol.rolling(30).mean().iloc[-1])
        out["vol_spike_up"] = int(
            out["today_vol"] > VOLUME_SPIKE_MULT * out["avg_vol_30"]
            and close.iloc[-1] > close.iloc[-2]
        )
    except:
        pass

    return out



############################################################
# ---------------- OPTIONS METRICS -------------------------
############################################################

def compute_options_metrics(ticker):
    out = {
        "opt_expiry": None,
        "call_put_vol_ratio": np.nan,
        "call_put_oi_ratio": np.nan,
    }

    try:
        t = safe_ticker(ticker)
        if t is None:
            return out

        exps = t.options
        if not exps:
            return out

        expiry = exps[0]
        chain = t.option_chain(expiry)

        calls = chain.calls
        puts = chain.puts

        call_vol = calls["volume"].fillna(0).sum()
        put_vol = puts["volume"].fillna(0).sum()

        call_oi = calls["openInterest"].fillna(0).sum()
        put_oi = puts["openInterest"].fillna(0).sum()

        out["opt_expiry"] = expiry
        out["call_put_vol_ratio"] = safe_div(call_vol, put_vol)
        out["call_put_oi_ratio"] = safe_div(call_oi, put_oi)

        return out
    except:
        return out



############################################################
# ---------------- SCORING FUNCTIONS -----------------------
############################################################

def score_price_momentum(tech):
    score = 0
    try:
        score += tech["ema_cross"] * 25
        score += tech["price_above_ema_slow"] * 25
        score += tech["rsi_rising"] * 15
        score += tech["higher_lows_3"] * 15
        score += tech["obv_slope_pos"] * 20
    except:
        pass

    return float(score)


def score_volume_flow(tech, opt, asset_class):
    score = 0
    try:
        if tech["vol_spike_up"]:
            score += 40
        if opt["call_put_vol_ratio"] and opt["call_put_vol_ratio"] > 1.2:
            score += 30
        if opt["call_put_oi_ratio"] and opt["call_put_oi_ratio"] > 1.2:
            score += 30
    except:
        pass

    return float(score)


def institutional_flow_proxy(tech, opt):
    score = 50
    try:
        if tech["obv_slope_pos"]:
            score += 15
        if tech["vol_spike_up"]:
            score += 10
        if opt["call_put_oi_ratio"] and opt["call_put_oi_ratio"] > 1.1:
            score += 15
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



############################################################
# ------------------ BUY THE DIP LOGIC ---------------------
############################################################

def detect_buy_the_dip(hist):
    if hist.empty or "Close" not in hist.columns:
        return False, np.nan, np.nan

    try:
        recent_high = hist["Close"].rolling(20).max().iloc[-1]
        pull = (recent_high - hist["Close"].iloc[-1]) / recent_high * 100
        return pull >= 5, pull, recent_high
    except:
        return False, np.nan, np.nan



############################################################
# ---------------- ANALYZE TICKER (MAIN) -------------------
############################################################

def analyze_ticker(ticker):
    result = {
        "ticker": ticker,
        "error": None,
    }

    try:
        # load data
        hist = safe_history(ticker, "1d", f"{HIST_DAYS}d")
        tech = compute_technical_metrics(hist)
        opt = compute_options_metrics(ticker)

        # compute subscores
        price = score_price_momentum(tech)
        flow = score_volume_flow(tech, opt, "STOCK")
        inst = institutional_flow_proxy(tech, opt)

        final = (
            price * SCORES_CONFIG["STOCK"]["price"] +
            flow * SCORES_CONFIG["STOCK"]["flow"] +
            inst  * INST_FLOW_WEIGHT
        )

        # buy the dip
        btd_flag, pull, rhigh = detect_buy_the_dip(hist)

        # fill result
        result.update({
            "last_close": tech["last_close"],
            "price_score": price,
            "flow_score": flow,
            "inst_flow": inst,
            "final_score": round(final, 2),
            "signal": get_buy_signal(final),
            "btd": btd_flag,
            "btd_pullback": pull,
            "btd_recent_high": rhigh,
            "call_put_vol_ratio": opt["call_put_vol_ratio"],
            "call_put_oi_ratio": opt["call_put_oi_ratio"],
            "opt_expiry": opt["opt_expiry"],
        })

    except Exception as e:
        result["error"] = str(e)

    return result



############################################################
# ------------------- STREAMLIT UI -------------------------
############################################################

st.set_page_config(page_title="Advanced Readiness Scanner", layout="wide")

st.title("📊 Advanced Market Readiness Scanner (Stable Build)")
st.caption("Fully Defensive • Multi-Ticker • Accurate Scoring • Ready to Deploy")


ticker_input = st.text_area(
    "Enter tickers (comma separated):",
    value="AAPL, NVDA, MSFT, TSLA, SPY"
)

tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]

run_button = st.button("🚀 Run Scan")



############################################################
# ------------------- RUN SCANNING -------------------------
############################################################

if run_button:

    st.warning("Scanning... Please wait ⏳")

    results = []
    progress = st.progress(0)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(analyze_ticker, t): t for t in tickers}
        total = len(futures)
        done = 0

        for fut in as_completed(futures):
            try:
                res = fut.result()
                results.append(res)
            except:
                results.append({"ticker": futures[fut], "error": "Unhandled exception"})
            done += 1
            progress.progress(done / total)

    df = pd.DataFrame(results)

    st.success("Completed!")

    st.dataframe(df, use_container_width=True)

    st.subheader("Export")
    st.download_button(
        "Download CSV",
        data=df.to_csv(index=False),
        file_name="scanner_output.csv"
    )

