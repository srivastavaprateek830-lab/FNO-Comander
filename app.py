import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from data.dhan_client import DhanClient, DhanAPIError
from data.universe import load_fno_universe, load_instrument_master
from engine.scanner import scan_universe
from engine.regime import market_regime
from options.analyzer import analyze_option_chain
from ui.components import inject_css, metric_card, signal_badge, render_signal_table, render_option_chain


st.set_page_config(
    page_title="FNO COMMANDER",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

st.title("📈 FNO COMMANDER")
st.caption("Personal Indian F&O Research & High-Conviction Alert Terminal")

# ---------------------------
# Secrets / connection
# ---------------------------
try:
    client_id = st.secrets["DHAN_CLIENT_ID"]
    access_token = st.secrets["DHAN_ACCESS_TOKEN"]
except Exception:
    st.error("Dhan credentials are missing. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in Streamlit Secrets.")
    st.stop()

client = DhanClient(client_id, access_token)

# ---------------------------
# Sidebar
# ---------------------------
with st.sidebar:
    st.header("COMMAND CENTER")
    page = st.radio(
        "Navigate",
        ["Dashboard", "F&O Scanner", "Deep Dive", "Option Chain"],
        label_visibility="collapsed",
    )

    st.divider()

    st.subheader("Scanner Controls")
    min_score = st.slider("Minimum conviction", 50, 95, 75, 1)
    candidate_count = st.slider("Stage-2 candidates", 10, 50, 25, 5)
    refresh_seconds = st.slider("Auto refresh (sec)", 0, 300, 60, 30)

    if st.button("🔄 FORCE REFRESH", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption("Data source")
    st.write("DhanHQ API")
    st.caption("Signals only • No order execution")

# Optional periodic refresh. Zero disables it.
if refresh_seconds > 0:
    st_autorefresh(interval=refresh_seconds * 1000, key="fno_commander_refresh")

# ---------------------------
# Load universe
# ---------------------------
try:
    instruments = load_instrument_master()
    universe = load_fno_universe(instruments)
except Exception as exc:
    st.error(f"Unable to load Dhan instrument master: {exc}")
    st.stop()

# ---------------------------
# Market snapshot
# ---------------------------
def get_market_snapshot():
    # Index IDs are resolved from the instrument master.
    idx = {}
    for name in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
        matches = instruments[
            instruments["SYMBOL_NAME"].astype(str).str.upper().eq(name)
        ]
        if not matches.empty:
            idx[name] = int(matches.iloc[0]["SECURITY_ID"])

    if not idx:
        return pd.DataFrame()

    quote = client.quote({"IDX_I": list(idx.values())})
    rows = []
    for name, sid in idx.items():
        item = quote.get("IDX_I", {}).get(str(sid), {})
        rows.append({
            "symbol": name,
            "security_id": sid,
            "ltp": item.get("last_price"),
            "change": item.get("net_change"),
            "volume": item.get("volume"),
        })
    return pd.DataFrame(rows)


# ---------------------------
# Dashboard
# ---------------------------
if page == "Dashboard":
    st.subheader("Market Regime")

    try:
        market_df = get_market_snapshot()
    except Exception:
        market_df = pd.DataFrame()

    if market_df.empty:
        st.warning("Index snapshot unavailable. Scanner can still run.")
    else:
        cols = st.columns(4)
        for i, name in enumerate(["NIFTY", "BANKNIFTY", "FINNIFTY"]):
            row = market_df[market_df["symbol"] == name]
            if row.empty:
                cols[i].metric(name, "—")
            else:
                r = row.iloc[0]
                cols[i].metric(
                    name,
                    f"{r['ltp']:,.2f}" if pd.notna(r["ltp"]) else "—",
                    f"{r['change']:+.2f}" if pd.notna(r["change"]) else None,
                )
        regime = market_regime(market_df)
        cols[3].metric("REGIME", regime["label"], f"{regime['score']}/100")

    st.divider()

    with st.spinner("Scanning F&O universe…"):
        try:
            results = scan_universe(
                _client=client,
                universe=universe,
                stage2_count=candidate_count,
                min_score=min_score,
            )
        except DhanAPIError as exc:
            st.error(str(exc))
            results = pd.DataFrame()
        except Exception as exc:
            st.error(f"Scanner error: {exc}")
            results = pd.DataFrame()

    if results.empty:
        st.info("No qualifying setups found. Try a lower conviction threshold or refresh.")
    else:
        high = results[results["score"] >= min_score].head(10)

        st.subheader("🔥 High-Conviction Signals")
        render_signal_table(high)

        st.subheader("Signal Reasoning")
        if not high.empty:
            selected = high.iloc[0]
            c1, c2 = st.columns([1, 2])
            with c1:
                signal_badge(selected["signal"], selected["score"])
                st.metric("Price", f"₹{selected['price']:,.2f}")
                st.metric("RVOL", f"{selected['rvol']:.2f}x")
                st.metric("RSI", f"{selected['rsi']:.1f}")
            with c2:
                st.markdown("### Why it surfaced")
                for reason in selected["reasons"]:
                    st.success(reason)
                if selected["risks"]:
                    st.markdown("### Risk / veto flags")
                    for risk in selected["risks"]:
                        st.warning(risk)

        st.caption(f"Universe: {len(universe)} F&O underlyings • Stage-2 inspected: {candidate_count} • Updated: {datetime.now().strftime('%H:%M:%S')}")

# ---------------------------
# F&O Scanner
# ---------------------------
elif page == "F&O Scanner":
    st.subheader("F&O Universe Scanner")
    st.caption("Stage 1 uses Dhan market quotes; Stage 2 validates selected candidates with 15-minute candles.")

    with st.spinner("Running scanner…"):
        try:
            results = scan_universe(
                _client=client,
                universe=universe,
                stage2_count=candidate_count,
                min_score=min_score,
            )
        except Exception as exc:
            st.error(str(exc))
            results = pd.DataFrame()

    if results.empty:
        st.warning("No results.")
    else:
        filter_mode = st.selectbox("View", ["All", "BUY", "SELL", "WATCH"])
        view = results if filter_mode == "All" else results[results["signal"] == filter_mode]
        render_signal_table(view, full=True)

# ---------------------------
# Deep Dive
# ---------------------------
elif page == "Deep Dive":
    st.subheader("Stock Deep Dive")

    symbols = universe["symbol"].dropna().sort_values().tolist()
    symbol = st.selectbox("Select F&O stock", symbols)

    row = universe[universe["symbol"] == symbol].iloc[0]
    sid = int(row["security_id"])

    timeframe = st.selectbox("Primary timeframe", ["5", "15", "60"], index=1)

    with st.spinner(f"Loading {symbol}…"):
        try:
            df = client.intraday(
                security_id=sid,
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                interval=timeframe,
                days=60,
                oi=False,
            )
        except Exception as exc:
            st.error(str(exc))
            st.stop()

    from indicators.technicals import add_indicators
    df = add_indicators(df)

    st.metric("Last Price", f"₹{df.iloc[-1]['close']:,.2f}")

    chart_df = df.tail(250).copy()
    st.line_chart(
        chart_df.set_index("timestamp")[["close", "ema20", "ema50", "ema200", "vwap"]]
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    last = df.iloc[-1]
    c1.metric("EMA20", f"{last['ema20']:,.2f}")
    c2.metric("EMA50", f"{last['ema50']:,.2f}")
    c3.metric("EMA200", f"{last['ema200']:,.2f}")
    c4.metric("RSI", f"{last['rsi']:.1f}")
    c5.metric("RVOL", f"{last['rvol']:.2f}x")

    st.markdown("### Technical validation")
    checks = {
        "Price > EMA20": last["close"] > last["ema20"],
        "EMA20 > EMA50": last["ema20"] > last["ema50"],
        "EMA50 > EMA200": last["ema50"] > last["ema200"],
        "Price > VWAP": last["close"] > last["vwap"],
        "RSI > 50": last["rsi"] > 50,
        "RVOL > 1.5x": last["rvol"] > 1.5,
    }
    st.dataframe(
        pd.DataFrame(
            [{"Parameter": k, "Pass": "✓" if v else "✕"} for k, v in checks.items()]
        ),
        use_container_width=True,
        hide_index=True,
    )

# ---------------------------
# Option Chain
# ---------------------------
elif page == "Option Chain":
    st.subheader("Option Chain Intelligence")

    symbols = universe["symbol"].dropna().sort_values().tolist()
    symbol = st.selectbox("Underlying", symbols)
    row = universe[universe["symbol"] == symbol].iloc[0]
    sid = int(row["security_id"])

    try:
        expiries = client.option_expiries(sid, "NSE_EQ")
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    if not expiries:
        st.warning("No active option expiries returned by Dhan.")
        st.stop()

    expiry = st.selectbox("Expiry", expiries)

    if st.button("Load Option Chain", type="primary"):
        with st.spinner("Fetching option chain…"):
            try:
                raw = client.option_chain(sid, "NSE_EQ", expiry)
                analysis = analyze_option_chain(raw)
            except Exception as exc:
                st.error(str(exc))
                st.stop()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Spot", f"₹{analysis['spot']:,.2f}")
        c2.metric("PCR", f"{analysis['pcr']:.2f}")
        c3.metric("Call Wall", f"{analysis['call_wall']:,.0f}")
        c4.metric("Put Wall", f"{analysis['put_wall']:,.0f}")

        st.markdown("### Option Chain")
        render_option_chain(analysis["table"])

        st.markdown("### Suggested trade-side validation")
        if analysis["pcr"] > 1.15:
            st.success("Put OI dominance: bullish support bias.")
        elif analysis["pcr"] < 0.85:
            st.error("Call OI dominance: bearish resistance bias.")
        else:
            st.info("PCR is neutral; require price/volume/OI confirmation.")

        st.caption("Option-chain requests are intentionally isolated from the broad universe scan to respect Dhan's option-chain rate limit.")
