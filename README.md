# Multi-Ticker Stock Data → Neon via GitHub Actions

Fetch the last 7 trading days of 1-minute bars for a list of tickers from Alpaca
and upsert them into a Neon Postgres database via GitHub Actions.

## How it works

1. GitHub Actions runs on schedule or manual trigger, spins up an Ubuntu runner,
   and checks out this repo.
2. `fetch_aapl.py` loads tickers from `tickers.txt` as a Python list.
3. For each ticker, it pulls 1-minute bars from Alpaca for the last 7 trading days
   (`feed="iex"` — free plan feed; with pagination support up to 10,000 bars per page)
   and upserts them into the `stock_bars` table (primary key on `(symbol, ts)`, so
   re-runs never duplicate).
4. The table is created automatically on first run; `schema.sql` is the same DDL
   for manual inspection in Neon's SQL editor.

## Setup (5 minutes)

1. **Neon**: create a free project at neon.com → copy the pooled connection string.
2. **Alpaca**: paper-trading API keys work for market data (app.alpaca.markets).
3. **Tickers**: edit `tickers.txt` with your desired stock symbols (one per line).
4. **GitHub Secrets**: in repo Settings → Secrets and variables → Actions:
   - `APCA_API_KEY_ID`
   - `APCA_API_SECRET_KEY`
   - `DATABASE_URL`
5. **Test**: Actions tab → "fetch-aapl" → "Run workflow".
6. **Verify in Neon**:
   ```sql
   SELECT symbol, ts::DATE AS trade_date, COUNT(*)
   FROM stock_bars
   GROUP BY symbol, ts::DATE
   ORDER BY symbol, trade_date DESC;
   ```

## Files

| File | What it is |
|---|---|
| `fetch_aapl.py` | The whole job: read tickers → fetch 7 trading days → upsert to Neon |
| `tickers.txt` | List of tickers to fetch (e.g. `AAPL`, `MSFT`, `NVDA`) |
| `requirements.txt` | `alpaca-py`, `psycopg[binary]` |
| `schema.sql` | Table DDL (also auto-created by the script) |
| `.github/workflows/fetch-aapl.yml` | The workflow: runs on schedule + manual trigger |

## Cost

$0. GitHub Actions is free for public repos (2,000 min/mo for private), Neon
has a free tier, Alpaca paper keys + IEX feed are free.
