"""Fetch the last 10 years of 1-minute bars for a list of tickers
from Alpaca and stream-upsert them into a Neon Postgres database.

Environment variables (set as GitHub Secrets in Actions):
    APCA_API_KEY_ID      - Alpaca API key (paper-trading keys work for market data)
    APCA_API_SECRET_KEY  - Alpaca API secret
    DATABASE_URL         - Neon connection string (use the pooled one)
    TICKERS_FILE         - Optional: path to tickers file (default: tickers.txt)
"""
import os
import time
from datetime import datetime, timedelta, timezone

import psycopg
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

TICKERS_FILE_DEFAULT = "tickers.txt"
LOOKBACK_YEARS = 10

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


def load_tickers(file_path: str = TICKERS_FILE_DEFAULT) -> list[str]:
    """Read stock tickers from a text file and return as a clean Python list.

    Supports:
      - One ticker per line
      - Comma or whitespace-separated tickers
      - Inline and full-line comments starting with '#'
      - Quoted ticker symbols (e.g., 'AAPL' or "MSFT")
    """
    if not os.path.exists(file_path):
        print(f"Warning: File '{file_path}' not found. Defaulting to ['AAPL'].")
        return ["AAPL"]

    tickers = []
    with open(file_path, "r") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            parts = line.replace(",", " ").split()
            for part in parts:
                clean_sym = part.strip("\"'").upper()
                if clean_sym and clean_sym not in tickers:
                    tickers.append(clean_sym)

    if not tickers:
        print(f"Warning: '{file_path}' contains no valid tickers. Defaulting to ['AAPL'].")
        return ["AAPL"]

    return tickers


def get_lookback_start(years: int = LOOKBACK_YEARS) -> datetime:
    """Calculate the start timestamp (midnight UTC) going back `years` calendar years."""
    end = datetime.now(timezone.utc)
    try:
        return end.replace(year=end.year - years, hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        # Handle leap day edge cases (e.g. Feb 29)
        return (end - timedelta(days=years * 365 + 3)).replace(hour=0, minute=0, second=0, microsecond=0)


def stream_fetch_and_upsert(
    client: StockHistoricalDataClient,
    symbol: str,
    start: datetime,
    end: datetime,
    conn: psycopg.Connection,
) -> int:
    """Fetch 1-minute bars page-by-page from Alpaca and immediately upsert each batch into Neon.

    Streaming page-by-page keeps memory consumption minimal and safely handles
    hundreds of thousands of 1-minute bars across the 10-year span.
    """
    current_start = start
    page_num = 1
    total_symbol_bars = 0

    while current_start < end:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=current_start,
            end=end,
            feed="iex",  # Free Alpaca plan -> IEX feed
            limit=10000,  # Max allowable batch size per API call
        )

        bar_set = client.get_stock_bars(request)

        # In alpaca-py, the dictionary of bars is under .data
        bars = []
        if hasattr(bar_set, "data") and symbol in bar_set.data:
            bars = bar_set.data[symbol]
        elif symbol in bar_set:
            bars = bar_set[symbol]

        if not bars:
            print(f"  Page {page_num:3d}: 0 bars returned. No further data available.")
            break

        rows = [
            (
                symbol,
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

        with conn.cursor() as cur:
            cur.executemany(UPSERT, rows)
        conn.commit()

        total_symbol_bars += len(rows)
        earliest_batch = bars[0].timestamp
        latest_batch = bars[-1].timestamp
        print(
            f"  Page {page_num:3d}: upserted {len(rows):5d} bars "
            f"({earliest_batch:%Y-%m-%d %H:%M} to {latest_batch:%Y-%m-%d %H:%M} UTC) "
            f"[Total: {total_symbol_bars:,}]"
        )

        # If Alpaca returned fewer than 10,000 bars, we have reached the end of the window
        if len(bars) < 10000:
            break

        # Advance current_start to strictly after the last bar's timestamp
        next_start = latest_batch + timedelta(seconds=1)
        if next_start <= current_start:
            break

        current_start = next_start
        page_num += 1
        time.sleep(0.3)

    return total_symbol_bars


def main():
    api_key = os.environ["APCA_API_KEY_ID"]
    api_secret = os.environ["APCA_API_SECRET_KEY"]
    database_url = os.environ["DATABASE_URL"]
    tickers_file = os.environ.get("TICKERS_FILE", TICKERS_FILE_DEFAULT)

    # 1. Load tickers
    tickers = load_tickers(tickers_file)
    print(f"Loaded {len(tickers)} ticker(s) from '{tickers_file}': {tickers}")

    # 2. Date window: 10 years of 1-minute bars
    client = StockHistoricalDataClient(api_key, api_secret)
    end = datetime.now(timezone.utc)
    start = get_lookback_start(years=LOOKBACK_YEARS)
    print(f"Window: {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC ({LOOKBACK_YEARS} years, 1-minute interval)\n")

    # 3. Connect to Neon and process tickers
    print("Connecting to Neon database...")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()

        grand_total = 0
        for symbol in tickers:
            print(f"[{symbol}] Starting 10-year 1-minute bar extraction...")
            t0 = time.time()
            try:
                upserted = stream_fetch_and_upsert(client, symbol, start, end, conn)
                grand_total += upserted
                elapsed = time.time() - t0
                print(f"[{symbol}] Complete: {upserted:,} total bars upserted in {elapsed:.1f}s.\n")
            except Exception as e:
                print(f"[{symbol}] Error fetching/storing data: {e}\n")

    print(f"Finished! Total 1-minute bars upserted across all tickers: {grand_total:,}")


if __name__ == "__main__":
    main()
