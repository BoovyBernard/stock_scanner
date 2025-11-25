import streamlit as st
import pandas as pd
import time
import traceback

# IMPORT YOUR FULL SCANNER LOGIC
from advanced_readiness_scanner_mtf_btd import (
    get_history,
    compute_technical_metrics_from_hist,
    compute_options_metrics,
    detect_asset_class,
    detect_sector,
    score_price_momentum_from_tech,
    score_volume_flow_from_tech_opt,
    score_fundamentals,
    institutional_flow_proxy,
    get_buy_signal_from_score
)

st.set_page_config(page_title="Readiness Scanner", layout="wide")

st.title("📊 Advanced Readiness Scanner (Multi-TF + BTD)")

ticker = st.text_input("Enter Ticker (e.g., AAPL, TSLA, SPY)", value="AAPL")

run_button = st.button("Run Scanner")

if run_button:
    try:
        st.write("Fetching data… this may take a few seconds...")

        # Multi-timeframe data
        results = {}
        for tf in ["1d", "4h", "1h"]:
            hist = get_history(ticker, timeframe=tf)
            tech = compute_technical_metrics_from_hist(hist)
            opt = compute_options_metrics(ticker)

            price_score = score_price_momentum_from_tech(tech)
            flow_score = score_volume_flow_from_tech_opt(tech, opt, detect_asset_class(ticker))
            fund_score = score_fundamentals(ticker)
            inst_score = institutional_flow_proxy(tech, opt)

            total = (
                price_score * 0.5 +
                flow_score * 0.3 +
                fund_score * 0.2 +
                inst_score * 0.1
            )

            results[tf] = {
                "Price Score": price_score,
                "Flow Score": flow_score,
                "Fundamentals": fund_score,
                "Inst. Flow": inst_score,
                "Total Score": total,
                "Signal": get_buy_signal_from_score(total)
            }

        st.success("Scan Complete!")

        df = pd.DataFrame(results).T
        st.dataframe(df)

        # Final decision
        final_signal = df["Total Score"].mean()
        st.header("Final Signal")
        st.subheader(f"📌 {get_buy_signal_from_score(final_signal)} ({final_signal:.2f})")

    except Exception as e:
        st.error("Error occurred:")
        st.code(traceback.format_exc())
