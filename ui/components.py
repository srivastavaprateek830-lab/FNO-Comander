import streamlit as st


def inject_css():
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
        [data-testid="stSidebar"] { border-right: 1px solid rgba(255,255,255,.08); }
        .hero-title { font-size: 2.15rem; font-weight: 800; letter-spacing: -.03em; margin-bottom: .15rem; }
        .hero-sub { color: #8d99a8; margin-bottom: 1.1rem; }
        .section-title { font-size: 1.35rem; font-weight: 750; margin: .9rem 0 .55rem; }
        .tiny { color: #8d99a8; font-size: .78rem; }
        .panel { background: #0b141d; border: 1px solid rgba(255,255,255,.08); border-radius: 12px; padding: 14px 16px; }
        .signal-buy { color: #35e58a; font-weight: 850; font-size: 1.55rem; }
        .signal-sell { color: #ff6675; font-weight: 850; font-size: 1.55rem; }
        .signal-watch { color: #f4c95d; font-weight: 850; font-size: 1.55rem; }
        .score { font-size: 2.1rem; font-weight: 800; }
        .score-label { color: #8d99a8; font-size: .8rem; }
        .pill { display:inline-block; padding:4px 9px; border-radius:999px; font-size:.74rem; font-weight:700; }
        .pill-green { background: rgba(53,229,138,.13); color:#35e58a; }
        .pill-red { background: rgba(255,102,117,.13); color:#ff6675; }
        .pill-yellow { background: rgba(244,201,93,.13); color:#f4c95d; }
        .check { color:#35e58a; font-weight:700; }
        .cross { color:#ff6675; font-weight:700; }
        .divider { height:1px; background:rgba(255,255,255,.08); margin: 1rem 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def section_title(title, subtitle=None):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="tiny">{subtitle}</div>', unsafe_allow_html=True)


def signal_badge(signal, score):
    cls = {"BUY": "signal-buy", "SELL": "signal-sell"}.get(signal, "signal-watch")
    st.markdown(
        f'<div class="panel"><div class="{cls}">{signal}</div>'
        f'<div class="score">{int(score)}/100</div>'
        f'<div class="score-label">Conviction score</div></div>',
        unsafe_allow_html=True,
    )


def regime_badge(label, score):
    cls = "pill-green" if "BULL" in label else "pill-red" if "BEAR" in label else "pill-yellow"
    st.markdown(
        f'<span class="pill {cls}">{label} · {int(score)}/100</span>',
        unsafe_allow_html=True,
    )


def render_signal_table(view, full=False):
    if view is None or view.empty:
        st.info("No qualifying setups.")
        return

    cols = [
        c for c in [
            "symbol", "signal", "score", "price", "rvol", "rsi", "atr", "priority"
        ] if c in view.columns
    ]
    display = view[cols].copy()
    rename = {
        "symbol": "SYMBOL", "signal": "SIGNAL", "score": "SCORE",
        "price": "PRICE", "rvol": "RVOL", "rsi": "RSI",
        "atr": "ATR", "priority": "PRIORITY",
    }
    display = display.rename(columns=rename)
    if "PRICE" in display:
        display["PRICE"] = display["PRICE"].map(lambda x: f"₹{x:,.2f}")
    if "RVOL" in display:
        display["RVOL"] = display["RVOL"].map(lambda x: f"{x:.2f}x")
    if "RSI" in display:
        display["RSI"] = display["RSI"].map(lambda x: f"{x:.1f}")
    if "ATR" in display:
        display["ATR"] = display["ATR"].map(lambda x: f"{x:.2f}")

    st.dataframe(display, use_container_width=True, hide_index=True)


def render_mtf_table(rows):
    if not rows:
        st.info("MTF data unavailable.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_option_chain(df):
    if df is None or df.empty:
        st.info("No option-chain rows.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)
