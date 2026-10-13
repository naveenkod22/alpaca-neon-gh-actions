-- Table for 1-minute stock bars. Also created automatically by fetch_aapl.py
-- on first run; this file is for manual setup / inspection in Neon's SQL editor.
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
