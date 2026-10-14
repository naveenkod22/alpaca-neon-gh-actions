"""Fetch the last 7 trading days of 1-minute bars for a list of tickers
from Alpaca and upsert them into a Neon Postgres database.

Environment variables (set as GitHub Secrets in Actions):
    APCA_API_KEY_ID      - Alpaca API key (paper-trading keys work for market data)
    APCA_API_SECRET_KEY  - Alpaca API secret
    DATABASE_URL         - Neon connection string (use the pooled one)
    TICKERS_FILE         - Optional: path to tickers file (default: tickers.txt)
"""
import os
from datetime import datetime, timedelta, timezone

import psycopg
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

TICKERS_FILE_DEFAULT = "tickers.txt"
TRADING_DAYS_LOOKBACK = 7

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
            # Strip inline comments
            line = line.split("#")[0].strip()
            if not line:
                continue
            # Handle comma or whitespace separated tokens
            parts = line.replace(",", " ").split()
            for part in parts:
                clean_sym = part.strip("\"'").upper()
                if clean_sym and clean_sym not in tickers:
                    tickers.append(clean_sym)

    if not tickers:
        print(f"Warning: '{file_path}' contains no valid tickers. Defaulting to ['AAPL'].")
        return ["AAPL"]

    return tickers


def get_trading_days_start(num_trading_days: int = TRADING_DAYS_LOOKBACK) -> datetime:
    """Calculate the start timestamp (midnight UTC) covering the last `num_trading_days` weekdays."""
    current = datetime.now(timezone.utc)
    trading_days = 0
    cursor = current
    while trading_days < num_trading_days:
        cursor -= timedelta(days=1)
        if cursor.weekday() < 5:  # Monday through Friday
            trading_days += 1
    # Start from midnight UTC of that day to encompass the full trading session
    return cursor.replace(hour=0, minute=0, second=0, microsecond=0)


def fetch_bars(client: StockHistoricalDataClient, symbol: str, start: datetime, end: datetime):
    """Fetch all 1-minute bars for a symbol between start and end with pagination."""
    all_bars = []
    page_token = None

    while True:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed="iex",  # Free Alpaca plan -> IEX feed
            limit=10000,
            page_token=page_token,
        )
        bar_set = client.get_stock_bars(request)

        # In alpaca-py, the dictionary of bars keyed by ticker is at .data
        bars = []
        if hasattr(bar_set, "data") and symbol in bar_set.data:
            bars = bar_set.data[symbol]
        elif symbol in bar_set:
            bars = bar_set[symbol]

        all_bars.extend(bars)
        print(f"  Fetched batch: {len(bars)} bars (page_token={page_token})")

        page_token = getattr(bar_set, "next_page_token", None)
        if not page_token:
            break

    return all_bars


def main():
    api_key = os.environ["APCA_API_KEY_ID"]
    api_secret = os.environ["APCA_API_SECRET_KEY"]
    database_url = os.environ["DATABASE_URL"]
    tickers_file = os.environ.get("TICKERS_FILE", TICKERS_FILE_DEFAULT)

    # 1. Load tickers from file into a Python list
    tickers = load_tickers(tickers_file)
    print(f"Loaded {len(tickers)} ticker(s) from '{tickers_file}': {tickers}")

    # 2. Compute the 7 trading days time range
    client = StockHistoricalDataClient(api_key, api_secret)
    end = datetime.now(timezone.utc)
    start = get_trading_days_start(num_trading_days=TRADING_DAYS_LOOKBACK)
    print(f"Time window: {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC ({TRADING_DAYS_LOOKBACK} trading days)\n")

    # 3. Connect to Neon and process each ticker
    print("Connecting to Neon database...")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()

        total_upserted = 0
        for symbol in tickers:
            print(f"[{symbol}] Fetching data...")
            try:
                bars = fetch_bars(client, symbol, start, end)
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

                if rows:
                    with conn.cursor() as cur:
                        cur.executemany(UPSERT, rows)
                    conn.commit()
                    total_upserted += len(rows)
                    print(f"[{symbol}] Successfully upserted {len(rows)} bars into Neon.\n")
                else:
                    print(f"[{symbol}] No bars returned for the given window.\n")

            except Exception as e:
                print(f"[{symbol}] Error fetching or storing data: {e}\n")

    print(f"Finished! Total bars upserted across all {len(tickers)} ticker(s): {total_upserted}")


if __name__ == "__main__":
    main()
