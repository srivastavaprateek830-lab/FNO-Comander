import pandas as pd
import streamlit as st
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from data.dhan_client import DhanClient, DhanAPIError
from data.universe import load_fno_universe, load_instrument_master
from engine.regime import market_regime
from engine.scanner import scan_universe
from engine.mtf import summarize_timeframe
from engine.trade_plan import build_trade_plan
from indicators.technicals import add_indicators
from options.analyzer import analyze_option_chain
from ui.components import (
    inject_css,
    render_mtf_table,
    render_option_chain,
    render_signal_table,
    regime_badge,
    section_title,
    signal_badge,
)


st.set_page_config(
    page_title="FNO COMMANDER",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()


# -----------------------------------------------------------------------------
# Dhan connection
# -----------------------------------------------------------------------------
try:
    client_id = st.secrets["DHAN_CLIENT_ID"]
    access_token = st.secrets["DHAN_ACCESS_TOKEN"]
except Exception:
    st.error("Dhan credentials are missing. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in Streamlit Secrets.")
    st.stop()

client = DhanClient(client_id, access_token)


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## COMMAND CENTER")
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

if refresh_seconds > 0:
    st_autorefresh(interval=refresh_seconds * 1000, key="fno_commander_refresh")


# -----------------------------------------------------------------------------
# Cached data helpers
# -----------------------------------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def cached_instrument_master():
    return load_instrument_master()


@st.cache_data(ttl=86400, show_spinner=False)
def cached_universe(instruments):
    return load_fno_universe(instruments)


@st.cache_data(ttl=45, show_spinner=False)
def cached_market_snapshot(_client, instruments):
    idx = {}
    for name in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
        matches = instruments[
            instruments["SYMBOL_NAME"].astype(str).str.upper().eq(name)
        ]
        if not matches.empty:
            idx[name] = int(matches.iloc[0]["SECURITY_ID"])

    if not idx:
        return pd.DataFrame()

    quote = _client.quote({"IDX_I": list(idx.values())})
    rows = []
    for name, sid in idx.items():
        item = quote.get("IDX_I", {}).get(str(sid), {})
        rows.append(
            {
                "symbol": name,
                "security_id": sid,
                "ltp": item.get("last_price"),
                "change": item.get("net_change"),
                "volume": item.get("volume"),
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=90, show_spinner=False)
def cached_stock_data(_client, security_id, interval="15", days=60):
    return _client.intraday(
        security_id=int(security_id),
        exchange_segment="NSE_EQ",
        instrument="EQUITY",
        interval=str(interval),
        days=int(days),
        oi=False,
    )


@st.cache_data(ttl=90, show_spinner=False)
def cached_futures_data(_client, future_security_id):
    if pd.isna(future_security_id):
        return pd.DataFrame()
    return _client.intraday(
        security_id=int(future_security_id),
        exchange_segment="NSE_FNO",
        instrument="FUTSTK",
        interval="15",
        days=5,
        oi=True,
    )


@st.cache_data(ttl=90, show_spinner=False)
def cached_mtf(_client, security_id):
    output = []
    for interval, label in [("5", "5M"), ("15", "15M"), ("60", "60M")]:
        try:
            df = cached_stock_data(_client, security_id, interval=interval, days=30)
            summary = summarize_timeframe(df)
            output.append(
                {
                    "TIMEFRAME": label,
                    "SIGNAL": summary["signal"],
                    "SCORE": summary["score"],
                    "RSI": round(summary["rsi"], 1) if summary["rsi"] is not None else None,
                    "RVOL": round(summary["rvol"], 2) if summary["rvol"] is not None else None,
                }
            )
        except Exception:
            output.append({"TIMEFRAME": label, "SIGNAL": "NO DATA", "SCORE": 50, "RSI": None, "RVOL": None})
    return output


def futures_oi_summary(df):
    if df is None or df.empty or "oi" not in df.columns or len(df) < 2:
        return {"status": "NO OI DATA", "price_change": None, "oi_change": None}

    last = df.iloc[-1]
    prev = df.iloc[-2]
    price_change = float(last["close"] - prev["close"])
    oi_change = float(last["oi"] - prev["oi"])

    if price_change > 0 and oi_change > 0:
        status = "LONG BUILDUP"
    elif price_change < 0 and oi_change > 0:
        status = "SHORT BUILDUP"
    elif price_change > 0 and oi_change < 0:
        status = "SHORT COVERING"
    elif price_change < 0 and oi_change < 0:
        status = "LONG UNWINDING"
    else:
        status = "NEUTRAL"

    return {"status": status, "price_change": price_change, "oi_change": oi_change}


def option_preference(analysis, signal):
    table = analysis.get("table")
    if table is None or table.empty:
        return "—"
    row = table.iloc[(table["Strike"] - analysis["spot"]).abs().argsort()[:1]].iloc[0]
    strike = row["Strike"]
    if signal == "BUY":
        return f"ATM / near-ATM CE · {strike:,.0f}"
    if signal == "SELL":
        return f"ATM / near-ATM PE · {strike:,.0f}"
    return f"ATM · {strike:,.0f}"


# -----------------------------------------------------------------------------
# Load base universe
# -----------------------------------------------------------------------------
try:
    instruments = cached_instrument_master()
    universe = cached_universe(instruments)
except Exception as exc:
    st.error(f"Unable to load Dhan instrument master: {exc}")
    st.stop()


# -----------------------------------------------------------------------------
# Market context + scanner
# -----------------------------------------------------------------------------
try:
    market_df = cached_market_snapshot(client, instruments)
except Exception:
    market_df = pd.DataFrame()

regime = market_regime(market_df)

@st.cache_data(ttl=45, show_spinner=False)
def run_scanner(_client, universe, stage2_count, minimum_score, market_bias):
    return scan_universe(
        _client=_client,
        universe=universe,
        stage2_count=stage2_count,
        min_score=minimum_score,
        market_bias=market_bias,
    )

try:
    with st.spinner("Refreshing F&O intelligence…"):
        results = run_scanner(
            client,
            universe,
            candidate_count,
            min_score,
            regime["label"],
        )
except DhanAPIError as exc:
    st.error(str(exc))
    results = pd.DataFrame()
except Exception as exc:
    st.error(f"Scanner error: {exc}")
    results = pd.DataFrame()


# -----------------------------------------------------------------------------
# DASHBOARD — integrated command center
# -----------------------------------------------------------------------------
if page == "Dashboard":
    st.markdown('<div class="hero-title">📈 FNO COMMANDER</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">Integrated Indian F&O research & high-conviction alert terminal</div>', unsafe_allow_html=True)

    # Market strip
    section_title("MARKET REGIME", "Index direction is used as a market-level context filter.")
    top = st.columns(4)
    for i, name in enumerate(["NIFTY", "BANKNIFTY", "FINNIFTY"]):
        row = market_df[market_df["symbol"] == name] if not market_df.empty else pd.DataFrame()
        if row.empty:
            top[i].metric(name, "—")
        else:
            r = row.iloc[0]
            top[i].metric(
                name,
                f"{r['ltp']:,.2f}" if pd.notna(r["ltp"]) else "—",
                f"{r['change']:+.2f}" if pd.notna(r["change"]) else None,
            )
    with top[3]:
        st.markdown("**REGIME**")
        regime_badge(regime["label"], regime["score"])
        st.caption("Model context")

    # Signal breadth from the actual scanned universe
    if not results.empty:
        buys = int((results["signal"] == "BUY").sum())
        sells = int((results["signal"] == "SELL").sum())
        watches = int((results["signal"] == "WATCH").sum())
    else:
        buys = sells = watches = 0

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("F&O STOCKS", f"{len(universe)}")
    b2.metric("BUY SIGNALS", buys)
    b3.metric("SELL SIGNALS", sells)
    b4.metric("WATCH", watches)

    st.divider()

    # Radar
    section_title(
        "🔥 HIGH-CONVICTION TRADE RADAR",
        "Stage-2 technical scan + 60M trend + futures OI enrichment. Option chain is loaded only when requested.",
    )
    high = results[results["score"] >= min_score].copy() if not results.empty else pd.DataFrame()
    radar = high.head(10) if not high.empty else results.head(10)

    if radar.empty:
        st.warning("No current candidates. Lower the minimum conviction or force refresh.")
        st.stop()

    # -------------------------------------------------------------------------
    # Interactive radar
    # -------------------------------------------------------------------------
    # The old version used a selectbox below the radar.  The dashboard now
    # behaves more like a trading terminal: click any row in the radar and the
    # selected stock drives every intelligence panel below.
    preferred = [
        "symbol", "signal", "score", "status", "price",
        "rvol", "rsi", "atr", "mtf_score", "oi_status", "priority"
    ]
    radar_cols = [c for c in preferred if c in radar.columns]
    radar_display = radar[radar_cols].copy()

    rename = {
        "symbol": "SYMBOL",
        "signal": "SIGNAL",
        "score": "SCORE",
        "status": "MODEL STATUS",
        "price": "PRICE",
        "rvol": "RVOL",
        "rsi": "RSI",
        "atr": "ATR",
        "mtf_score": "60M",
        "oi_status": "FUT OI",
        "priority": "PRIORITY",
    }
    radar_display = radar_display.rename(columns=rename)

    if "PRICE" in radar_display.columns:
        radar_display["PRICE"] = pd.to_numeric(
            radar_display["PRICE"], errors="coerce"
        ).map(lambda x: f"₹{x:,.2f}" if pd.notna(x) else "—")

    if "RVOL" in radar_display.columns:
        radar_display["RVOL"] = pd.to_numeric(
            radar_display["RVOL"], errors="coerce"
        ).map(lambda x: f"{x:.2f}x" if pd.notna(x) else "—")

    if "RSI" in radar_display.columns:
        radar_display["RSI"] = pd.to_numeric(
            radar_display["RSI"], errors="coerce"
        ).map(lambda x: f"{x:.1f}" if pd.notna(x) else "—")

    if "ATR" in radar_display.columns:
        radar_display["ATR"] = pd.to_numeric(
            radar_display["ATR"], errors="coerce"
        ).map(lambda x: f"{x:.2f}" if pd.notna(x) else "—")

    if "60M" in radar_display.columns:
        radar_display["60M"] = pd.to_numeric(
            radar_display["60M"], errors="coerce"
        ).map(lambda x: f"{x:.0f}" if pd.notna(x) else "—")

    st.caption(
        "Click any stock row below. The selected stock automatically drives "
        "Technical Confirmation, Trade Plan, MTF, Futures OI and Option Intelligence."
    )

    radar_event = st.dataframe(
        radar_display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="trade_radar",
    )

    # Persist the selection across Streamlit reruns/auto-refreshes.
    selected_rows = radar_event.selection.rows

    if selected_rows:
        clicked_index = selected_rows[0]
        clicked_symbol = str(
            radar_display.iloc[clicked_index]["SYMBOL"]
        )
        st.session_state["dashboard_selected_symbol"] = clicked_symbol

    selected_symbol = st.session_state.get("dashboard_selected_symbol")

    # If the previously selected stock has disappeared from the current radar
    # after a refresh, automatically fall back to the first available candidate.
    radar_symbols = radar["symbol"].astype(str).tolist()

    if selected_symbol not in radar_symbols:
        selected_symbol = radar_symbols[0]
        st.session_state["dashboard_selected_symbol"] = selected_symbol

    # Small confirmation line so it is obvious which row is driving the panels.
    st.markdown(
        f'<div class="tiny">Selected stock: <b>{selected_symbol}</b> '
        f'· Click another radar row to switch</div>',
        unsafe_allow_html=True,
    )

    selected = radar[radar["symbol"].astype(str) == selected_symbol].iloc[0]
    universe_row = universe[universe["symbol"] == selected_symbol].iloc[0]
    sid = int(universe_row["security_id"])

    # Selected trade + technicals
    st.divider()
    section_title("SELECTED TRADE INTELLIGENCE", f"Focused on {selected_symbol}. All panels below update from the same selected candidate.")

    stock15 = cached_stock_data(client, sid, interval="15", days=60)
    if stock15.empty:
        st.warning("15-minute technical data unavailable for the selected stock.")
        st.stop()

    tech = add_indicators(stock15)
    last = tech.iloc[-1]
    plan = build_trade_plan(selected["signal"], float(last["close"]), float(last["atr"]))

    left, mid, right = st.columns([1.0, 1.35, 1.35])

    with left:
        signal_badge(selected["signal"], selected["score"])
        st.caption(selected.get("status", "TECHNICAL ONLY"))
        st.metric("Last price", f"₹{last['close']:,.2f}")
        st.metric("RVOL", f"{last['rvol']:.2f}x")
        st.metric("RSI", f"{last['rsi']:.1f}")
        if "mtf_score" in selected:
            st.metric("60M confirmation", f"{float(selected['mtf_score']):.0f}/100")

    with mid:
        st.markdown("### Technical confirmation")
        checks = [
            ("Price > EMA20", last["close"] > last["ema20"]),
            ("EMA20 > EMA50", last["ema20"] > last["ema50"]),
            ("EMA50 > EMA200", last["ema50"] > last["ema200"]),
            ("Price > VWAP", last["close"] > last["vwap"]),
            ("SuperTrend bullish", last["supertrend"] == 1),
            ("MACD bullish", last["macd"] > last["macd_signal"]),
            ("RVOL > 1.5x", last["rvol"] > 1.5),
        ]
        for label, passed in checks:
            icon = "✓" if passed else "✕"
            cls = "check" if passed else "cross"
            st.markdown(f'<span class="{cls}">{icon}</span> {label}', unsafe_allow_html=True)

    with right:
        st.markdown("### Reference trade plan")
        if plan:
            st.metric("Entry reference", f"₹{plan['entry']:,.2f}")
            st.metric("Stop reference", f"₹{plan['sl']:,.2f}")
            p1, p2 = st.columns(2)
            p1.metric("Target 1", f"₹{plan['target1']:,.2f}")
            p2.metric("Target 2", f"₹{plan['target2']:,.2f}")
            st.caption(f"Reference R:R: 1:{plan['rr2']:.1f} to Target 2 · ATR based")
        else:
            st.info("Trade levels available only for BUY/SELL signals.")

    # MTF + futures OI
    mtf_col, oi_col = st.columns([1.25, 1])
    with mtf_col:
        section_title("MULTI-TIMEFRAME CONFIRMATION", "5M / 15M / 60M — informational confirmation, not an execution trigger.")
        mtf_rows = cached_mtf(client, sid)
        render_mtf_table(mtf_rows)

    with oi_col:
        section_title("FUTURES OI INTELLIGENCE", "Nearest F&O future; price/OI change on the latest 15-minute bars.")
        fut_df = cached_futures_data(client, universe_row["future_security_id"])
        oi = futures_oi_summary(fut_df)
        st.markdown(f"### {oi['status']}")
        if oi["price_change"] is not None:
            st.metric("Last-bar price change", f"{oi['price_change']:+.2f}")
            st.metric("Last-bar OI change", f"{oi['oi_change']:+,.0f}")
        else:
            st.caption("Dhan did not return usable OI bars for this future.")

    # Option intelligence on demand from the same screen
    st.divider()
    section_title("OPTION INTELLIGENCE", "Loaded on demand to respect Dhan option-chain request limits.")
    option_col1, option_col2 = st.columns([1.3, 1])
    with option_col1:
        st.markdown("**Preferred side:** " + ("🟢 CE" if selected["signal"] == "BUY" else "🔴 PE" if selected["signal"] == "SELL" else "⚪ WAIT"))
        st.caption("The option panel is intentionally on-demand; it is not repeatedly requested during every auto-refresh.")
    with option_col2:
        load_options = st.button("Load Option Intelligence", type="primary", use_container_width=True)

    if load_options:
        try:
            expiries = client.option_expiries(sid, "NSE_EQ")
            if not expiries:
                st.warning("No active option expiries returned by Dhan.")
            else:
                expiry = expiries[0]
                with st.spinner("Fetching option chain…"):
                    raw = client.option_chain(sid, "NSE_EQ", expiry)
                    analysis = analyze_option_chain(raw)

                oc1, oc2, oc3, oc4 = st.columns(4)
                oc1.metric("Spot", f"₹{analysis['spot']:,.2f}")
                oc2.metric("PCR", f"{analysis['pcr']:.2f}")
                oc3.metric("Call Wall", f"{analysis['call_wall']:,.0f}" if analysis["call_wall"] else "—")
                oc4.metric("Put Wall", f"{analysis['put_wall']:,.0f}" if analysis["put_wall"] else "—")
                st.markdown(f"**Model option preference:** {option_preference(analysis, selected['signal'])}")
                render_option_chain(analysis["table"])
        except Exception as exc:
            st.error(f"Option-chain error: {exc}")

    # Why surfaced / risks
    st.divider()
    reason_col, risk_col = st.columns(2)
    with reason_col:
        section_title("WHY IT SURFACED")
        for reason in selected.get("reasons", []):
            st.success(reason)
    with risk_col:
        section_title("RISK / VETO FLAGS")
        risks = selected.get("risks", [])
        if risks:
            for risk in risks:
                st.warning(risk)
        else:
            st.success("No current technical veto flags in the Stage-2 model.")

    st.caption(
        f"Universe: {len(universe)} F&O underlyings · Stage-2: {candidate_count} · "
        f"Updated: {datetime.now().strftime('%d-%b-%Y %H:%M:%S IST')} · "
        "Reference levels are mechanical research outputs, not investment advice."
    )


# -----------------------------------------------------------------------------
# F&O SCANNER — preserved as specialist view
# -----------------------------------------------------------------------------
elif page == "F&O Scanner":
    st.markdown('<div class="hero-title">F&O Universe Scanner</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">Broad universe ranking + Stage-2 15-minute technical validation.</div>', unsafe_allow_html=True)

    filter_mode = st.selectbox("View", ["All", "BUY", "SELL", "WATCH"])
    view = results if filter_mode == "All" else results[results["signal"] == filter_mode]
    render_signal_table(view, full=True)


# -----------------------------------------------------------------------------
# DEEP DIVE — preserved as specialist view
# -----------------------------------------------------------------------------
elif page == "Deep Dive":
    st.markdown('<div class="hero-title">Stock Deep Dive</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">Detailed technical view for one F&O underlying.</div>', unsafe_allow_html=True)

    symbols = universe["symbol"].dropna().sort_values().tolist()
    symbol = st.selectbox("Select F&O stock", symbols)
    row = universe[universe["symbol"] == symbol].iloc[0]
    sid = int(row["security_id"])
    timeframe = st.selectbox("Primary timeframe", ["5", "15", "60"], index=1)

    with st.spinner(f"Loading {symbol}…"):
        try:
            df = cached_stock_data(client, sid, interval=timeframe, days=60)
        except Exception as exc:
            st.error(str(exc))
            st.stop()

    if df.empty:
        st.warning("No candle data returned.")
        st.stop()

    df = add_indicators(df)
    last = df.iloc[-1]
    st.metric("Last Price", f"₹{last['close']:,.2f}")
    chart_df = df.tail(250).copy()
    st.line_chart(chart_df.set_index("timestamp")[["close", "ema20", "ema50", "ema200", "vwap"]])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("EMA20", f"{last['ema20']:,.2f}")
    c2.metric("EMA50", f"{last['ema50']:,.2f}")
    c3.metric("EMA200", f"{last['ema200']:,.2f}")
    c4.metric("RSI", f"{last['rsi']:.1f}")
    c5.metric("RVOL", f"{last['rvol']:.2f}x")

    section_title("Technical validation")
    checks = {
        "Price > EMA20": last["close"] > last["ema20"],
        "EMA20 > EMA50": last["ema20"] > last["ema50"],
        "EMA50 > EMA200": last["ema50"] > last["ema200"],
        "Price > VWAP": last["close"] > last["vwap"],
        "RSI > 50": last["rsi"] > 50,
        "RVOL > 1.5x": last["rvol"] > 1.5,
    }
    st.dataframe(
        pd.DataFrame([{"Parameter": k, "Pass": "✓" if v else "✕"} for k, v in checks.items()]),
        use_container_width=True,
        hide_index=True,
    )


# -----------------------------------------------------------------------------
# OPTION CHAIN — preserved as specialist view
# -----------------------------------------------------------------------------
elif page == "Option Chain":
    st.markdown('<div class="hero-title">Option Chain Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">Full option-chain workspace for manual deep research.</div>', unsafe_allow_html=True)

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
        c3.metric("Call Wall", f"{analysis['call_wall']:,.0f}" if analysis["call_wall"] else "—")
        c4.metric("Put Wall", f"{analysis['put_wall']:,.0f}" if analysis["put_wall"] else "—")
        render_option_chain(analysis["table"])
