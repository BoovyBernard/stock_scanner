# streamlit_app.py
import streamlit as st
import pandas as pd
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import scanner functions (same folder)
from advanced_readiness_scanner_mtf_btd import TOP_LEVEL_TICKERS, run_full_scan

st.set_page_config(page_title="Readiness Scanner", layout="wide")
st.title("📊 Advanced Readiness Scanner (MTF + BTD)")

st.markdown("Enter a ticker and click **Run**, or click **Scan All** to run through your TOP_LEVEL_TICKERS list.")

col1, col2 = st.columns([2,1])
with col1:
    single_ticker = st.text_input("Single Ticker (e.g., AAPL)", value="AAPL")
with col2:
    run_single = st.button("Run Single")

st.markdown("---")
run_bulk = st.button(f"Scan All ({len(TOP_LEVEL_TICKERS)} tickers)")

# Option: limit concurrency (avoid blowing up resources)
MAX_WORKERS = 6

def run_single_ticker_ui(ticker):
    try:
        st.info(f"Running scan for {ticker} ...")
        res = run_full_scan(ticker)
        if isinstance(res, dict):
            df = pd.DataFrame([res])
            st.success(f"Scan complete for {ticker}")
            st.dataframe(df, use_container_width=True)
            return df
        else:
            st.json(res)
            return None
    except Exception:
        st.error("Error while scanning single ticker.")
        st.code(traceback.format_exc())
        return None

if run_single:
    ticker = single_ticker.strip().upper()
    if ticker == "":
        st.error("Please provide a ticker.")
    else:
        run_single_ticker_ui(ticker)

if run_bulk:
    tickers = list(dict.fromkeys([t.strip().upper() for t in TOP_LEVEL_TICKERS if t and isinstance(t, str)]))
    if not tickers:
        st.error("No tickers configured in TOP_LEVEL_TICKERS inside advanced_readiness_scanner_mtf_btd.py")
    else:
        st.info(f"Starting bulk scan for {len(tickers)} tickers. This may take some time.")
        progress = st.progress(0)
        results = []
        errors = []
        start = time.time()

        # Using ThreadPoolExecutor to parallelize network calls a bit (yfinance does HTTP IO)
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tickers))) as ex:
            futures = {ex.submit(run_full_scan, t): t for t in tickers}
            completed = 0
            for fut in as_completed(futures):
                t = futures[fut]
                try:
                    res = fut.result()
                    results.append(res)
                except Exception as e:
                    errors.append({"Ticker": t, "error": str(e)})
                completed += 1
                progress.progress(completed / len(tickers))

        elapsed = time.time() - start
        st.success(f"Bulk scan finished in {elapsed:.1f}s — {len(results)} results, {len(errors)} errors.")
        if results:
            df = pd.json_normalize(results)
            # Show most important columns first if they exist
            show_cols = ['Ticker','asset_class','sector','final_readiness_score','buy_signal','mtf_positive_count','buy_the_dip']
            existing = [c for c in show_cols if c in df.columns]
            st.dataframe(df[existing + [c for c in df.columns if c not in existing]], use_container_width=True)
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Download CSV", csv, "readiness_bulk.csv", "text/csv")
        if errors:
            st.warning(f"{len(errors)} tickers failed. See details below.")
            st.json(errors)
