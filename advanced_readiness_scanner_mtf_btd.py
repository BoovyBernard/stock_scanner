# advanced_readiness_scanner_mtf_btd.py
# Cleaned and self-contained scanner module for Streamlit use.
# NOTE: This module MUST NOT import streamlit.

import os
import math
from datetime import datetime, timedelta
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup

# -----------------------------
# CONFIG
# -----------------------------
HIST_DAYS = 180
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
OBV_LOOKBACK = 14
VOLUME_SPIKE_MULT = 1.5

INST_FLOW_WEIGHT = 0.10

MTF_TIMEFRAMES = ["1d", "4h", "1h"]
MTF_POSITIVE_PRICE_SCORE = 60.0

BTD_LOOKBACK_DAYS = 20
BTD_MIN_PULLBACK = 0.02
BTD_MAX_PULLBACK = 0.08
BTD_REQUIRE_DAILY_UPTREND = True

OUTPUT_FILE = "readiness_scores.xlsx"
HISTORY_CSV = "readiness_history.csv"

# baseline example tickers (you can populate this list or leave empty)
TOP_LEVEL_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"]

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
# Helpers: indicators & utils
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
# Data retrieval (multi-timeframe aware)
# -----------------------------
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
# Scoring functions
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

# -----------------------------
# Buy signal helpers & history
# -----------------------------
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
        header = not os.path.exists(history_file)
        row.to_csv(history_file, mode='a', header=header, index=False)
    except Exception:
        pass

# -----------------------------
# Buy-The-Dip detection (simple)
# -----------------------------
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

# -----------------------------
# Wrapper: run_full_scan
# -----------------------------
def run_full_scan(ticker):
    """
    Run full scan for a single ticker.
    Returns a dict with computed metrics and final score.
    """
    rec = {"Ticker": ticker}
    try:
        asset_class = detect_asset_class(ticker)
        sector = detect_sector(ticker, asset_class)

        hist_daily = get_history(ticker, timeframe='1d')
        tech_daily = compute_technical_metrics_from_hist(hist_daily)
        price_sub = score_price_momentum_from_tech(tech_daily)
        opt = compute_options_metrics(ticker)
        flow_sub = score_volume_flow_from_tech_opt(tech_daily, opt, asset_class)
        fund_sub = score_fundamentals(ticker) if SCORES_CONFIG.get(asset_class, SCORES_CONFIG['UNKNOWN'])['fund'] > 0 else 50.0
        inst_proxy = institutional_flow_proxy(tech_daily, opt) if INST_FLOW_WEIGHT > 0 else 50.0

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

        mtf_count = 0
        mtf_details = {}
        for tf in MTF_TIMEFRAMES:
            try:
                hist = get_history(ticker, timeframe=tf)
                tech = compute_technical_metrics_from_hist(hist)
                price_score = score_price_momentum_from_tech(tech)
                mtf_details[tf] = price_score
                if price_score >= MTF_POSITIVE_PRICE_SCORE:
                    mtf_count += 1
            except Exception:
                mtf_details[tf] = np.nan

        btd_flag, btd_pullback, btd_recent_high = detect_buy_the_dip(ticker)
        buy_signal = get_buy_signal_from_score(final_score)

        # Refinements
        if buy_signal in ("STRONG BUY","BUY"):
            if mtf_count < 2:
                if buy_signal == "STRONG BUY":
                    if not (btd_flag and final_score >= 70):
                        buy_signal = "WATCHLIST"
                else:
                    if not (btd_flag and final_score >= 70):
                        buy_signal = "WATCHLIST"
        else:
            if btd_flag and (final_score >= 70):
                buy_signal = "BUY (BTD)"
            elif btd_flag and (final_score >= 65):
                buy_signal = "WATCHLIST (BTD)"

        append_history_row(ticker, final_score, buy_signal)

        rec.update({
            'asset_class': asset_class,
            'sector': sector,
            'price_subscore': round(price_sub,2),
            'flow_subscore': round(flow_sub,2),
            'fund_subscore': round(float(fund_val),2),
            'inst_flow_proxy': round(float(inst_val),2),
            'final_readiness_score': round(float(final_score),2),
            'buy_signal': buy_signal,
            'mtf_positive_count': int(mtf_count),
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
# Optional fetchers (kept minimal)
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
        return TOP_LEVEL_TICKERS
