# AAPL → Neon via GitHub Actions

Fetch the last 7 days of AAPL 1-minute bars from Alpaca and upsert them into
a Neon Postgres database via GitHub Actions.

## How it works

1. GitHub Actions runs on schedule or manual trigger, spins up a fresh Ubuntu runner,
   and checks out this repo.
2. `fetch_aapl.py` pulls 1-minute AAPL bars from Alpaca for the last 7 days
   (`feed="iex"` — free plan feed; with pagination support up to 10,000 bars per page)
   and upserts them into the `stock_bars` table (primary key on `(symbol, ts)`, so
   re-runs never duplicate).
3. The table is created automatically on first run; `schema.sql` is the same DDL
   for manual use in Neon's SQL editor.

Outside market hours there are no new bars — the script just upserts 0 rows and
exits cleanly.

## Setup (5 minutes)

1. **Neon**: create a free project at neon.com → copy the connection string.
   Use the **pooled** connection string (hostname contains `-pooler`) — it's
   built for short-lived connections like this. No card required.
2. **Alpaca**: paper-trading API keys work for market data. Generate them at
   app.alpaca.markets → "Your API keys".
3. **GitHub**: create a repo, push these files to the **default branch**
   (scheduled workflows only run there). Then go to
   Settings → Secrets and variables → Actions → New repository secret, and add:
   - `APCA_API_KEY_ID`
   - `APCA_API_SECRET_KEY`
   - `DATABASE_URL`
4. **Test now**: Actions tab → "fetch-aapl" → "Run workflow" → watch the log.
   You should see `Upserted N one-minute bars for AAPL`.
5. **Verify in Neon**: SQL editor → `SELECT * FROM stock_bars ORDER BY ts DESC LIMIT 20;`

## Files

| File | What it is |
|---|---|
| `fetch_aapl.py` | The whole job: fetch bars → upsert to Postgres |
| `requirements.txt` | `alpaca-py`, `psycopg[binary]` |
| `schema.sql` | Table DDL (also auto-created by the script) |
| `.github/workflows/fetch-aapl.yml` | The schedule: every 10 min + manual trigger |

## Cost

$0. GitHub Actions is free for public repos (2,000 min/mo for private), Neon
has a free tier, Alpaca paper keys + IEX feed are free.
