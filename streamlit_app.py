import streamlit as st
import pandas as pd
from advanced_readiness_scanner_mtf_btd import (
    TOP_LEVEL_TICKERS,
    run_full_scan  # you create this wrapper to run your logic per ticker
)

st.set_page_config(page_title="Readiness Scanner", layout="wide")

st.title("📊 Advanced Readiness Scanner (MTF + BTD)")
st.write("Run analysis on a single ticker or scan all tickers in your list.")

# -------------------------------------------------------------------
# UI INPUTS
# -------------------------------------------------------------------
st.subheader("Single Ticker Scan")
single_ticker = st.text_input("Enter Ticker (e.g., AAPL, TSLA, BTC-USD, EURUSD=X)")

run_single = st.button("Run Single Ticker Scan")

st.divider()

st.subheader("Bulk Scan")
run_bulk = st.button("Run Full Bulk Scan (All Tickers)")

# -------------------------------------------------------------------
# RUN SINGLE TICKER
# -------------------------------------------------------------------
if run_single:
    if not single_ticker.strip():
        st.error("Please enter a ticker.")
    else:
        with st.spinner(f"Running scan for {single_ticker}..."):
            try:
                result = run_full_scan(single_ticker.upper())

                if isinstance(result, pd.DataFrame):
                    st.success(f"Scan complete for {single_ticker}")
                    st.dataframe(result, use_container_width=True)
                else:
                    st.json(result)

            except Exception as e:
                st.error(f"Error: {e}")

# -------------------------------------------------------------------
# RUN BULK SCAN
# -------------------------------------------------------------------
if run_bulk:
    if not TOP_LEVEL_TICKERS:
        st.error("Your TOP_LEVEL_TICKERS list is empty.")
    else:
        st.info(f"Scanning {len(TOP_LEVEL_TICKERS)} tickers...")
        all_results = []

        progress = st.progress(0)
        for i, t in enumerate(TOP_LEVEL_TICKERS):
            progress.progress((i+1)/len(TOP_LEVEL_TICKERS))
            try:
                data = run_full_scan(t)
                if isinstance(data, dict):
                    all_results.append(data)
                elif isinstance(data, pd.DataFrame):
                    all_results.append(data.to_dict(orient="records")[0])
            except Exception as e:
                all_results.append({"Ticker": t, "Error": str(e)})

        df = pd.DataFrame(all_results)
        st.success("Bulk scan complete!")
        st.dataframe(df, use_container_width=True)

        # Option to download results
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download Results (CSV)",
            csv,
            "readiness_bulk_results.csv",
            "text/csv"
        )
