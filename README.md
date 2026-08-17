# FNO COMMANDER

Personal Indian F&O research and high-conviction alert terminal built with:

- DhanHQ API
- Python
- Streamlit
- GitHub
- Streamlit Community Cloud

## What V1 does

1. Loads the current Dhan instrument master.
2. Derives the NSE stock F&O universe from stock futures.
3. Gets a broad market-quote snapshot.
4. Uses movement + liquidity to create a Stage-2 candidate list.
5. Validates candidates on 15-minute candles.
6. Calculates:
   - EMA20 / EMA50 / EMA200
   - RSI
   - ATR
   - VWAP
   - Relative volume
   - SuperTrend direction
   - MACD
7. Produces BUY / SELL / WATCH scores.
8. Provides a stock deep-dive page.
9. Provides on-demand option-chain analysis:
   - PCR
   - Call OI wall
   - Put OI wall
   - OI change
   - IV
   - Delta
10. Has no order-placement code.

## Important architecture

The app intentionally does NOT request option chains for the entire F&O universe.

Broad universe:
F&O stocks -> market quote -> Stage 2 candidates -> technical validation -> option chain on demand.

This keeps API usage practical and respects Dhan's option-chain request limit.

## GitHub deployment

Create a repository and upload the repository files.

Minimum structure:

fno-commander/
  app.py
  requirements.txt
  data/
  indicators/
  engine/
  options/
  ui/
  .streamlit/config.toml
  .streamlit/secrets.toml.example

Do NOT upload `.streamlit/secrets.toml`.

## Streamlit secrets

In Streamlit Community Cloud, open:

App -> Settings -> Secrets

Paste:

DHAN_CLIENT_ID = "your_client_id"
DHAN_ACCESS_TOKEN = "your_access_token"

## Run

Streamlit Community Cloud entrypoint:

app.py

## No trading execution

This V1 is deliberately signal/research only.

Future modules can add:
- futures OI confirmation
- sector strength
- market breadth
- multi-timeframe confirmation
- trade setup engine
- BTST radar
- trade journal
- historical signal evaluation
- Telegram/email/browser alerts
- Dhan websocket live feed

Do not add order APIs until the signal engine has been validated.
