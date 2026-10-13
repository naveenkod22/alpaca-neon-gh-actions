"""Fetch the last 7 days of AAPL 1-minute bars from Alpaca and upsert them
into a Neon Postgres database.

Environment variables (set as GitHub Secrets in Actions):
    APCA_API_KEY_ID      - Alpaca API key (paper-trading keys work for market data)
    APCA_API_SECRET_KEY  - Alpaca API secret
    DATABASE_URL         - Neon connection string (use the pooled one)
"""
import os
from datetime import datetime, timedelta, timezone

import psycopg
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

SYMBOL = "AAPL"
LOOKBACK_DAYS = 7

DDL = """
CREATE TABLE IF NOT EXISTS stock_bars (
    symbol      TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT,
    trade_count BIGINT,
    vwap        DOUBLE PRECISION,
    PRIMARY KEY (symbol, ts)
);
"""

UPSERT = """
INSERT INTO stock_bars
    (symbol, ts, open, high, low, close, volume, trade_count, vwap)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (symbol, ts) DO UPDATE SET
    open        = EXCLUDED.open,
    high        = EXCLUDED.high,
    low         = EXCLUDED.low,
    close       = EXCLUDED.close,
    volume      = EXCLUDED.volume,
    trade_count = EXCLUDED.trade_count,
    vwap        = EXCLUDED.vwap;
"""


def fetch_bars(client, symbol, start, end):
    all_bars = []
    page_token = None
    while True:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed="iex",  # free Alpaca plan -> IEX feed (SIP needs a paid subscription)
            limit=10000,
            page_token=page_token,
        )
        bar_set = client.get_stock_bars(request)

        # In alpaca-py, bar_set is a BarSet model whose bars dictionary is at .data.
        # Checking 'symbol in bar_set' checks model fields, which returns False.
        # We must inspect bar_set.data directly:
        bars = []
        if hasattr(bar_set, "data") and symbol in bar_set.data:
            bars = bar_set.data[symbol]
        elif symbol in bar_set:
            bars = bar_set[symbol]

        all_bars.extend(bars)
        print(f"Fetched batch: {len(bars)} bars for {symbol} (page_token={page_token})")

        page_token = getattr(bar_set, "next_page_token", None)
        if not page_token:
            break
    return all_bars


def main():
    api_key = os.environ["APCA_API_KEY_ID"]
    api_secret = os.environ["APCA_API_SECRET_KEY"]
    database_url = os.environ["DATABASE_URL"]

    client = StockHistoricalDataClient(api_key, api_secret)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    print(f"Querying Alpaca for {SYMBOL} from {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC...")
    bars = fetch_bars(client, SYMBOL, start, end)
    print(f"Total bars fetched from Alpaca: {len(bars)}")

    rows = [
        (
            SYMBOL,
            bar.timestamp,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.trade_count,
            bar.vwap,
        )
        for bar in bars
    ]

    print(f"Connecting to Neon database...")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            if rows:
                print(f"Upserting {len(rows)} bars into stock_bars table...")
                cur.executemany(UPSERT, rows)
            else:
                print("No rows to upsert.")
        conn.commit()

    print(f"Successfully upserted {len(rows)} one-minute bars for {SYMBOL} "
          f"({start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC)")


if __name__ == "__main__":
    main()
