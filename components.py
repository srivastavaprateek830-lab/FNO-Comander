import streamlit as st


def inject_css():
    st.markdown(
        """
        <style>
        .stApp {
            background: #071018;
            color: #E8EEF4;
        }
        [data-testid="stSidebar"] {
            background: #050B11;
        }
        div[data-testid="metric-container"] {
            background: #0B151E;
            border: 1px solid #1A2A36;
            border-radius: 10px;
            padding: 10px;
        }
        .signal-box {
            padding: 18px;
            border-radius: 12px;
            background: #0B151E;
            border: 1px solid #1A2A36;
            text-align: center;
        }
        .signal-buy {
            color: #42E695;
            font-size: 30px;
            font-weight: 800;
        }
        .signal-sell {
            color: #FF5C6C;
            font-size: 30px;
            font-weight: 800;
        }
        .signal-watch {
            color: #F4C95D;
            font-size: 30px;
            font-weight: 800;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def signal_badge(signal, score):
    cls = {
        "BUY": "signal-buy",
        "SELL": "signal-sell",
    }.get(signal, "signal-watch")

    st.markdown(
        f"""
        <div class="signal-box">
            <div class="{cls}">{signal}</div>
            <div>Conviction {score}/100</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label, value, delta=None):
    st.metric(label, value, delta)


def render_signal_table(df, full=False):
    if df.empty:
        st.info("No signals.")
        return

    view = df.copy()

    if not full:
        view = view.head(10)

    display_cols = [
        c for c in [
            "symbol", "signal", "score", "price",
            "rvol", "rsi", "atr", "priority"
        ] if c in view.columns
    ]

    view = view[display_cols].copy()
    view.columns = [c.upper() for c in view.columns]

    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
    )


def render_option_chain(df):
    if df.empty:
        st.info("No option-chain rows.")
        return

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )
