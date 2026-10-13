"""Fetch the last 10 minutes of AAPL 1-minute bars from Alpaca and upsert them
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
LOOKBACK_MINUTES = 10

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
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed="iex",  # free Alpaca plan -> IEX feed (SIP needs a paid subscription)
    )
    bar_set = client.get_stock_bars(request)
    return list(bar_set[symbol])


def main():
    api_key = os.environ["APCA_API_KEY_ID"]
    api_secret = os.environ["APCA_API_SECRET_KEY"]
    database_url = os.environ["DATABASE_URL"]

    client = StockHistoricalDataClient(api_key, api_secret)

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=LOOKBACK_MINUTES)
    bars = fetch_bars(client, SYMBOL, start, end)

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

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            if rows:
                cur.executemany(UPSERT, rows)
        conn.commit()

    print(f"Upserted {len(rows)} one-minute bars for {SYMBOL} "
          f"({start:%H:%M}–{end:%H:%M} UTC)")


if __name__ == "__main__":
    main()
