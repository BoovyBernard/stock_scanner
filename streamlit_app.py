# streamlit_app.py
"""
Streamlit dashboard (single-file) wrapping your
advanced_readiness_scanner_mtf_btd logic into a
multi-page app (Home / Results / Detail / History).
"""

import streamlit as st
import pandas as pd
import numpy as np
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import plotly.express as px
import plotly.graph_objects as go

# --- Core libs used by the scanner (yfinance + fetchers) ---
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

# -----------------------------
# Paste your original scanner configuration & functions here
# (I kept function names & behavior consistent with your script)
# -----------------------------

# -----------------------------
# CONFIG (same as original)
# -----------------------------
HIST_DAYS = 180
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
OBV_LOOKBACK = 14
VOLUME_SPIKE_MULT = 1.5

INST_FLOW_WEIGHT = 0.10

MTF_TIMEFRAMES = ["1d", "4h", "1h"]
MTF_CONFIRM_THRESHOLD = 2
MTF_POSITIVE_PRICE_SCORE = 60.0

BTD_LOOKBACK_DAYS = 20
BTD_MIN_PULLBACK = 0.02
BTD_MAX_PULLBACK = 0.08
BTD_REQUIRE_DAILY_UPTREND = True

HISTORY_CSV = "readiness_history.csv"

TOP_LEVEL_TICKERS = []  # will be accessible by UI (user can load groups)

SCORES_CONFIG = {
    "EQUITY": {"price": 0.40, "flow": 0.35, "fund": 0.25},
    "ETF": {"price": 0.45, "flow": 0.45, "fund": 0.10},
    "INDEX": {"price": 0.70, "flow": 0.00, "fund": 0.30},
    "COMMODITY": {"price": 0.80, "flow": 0.20, "fund": 0.00},
    "CRYPTOCURRENCY": {"price": 0.75, "flow": 0.25, "fund": 0.00},
    "CURRENCY": {"price": 0.80, "flow": 0.20, "fund": 0.00},
    "UNKNOWN": {"price": 0.40, "flow": 0.35, "fund": 0.25}
}

# -----------------------------
# Helpers
# -----------------------------
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(period, min_periods=period).mean()
    ma_down = down.rolling(period, min_periods=period).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def compute_obv(df):
    obv = [0]
    for i in range(1, len(df)):
        if df['Close'].iat[i] > df['Close'].iat[i-1]:
            obv.append(obv[-1] + int(df['Volume'].iat[i]) if 'Volume' in df.columns else obv[-1])
        elif df['Close'].iat[i] < df['Close'].iat[i-1]:
            obv.append(obv[-1] - int(df['Volume'].iat[i]) if 'Volume' in df.columns else obv[-1])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=df.index)

def safe_div(a,b,default=np.nan):
    try:
        return a/b if b else default
    except Exception:
        return default

# -----------------------------
# Asset class & sector detection
# -----------------------------
def detect_asset_class(ticker):
    if isinstance(ticker, str):
        if ticker.endswith("=X"):
            return "CURRENCY"
        if ticker.endswith("=F") or ticker.endswith("=f"):
            return "COMMODITY"
        if ticker.endswith("-USD"):
            return "CRYPTOCURRENCY"
        if ticker.startswith("^"):
            return "INDEX"
    try:
        info = yf.Ticker(ticker).info or {}
        q = (info.get('quoteType') or "").upper()
        if q in ["EQUITY", "STOCK"]:
            return "EQUITY"
        if q == "ETF":
            return "ETF"
        if q == "INDEX":
            return "INDEX"
        if q in ["CURRENCY", "CURRENCYPAIR"]:
            return "CURRENCY"
        if q in ["CRYPTOCURRENCY", "CRYPTO"]:
            return "CRYPTOCURRENCY"
        if q in ["FUTURE", "COMMODITY"]:
            return "COMMODITY"
        if info.get("isEtf"):
            return "ETF"
    except Exception:
        pass
    return "UNKNOWN"

def detect_sector(ticker, asset_class):
    if asset_class == "INDEX":
        return "Index"
    if asset_class == "COMMODITY":
        return "Commodities"
    if asset_class == "CRYPTOCURRENCY":
        return "Digital Assets"
    if asset_class == "CURRENCY":
        return "Forex"
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    sector = info.get("sector") or info.get("industry") or info.get("category")
    if sector and isinstance(sector, str) and sector.strip():
        return sector.strip()
    summary = (info.get("longBusinessSummary") or info.get("shortName") or "").lower()
    keyword_map = {
        "Technology": ["technology", "software", "semi", "chip", "cloud", "ai"],
        "Financials": ["bank", "financ", "insur", "asset"],
        "Energy": ["oil", "gas", "energy", "pipeline"],
        "Healthcare": ["health", "biotech", "pharm", "medical"],
        "Consumer Discretionary": ["retail", "automotive", "hotel", "leisure"],
        "Consumer Staples": ["food", "beverage", "grocery"],
        "Industrials": ["industrial", "machinery", "aerospace", "logistic"],
        "Utilities": ["utility", "electric", "water"],
        "Real Estate": ["real estate", "reit"],
        "Materials": ["metal", "mining", "chemical"],
        "Communication Services": ["telecom", "communication", "media"]
    }
    for name, terms in keyword_map.items():
        if any(t in summary for t in terms):
            return name
    return "Unknown"

# -----------------------------
# Data retrieval
# -----------------------------
@st.cache_data(ttl=60*60)  # cache per ticker/timeframe for 1 hour
def get_history(ticker, timeframe='1d', days=HIST_DAYS):
    t = yf.Ticker(ticker)
    if timeframe == '1d':
        interval = '1d'
        period = f"{days}d"
    elif timeframe == '4h':
        interval = '4h'
        period = "120d"
    elif timeframe == '1h':
        interval = '1h'
        period = "60d"
    else:
        interval = timeframe
        period = f"{days}d"
    hist = t.history(period=period, interval=interval, actions=False)
    if (hist is None or hist.empty) and interval == '4h':
        hist = t.history(period=period, interval='60m', actions=False)
        if hist is not None and not hist.empty:
            hist = hist.resample('4H').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    if hist is None or hist.empty:
        hist = t.history(period="30d", interval=interval, actions=False)
    if hist is None or hist.empty:
        raise ValueError(f"No history for {ticker} {timeframe}")
    return hist.dropna(subset=['Close'])

# -----------------------------
# Technical & options metrics per timeframe
# -----------------------------
def compute_technical_metrics_from_hist(hist):
    close = hist['Close']
    low = hist['Low'] if 'Low' in hist.columns else close
    vol = hist['Volume'] if 'Volume' in hist.columns else pd.Series([0]*len(hist), index=hist.index)

    tech = {}
    tech['last_close'] = float(close.iloc[-1])
    tech['ema_fast'] = float(ema(close, EMA_FAST).iloc[-1])
    tech['ema_slow'] = float(ema(close, EMA_SLOW).iloc[-1])
    tech['ema_cross'] = int(tech['ema_fast'] > tech['ema_slow'])
    tech['price_above_ema_slow'] = int(close.iloc[-1] > tech['ema_slow'])

    r = rsi(close, RSI_PERIOD)
    tech['rsi'] = float(r.iloc[-1]) if not r.isna().all() else np.nan
    tech['rsi_rising'] = int(r.iloc[-1] > r.iloc[-3]) if len(r) >= 3 else 0

    try:
        lows = low.dropna().iloc[-5:]
        tech['higher_lows_3'] = int(len(lows) >= 3 and lows.iloc[-1] > lows.iloc[-2] > lows.iloc[-3])
    except Exception:
        tech['higher_lows_3'] = 0

    obv = compute_obv(hist)
    tech['obv_latest'] = float(obv.iloc[-1])
    if len(obv) >= OBV_LOOKBACK:
        y = obv.iloc[-OBV_LOOKBACK:].values
        x = np.arange(len(y))
        if np.all(np.isfinite(y)):
            m = np.polyfit(x, y, 1)[0]
            tech['obv_slope'] = float(m)
            tech['obv_slope_pos'] = int(m > 0)
        else:
            tech['obv_slope'] = 0.0
            tech['obv_slope_pos'] = 0
    else:
        tech['obv_slope'] = 0.0
        tech['obv_slope_pos'] = 0

    avg30 = vol.rolling(30, min_periods=5).mean().iloc[-1] if len(vol) >= 5 else (vol.mean() if len(vol)>0 else 0)
    tech['avg_vol_30'] = float(avg30 if not np.isnan(avg30) else 0.0)
    tech['today_vol'] = float(vol.iloc[-1]) if len(vol)>0 else 0.0
    today_up = int(close.iloc[-1] > close.iloc[-2]) if len(close) >= 2 else 0
    tech['vol_spike_up'] = int((tech['today_vol'] > VOLUME_SPIKE_MULT * tech['avg_vol_30']) and today_up)

    return tech

def compute_options_metrics(ticker):
    t = yf.Ticker(ticker)
    res = {
        'opt_nearest_expiry': None,
        'call_vol_sum': np.nan,
        'put_vol_sum': np.nan,
        'call_oi_sum': np.nan,
        'put_oi_sum': np.nan,
        'call_put_vol_ratio': np.nan,
        'call_put_oi_ratio': np.nan
    }
    try:
        exps = t.options
        if not exps:
            return res
        ne = exps[0]
        chain = t.option_chain(ne)
        calls = chain.calls
        puts = chain.puts
        cv = int(calls['volume'].dropna().sum()) if not calls.empty else 0
        pv = int(puts['volume'].dropna().sum()) if not puts.empty else 0
        coi = int(calls['openInterest'].dropna().sum()) if not calls.empty else 0
        poi = int(puts['openInterest'].dropna().sum()) if not puts.empty else 0
        res.update({
            'opt_nearest_expiry': ne,
            'call_vol_sum': cv,
            'put_vol_sum': pv,
            'call_oi_sum': coi,
            'put_oi_sum': poi,
            'call_put_vol_ratio': safe_div(cv,pv),
            'call_put_oi_ratio': safe_div(coi,poi)
        })
    except Exception:
        pass
    return res

# -----------------------------
# Scoring functions (kept same)
# -----------------------------
def score_price_momentum_from_tech(tech):
    w_ema = 0.35
    w_price = 0.25
    w_rsi = 0.20
    w_hl = 0.20
    score = 0.0
    score += w_ema * (1.0 if tech.get('ema_cross',0)==1 else 0.0)
    score += w_price * (1.0 if tech.get('price_above_ema_slow',0)==1 else 0.0)
    r = tech.get('rsi', np.nan)
    if np.isfinite(r):
        if r < 30: r_score = 0.0
        elif r > 80: r_score = 0.2
        else: r_score = max(0.0, 1.0 - abs(r-60)/30.0)
        if tech.get('rsi_rising',0): r_score = min(1.0, r_score*1.2)
    else:
        r_score = 0.5
    score += w_rsi * r_score
    score += w_hl * (1.0 if tech.get('higher_lows_3',0)==1 else 0.0)
    return float(score*100.0)

def score_volume_flow_from_tech_opt(tech, opt, asset_class):
    w_vol_spike = 0.30
    w_obv = 0.30
    w_cp_vol = 0.20
    w_cp_oi = 0.20
    s = 0.0
    s += w_vol_spike * (1.0 if tech.get('vol_spike_up',0)==1 else 0.0)
    s += w_obv * (1.0 if tech.get('obv_slope_pos',0)==1 else 0.0)
    cpv = opt.get('call_put_vol_ratio', np.nan)
    cpoi = opt.get('call_put_oi_ratio', np.nan)
    if asset_class in ["INDEX","CURRENCY","COMMODITY","CRYPTOCURRENCY"]:
        s += w_cp_vol * 0.5
        s += w_cp_oi * 0.5
    else:
        if np.isfinite(cpv):
            mapped = max(0.0, min(1.0, cpv/2.0))
            s += w_cp_vol * mapped
        else:
            s += w_cp_vol * 0.5
        if np.isfinite(cpoi):
            mapped = max(0.0, min(1.0, cpoi/2.0))
            s += w_cp_oi * mapped
        else:
            s += w_cp_oi * 0.5
    total = w_vol_spike + w_obv + w_cp_vol + w_cp_oi
    return float(s/total*100.0)

def score_fundamentals(ticker):
    t = yf.Ticker(ticker)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}
    earnings_score = 0.5
    try:
        qearn = t.quarterly_earnings
        if qearn is not None and 'Earnings' in qearn.columns:
            vals = qearn['Earnings'].dropna()
            if len(vals) >= 2:
                last, prev = vals.iloc[-1], vals.iloc[-2]
                if prev != 0:
                    g = (last - prev)/abs(prev)
                    earnings_score = max(0.0, min(1.0, (g+1)/2.0))
    except Exception:
        pass
    short_ratio = info.get('shortRatio', np.nan)
    short_score = 0.5
    if np.isfinite(short_ratio):
        short_score = max(0.0, min(1.0, 1.0 - (short_ratio - 0.05)/0.25))
    rec = info.get('recommendationMean', np.nan)
    rec_score = 0.5
    if np.isfinite(rec):
        rec_score = max(0.0, min(1.0, (5.0 - rec)/4.0))
    raw = 0.5*earnings_score + 0.3*rec_score + 0.2*short_score
    return float(max(0.0, min(1.0, raw))*100.0)

def institutional_flow_proxy(tech, opt):
    cpv = opt.get('call_put_vol_ratio', np.nan)
    cpv_score = max(0.0, min(1.0, cpv/2.0)) if np.isfinite(cpv) else 0.5
    avg30 = tech.get('avg_vol_30', 0.0)
    today = tech.get('today_vol', 0.0)
    if avg30 and avg30 > 0:
        mult = today/avg30
        vol_score = max(0.0, min(1.0, (mult-1.0)/2.0 + 0.5))
    else:
        vol_score = 0.5
    obv_pos = 1.0 if tech.get('obv_slope_pos', 0) == 1 else 0.0
    w_opts, w_vol, w_obv = 0.4, 0.4, 0.2
    raw = w_opts*cpv_score + w_vol*vol_score + w_obv*obv_pos
    return float(raw*100.0)

def get_buy_signal_from_score(score):
    if score >= 80:
        return "STRONG BUY"
    elif score >= 75:
        return "BUY"
    elif score >= 65:
        return "WATCHLIST"
    else:
        return "NO TRADE"

def append_history_row(ticker, score, signal, history_file=HISTORY_CSV):
    try:
        row = pd.DataFrame([{
            "Datetime": datetime.utcnow().isoformat(),
            "Ticker": ticker,
            "Score": score,
            "Signal": signal
        }])
        header = not (os.path.exists(history_file))
        row.to_csv(history_file, mode='a', header=header, index=False)
    except Exception:
        pass

def get_score_trend(ticker, history_file=HISTORY_CSV, lookback=3):
    if not os.path.exists(history_file):
        return "N/A"
    try:
        df = pd.read_csv(history_file)
        df_t = df[df["Ticker"]==ticker].tail(lookback)
        if len(df_t) < 2:
            return "N/A"
        prev_mean = df_t["Score"].iloc[:-1].mean() if len(df_t) > 1 else df_t["Score"].iloc[0]
        last = df_t["Score"].iloc[-1]
        if last > prev_mean:
            return "RISING"
        elif last < prev_mean:
            return "FALLING"
        else:
            return "FLAT"
    except Exception:
        return "N/A"

def compute_mtf_confirmation(ticker):
    positives = 0
    details = {}
    for tf in MTF_TIMEFRAMES:
        try:
            hist = get_history(ticker, timeframe=tf)
            tech = compute_technical_metrics_from_hist(hist)
            price_score = score_price_momentum_from_tech(tech)
            details[tf] = price_score
            if price_score >= MTF_POSITIVE_PRICE_SCORE:
                positives += 1
        except Exception:
            details[tf] = np.nan
    confirmed = positives >= MTF_CONFIRM_THRESHOLD
    return positives, confirmed, details

def detect_buy_the_dip(ticker):
    try:
        hist = get_history(ticker, timeframe='1d')
    except Exception:
        return False, np.nan, np.nan
    tech = compute_technical_metrics_from_hist(hist)
    last_close = tech.get('last_close')
    if BTD_REQUIRE_DAILY_UPTREND:
        if not (tech.get('ema_cross',0) == 1 and tech.get('price_above_ema_slow',0) == 1):
            return False, None, None
    look = hist['Close'].iloc[-BTD_LOOKBACK_DAYS:] if len(hist) >= BTD_LOOKBACK_DAYS else hist['Close']
    recent_high = float(look.max())
    pullback = (recent_high - last_close) / recent_high if recent_high>0 else 0.0
    is_btd = (pullback >= BTD_MIN_PULLBACK) and (pullback <= BTD_MAX_PULLBACK)
    return bool(is_btd), round(pullback, 4), recent_high

def analyze_ticker(ticker):
    rec = {'ticker': ticker}
    try:
        asset_class = detect_asset_class(ticker)
        rec['asset_class'] = asset_class
        rec['sector'] = detect_sector(ticker, asset_class)

        hist_daily = get_history(ticker, timeframe='1d')
        tech_daily = compute_technical_metrics_from_hist(hist_daily)
        opt = compute_options_metrics(ticker)

        price_sub = score_price_momentum_from_tech(tech_daily)
        flow_sub = score_volume_flow_from_tech_opt(tech_daily, opt, asset_class)
        fund_sub = np.nan
        if SCORES_CONFIG.get(asset_class, SCORES_CONFIG['UNKNOWN'])['fund'] > 0:
            try:
                fund_sub = score_fundamentals(ticker)
            except Exception:
                fund_sub = np.nan

        inst_proxy = institutional_flow_proxy(tech_daily, opt) if INST_FLOW_WEIGHT > 0 else np.nan

        base_cfg = SCORES_CONFIG.get(asset_class, SCORES_CONFIG['UNKNOWN'])
        base_price = base_cfg['price']
        base_flow = base_cfg['flow']
        base_fund = base_cfg['fund']
        base_total = base_price + base_flow + base_fund
        inst_w = INST_FLOW_WEIGHT
        remaining = max(0.0, 1.0 - inst_w)
        if base_total > 0:
            p_w = (base_price / base_total) * remaining
            f_w = (base_flow / base_total) * remaining
            fund_w = (base_fund / base_total) * remaining
        else:
            p_w = remaining*0.6; f_w = remaining*0.4; fund_w = 0.0

        fund_val = fund_sub if not (fund_sub is None or np.isnan(fund_sub)) else 50.0
        inst_val = inst_proxy if not (inst_proxy is None or np.isnan(inst_proxy)) else 50.0

        final_score = p_w*price_sub + f_w*flow_sub + fund_w*fund_val + inst_w*inst_val

        mtf_count, mtf_confirm, mtf_details = compute_mtf_confirmation(ticker)
        btd_flag, btd_pullback, btd_recent_high = detect_buy_the_dip(ticker)

        buy_signal = get_buy_signal_from_score(final_score)
        if buy_signal in ("STRONG BUY","BUY"):
            if not mtf_confirm:
                if buy_signal == "STRONG BUY":
                    if not mtf_confirm:
                        if btd_flag and final_score >= 70:
                            buy_signal = "BUY (BTD)"
                        else:
                            buy_signal = "WATCHLIST"
                else:
                    if btd_flag and final_score >= 70:
                        buy_signal = "BUY (BTD)"
                    else:
                        buy_signal = "WATCHLIST"
        else:
            if btd_flag and (final_score >= 70):
                buy_signal = "BUY (BTD)"
            elif btd_flag and (final_score >= 65):
                buy_signal = "WATCHLIST (BTD)"

        score_trend = get_score_trend(ticker)
        append_history_row(ticker, final_score, buy_signal)

        rec.update({
            'price_subscore': round(price_sub,2),
            'flow_subscore': round(flow_sub,2),
            'fund_subscore': round(float(fund_val),2),
            'inst_flow_proxy': round(float(inst_val),2),
            'final_readiness_score': round(float(final_score),2),
            'buy_signal': buy_signal,
            'signal_strength': "High" if final_score>=80 else ("Medium" if final_score>=75 else ("Low" if final_score>=65 else "None")),
            'score_trend': score_trend,
            'mtf_positive_count': int(mtf_count),
            'mtf_confirm': bool(mtf_confirm),
            'mtf_details': mtf_details,
            'buy_the_dip': bool(btd_flag),
            'btd_pullback_pct': btd_pullback,
            'btd_recent_high': btd_recent_high,
            'last_close': tech_daily.get('last_close'),
            'avg_vol_30': tech_daily.get('avg_vol_30'),
            'opt_nearest_expiry': opt.get('opt_nearest_expiry'),
            'call_put_vol_ratio': opt.get('call_put_vol_ratio'),
            'call_put_oi_ratio': opt.get('call_put_oi_ratio'),
        })
    except Exception as e:
        rec['error'] = str(e)
    return rec

# -----------------------------
# Fetchers for groups
# -----------------------------
def fetch_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        r = requests.get(url, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table", {"id": "constituents"})
        df = pd.read_html(str(table))[0]
        tickers = [t.replace('.', '-') for t in df['Symbol'].tolist()]
        return tickers
    except Exception:
        return ["AAPL","MSFT","AMZN","GOOGL","META"]

def fetch_dow30_tickers():
    return ["AAPL","AMGN","AXP","BA","CAT","CRM","CSCO","CVX","DIS","DOW","GS","HD","HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","PG","TRV","UNH","V","VZ","WBA","WMT"]

def fetch_nasdaq100_tickers():
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    try:
        r = requests.get(url, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table", {"class": "wikitable sortable"})
        df = pd.read_html(str(table))[0]
        tickers = [t.replace('.', '-') for t in df['Ticker'].tolist()]
        return tickers
    except Exception:
        return ["AAPL","MSFT","NVDA","TSLA","AMZN","META","GOOGL","PEP","AVGO","ADBE"]

# -----------------------------
# UI helpers & core run functions
# -----------------------------
def run_full_scan_single(ticker):
    """Wrapper returning a dict result for a ticker (uses analyze_ticker)"""
    return analyze_ticker(ticker)

def run_bulk_scan(tickers, max_workers=6, show_progress_callback=None):
    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(tickers) or 1)) as ex:
        futures = {ex.submit(run_full_scan_single, t): t for t in tickers}
        completed = 0
        total = len(tickers)
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                r = fut.result()
                results.append(r)
            except Exception as e:
                errors.append({"Ticker": t, "error": str(e)})
            completed += 1
            if show_progress_callback:
                show_progress_callback(completed, total)
    return results, errors

# -----------------------------
# Streamlit UI - app structure (multi-page)
# -----------------------------
st.set_page_config(page_title="Readiness Scanner Dashboard", layout="wide", initial_sidebar_state="expanded")

# Initialize session state containers
if "results" not in st.session_state:
    st.session_state.results = []   # list of dicts
if "last_scan_time" not in st.session_state:
    st.session_state.last_scan_time = None
if "history" not in st.session_state:
    st.session_state.history = []   # cached last N scans stored in session

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Home / Scanner", "Results Summary", "Ticker Detail", "History"])

# Sidebar: groups loader
st.sidebar.markdown("---")
st.sidebar.markdown("**Ticker Groups**")
if st.sidebar.button("Load S&P 500 (may be slow)"):
    try:
        sp = fetch_sp500_tickers()
        TOP_LEVEL_TICKERS.clear()
        TOP_LEVEL_TICKERS.extend(sp)
        st.sidebar.success(f"Loaded S&P500 ({len(sp)})")
    except Exception:
        st.sidebar.error("Failed to load S&P list.")
if st.sidebar.button("Load NAS100"):
    try:
        n100 = fetch_nasdaq100_tickers()
        TOP_LEVEL_TICKERS.clear()
        TOP_LEVEL_TICKERS.extend(n100)
        st.sidebar.success(f"Loaded NAS100 ({len(n100)})")
    except Exception:
        st.sidebar.error("Failed to load NAS100 list.")
if st.sidebar.button("Load DOW30"):
    TOP_LEVEL_TICKERS.clear()
    TOP_LEVEL_TICKERS.extend(fetch_dow30_tickers())
    st.sidebar.success("Loaded DOW30")

# Additional small groups
if st.sidebar.button("Load Crypto sample"):
    TOP_LEVEL_TICKERS.clear()
    TOP_LEVEL_TICKERS.extend(["BTC-USD","ETH-USD","SOL-USD","ADA-USD"])
    st.sidebar.success("Loaded Crypto sample")

if st.sidebar.button("Load Forex sample"):
    TOP_LEVEL_TICKERS.clear()
    TOP_LEVEL_TICKERS.extend(["EURUSD=X","GBPUSD=X","USDJPY=X","USDCAD=X"])
    st.sidebar.success("Loaded Forex sample")

st.sidebar.markdown("---")
st.sidebar.write("Bulk scan size: " + str(len(TOP_LEVEL_TICKERS)))

# MAIN PAGE: Home / Scanner
if page == "Home / Scanner":
    st.title("Readiness Scanner — Home")
    st.markdown(
        """
        Use this dashboard to scan tickers (single or bulk), view readiness scores,
        multi-timeframe confirmation, and buy-the-dip signals.
        """
    )
    st.markdown("### Quick scan")
    col1, col2, col3 = st.columns([2,1,1])
    with col1:
        input_ticker = st.text_input("Manual ticker (comma-separated for multiple):", value="AAPL")
    with col2:
        mode = st.selectbox("Mode", ["Single", "Bulk (TOP_LEVEL_TICKERS)"])
    with col3:
        max_workers = st.number_input("Workers (parallel)", min_value=1, max_value=12, value=4, step=1)

    st.markdown("### Options")
    c1, c2, c3 = st.columns(3)
    with c1:
        include_options = st.checkbox("Include options metrics (may be slower)", value=True)
    with c2:
        show_charts = st.checkbox("Show charts after scan", value=True)
    with c3:
        save_history_toggle = st.checkbox("Persist scan to history CSV", value=True)

    run_scan_btn = st.button("Run Scan")

    if run_scan_btn:
        try:
            st.info("Starting scan...")
            start = time.time()
            if mode == "Single":
                tickers = [t.strip().upper() for t in input_ticker.split(",") if t.strip()]
            else:
                tickers = list(dict.fromkeys([t.strip().upper() for t in TOP_LEVEL_TICKERS if t and isinstance(t, str)]))

            if not tickers:
                st.error("No tickers selected. Either enter a ticker or load a group.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()

                def progress_cb(done, total):
                    progress = int(done/total * 100)
                    progress_bar.progress(progress)
                    status_text.text(f"Completed {done}/{total}")

                results, errors = run_bulk_scan(tickers, max_workers=max_workers, show_progress_callback=progress_cb)
                st.session_state.results = results
                st.session_state.last_scan_time = datetime.utcnow().isoformat()
                # append to session history
                st.session_state.history.append({
                    "time": st.session_state.last_scan_time,
                    "count": len(results)
                })

                # persist each to CSV if requested
                if save_history_toggle:
                    for r in results:
                        try:
                            append_history_row(r.get('ticker') or r.get('Ticker') or 'TICK', r.get('final_readiness_score', np.nan), r.get('buy_signal','N/A'))
                        except Exception:
                            pass

                elapsed = time.time() - start
                st.success(f"Scan complete in {elapsed:.1f}s — {len(results)} results, {len(errors)} errors.")
                if errors:
                    st.warning(f"{len(errors)} tickers had errors. See 'History' page for details (or check logs).")
                # If asked, show charts for first result
                if show_charts and results:
                    sample = results[0]
                    st.markdown("### Sample result preview (first ticker)")
                    st.json(sample)
                    if 'ticker' in sample:
                        ticker0 = sample['ticker']
                        try:
                            histd = get_history(ticker0, timeframe='1d')
                            fig = go.Figure(data=[go.Candlestick(
                                x=histd.index, open=histd['Open'], high=histd['High'], low=histd['Low'], close=histd['Close']
                            )])
                            fig.update_layout(height=350, margin=dict(t=10,l=10,r=10,b=10))
                            st.plotly_chart(fig, use_container_width=True)
                        except Exception:
                            st.info("Could not draw chart for sample ticker.")
                # navigate to Results Summary page automatically (client-side)
                st.experimental_rerun()
        except Exception as e:
            st.error("Scan failed.")
            st.code(traceback.format_exc())

# RESULTS SUMMARY page
elif page == "Results Summary":
    st.title("Results Summary")
    if not st.session_state.results:
        st.info("No results in session. Run a scan from Home.")
    else:
        df = pd.json_normalize(st.session_state.results)
        # normalize column names
        if 'ticker' in df.columns:
            df = df.rename(columns={'ticker':'Ticker'})
        # reorder
        score_col = 'final_readiness_score' if 'final_readiness_score' in df.columns else None
        if score_col:
            df = df.sort_values(score_col, ascending=False)

        # Top cards
        st.markdown("### Top Signals")
        top_row = st.columns(3)
        top_df = df.head(3) if score_col else df.head(3)
        for i, (_, row) in enumerate(top_df.iterrows()):
            c = top_row[i]
            tck = row.get('Ticker', row.get('ticker', ''))
            sc = row.get(score_col, 'N/A') if score_col else 'N/A'
            sig = row.get('buy_signal', 'N/A')
            c.metric(label=f"{tck}", value=f"{sc}", delta=f"{sig}")

        st.markdown("---")
        # Interactive table
        st.write("### All scanned tickers (interactive)")
        # show main columns first
        show_cols = ['Ticker','asset_class','sector','final_readiness_score','buy_signal','mtf_positive_count','buy_the_dip']
        existing = [c for c in show_cols if c in df.columns]
        other_cols = [c for c in df.columns if c not in existing]
        st.dataframe(df[existing + other_cols], use_container_width=True)

        # Distribution chart
        if score_col:
            fig = px.histogram(df, x=score_col, nbins=20, title="Readiness Score Distribution")
            st.plotly_chart(fig, use_container_width=True)

        # Allow clicking one ticker for details (selectbox)
        st.markdown("### Inspect a ticker")
        ticker_select = st.selectbox("Choose ticker", options=sorted(df['Ticker'].unique()))
        if st.button("Open detail view for selected ticker"):
            st.session_state._detail_ticker = ticker_select
            st.experimental_rerun()

# TICKER DETAIL page
elif page == "Ticker Detail":
    st.title("Ticker Detail")
    # determine which ticker to show
    detail_ticker = st.session_state.get('_detail_ticker', None)
    if detail_ticker is None:
        st.info("Pick a ticker from Results Summary and click 'Open detail view', or enter a ticker below.")
        detail_ticker = st.text_input("Enter ticker to inspect (or paste e.g. AAPL)", value="")
        if detail_ticker.strip() == "":
            st.stop()
    # fetch latest analysis (run fresh to ensure up-to-date)
    ticker = detail_ticker.strip().upper()
    st.header(f"Details: {ticker}")
    try:
        with st.spinner("Computing details..."):
            res = run_full_scan_single(ticker)
        if res.get('error'):
            st.error(f"Error: {res['error']}")
        else:
            col_left, col_right = st.columns([2,1])
            with col_left:
                st.subheader("Score & Signal")
                st.metric("Readiness Score", f"{res.get('final_readiness_score','N/A')}", delta=f"{res.get('buy_signal','')}")
                st.write("Signal Strength:", res.get('signal_strength'))
                st.write("Score trend:", res.get('score_trend'))
                st.write("MTF positive count:", res.get('mtf_positive_count'), " MTf details:", res.get('mtf_details'))
                st.write("Buy-the-dip:", res.get('buy_the_dip'), " Pullback:", res.get('btd_pullback_pct'))
            with col_right:
                st.subheader("Key subscores")
                ss = {
                    "Price": res.get('price_subscore'),
                    "Flow": res.get('flow_subscore'),
                    "Fundamentals": res.get('fund_subscore'),
                    "Inst Proxy": res.get('inst_flow_proxy')
                }
                for k,v in ss.items():
                    st.progress(min(100, int(v if (v is not None and not (isinstance(v,float) and np.isnan(v))) else 0)))
                    st.caption(f"{k}: {v}")

            # Price chart + RSI / Volume
            try:
                histd = get_history(ticker, timeframe='1d')
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=histd.index, open=histd['Open'], high=histd['High'], low=histd['Low'], close=histd['Close'], name="Price"))
                fig.update_layout(height=450, margin=dict(t=10,l=10,r=10,b=10), title=f"{ticker} — Daily")
                st.plotly_chart(fig, use_container_width=True)

                # RSI chart
                r = rsi(histd['Close'], RSI_PERIOD)
                fig2 = px.line(x=histd.index, y=r, labels={'x':'Date','y':'RSI'}, title="RSI")
                fig2.update_layout(height=220, margin=dict(t=10,l=10,r=10,b=10))
                st.plotly_chart(fig2, use_container_width=True)

                # Volume / OBV
                vol_df = histd[['Volume']].copy()
                vol_df['OBV'] = compute_obv(histd)
                fig3 = go.Figure()
                fig3.add_trace(go.Bar(x=vol_df.index, y=vol_df['Volume'], name='Volume'))
                fig3.add_trace(go.Scatter(x=vol_df.index, y=vol_df['OBV'], name='OBV', yaxis='y2'))
                fig3.update_layout(title="Volume & OBV", height=300, margin=dict(t=10,l=10,r=10,b=10),
                                   yaxis=dict(title="Volume"), yaxis2=dict(title="OBV", overlaying='y', side='right'))
                st.plotly_chart(fig3, use_container_width=True)
            except Exception:
                st.info("Could not retrieve charts for this ticker.")

            # Options info
            st.subheader("Options Snapshot (nearest expiry)") 
            opt = compute_options_metrics(ticker)
            st.write(opt)

    except Exception as e:
        st.error("Failed to compute details.")
        st.code(traceback.format_exc())

# HISTORY page
elif page == "History":
    st.title("Scan History")
    st.markdown("Recent session scans (stored in-memory) and persisted history CSV")

    st.subheader("Session history")
    if not st.session_state.history:
        st.info("No session scans recorded yet.")
    else:
        sh = pd.DataFrame(st.session_state.history)
        st.dataframe(sh)

    st.subheader("Persisted history (readiness_history.csv)")
    try:
        import os
        if os.path.exists(HISTORY_CSV):
            hist_df = pd.read_csv(HISTORY_CSV)
            st.dataframe(hist_df.tail(200))
            # small summary chart
            if 'Score' in hist_df.columns:
                agg = hist_df.groupby('Ticker')['Score'].agg(['mean','count']).reset_index().sort_values('mean', ascending=False).head(10)
                fig = px.bar(agg, x='Ticker', y='mean', title="Top average score (by ticker)")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No persisted history file found yet.")
    except Exception:
        st.error("Could not load persisted history.")
        st.code(traceback.format_exc())

# Footer
st.sidebar.markdown("---")
st.sidebar.write("Built from user's scanner logic — multi-page Streamlit app")
st.sidebar.write("Pro tip: limit bulk scans to small groups on Streamlit Cloud to avoid timeouts.")
