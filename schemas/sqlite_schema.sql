-- Temple Flow local market store (SQLite)
-- Owner: Data & Backfill. No invented rows. All loads must write provenance.
-- Revised after Data & Backfill schema review (2026-08-22).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS universe (
  symbol        TEXT PRIMARY KEY,
  asset_class   TEXT NOT NULL,          -- equity|etf|index|fx|future|other
  active        INTEGER NOT NULL DEFAULT 1,
  notes         TEXT,
  added_at_utc  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_provenance (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_name   TEXT NOT NULL,          -- e.g. goldbrick, schwab, yahoo, csv_import
  source_uri    TEXT,                   -- path or API endpoint descriptor (no secrets)
  pulled_at_utc TEXT NOT NULL,
  as_of_utc     TEXT,                   -- data vintage if different from pull time
  checksum      TEXT,                   -- optional content hash
  row_count     INTEGER,
  notes         TEXT
);

-- NYSE/Nasdaq-style expected sessions for America/New_York gap reports
CREATE TABLE IF NOT EXISTS trading_calendar (
  session_date  TEXT PRIMARY KEY,       -- YYYY-MM-DD America/New_York session label
  is_open       INTEGER NOT NULL,       -- 1=regular session, 0=holiday/closed
  session_label TEXT,                   -- regular|early_close|holiday
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS bars_daily (
  symbol        TEXT NOT NULL REFERENCES universe(symbol),
  session_date  TEXT NOT NULL,          -- YYYY-MM-DD in America/New_York session terms
  open          REAL NOT NULL,
  high          REAL NOT NULL,
  low           REAL NOT NULL,
  close         REAL NOT NULL,
  adj_close     REAL,                   -- split/dividend adjusted close when source provides
  volume        REAL,
  split_factor  REAL,                   -- cumulative or per-bar factor if known
  dividend      REAL,                   -- cash dividend on this session if any
  adjust_method TEXT,                   -- e.g. source_adj|none|manual_v1
  provenance_id INTEGER NOT NULL REFERENCES data_provenance(id),
  PRIMARY KEY (symbol, session_date)
);

CREATE TABLE IF NOT EXISTS bars_intraday (
  symbol        TEXT NOT NULL REFERENCES universe(symbol),
  ts_utc        TEXT NOT NULL,          -- ISO-8601 UTC bar open
  timeframe     TEXT NOT NULL,          -- e.g. 1m, 5m, 15m, 1h
  open          REAL NOT NULL,
  high          REAL NOT NULL,
  low           REAL NOT NULL,
  close         REAL NOT NULL,
  volume        REAL,
  provenance_id INTEGER NOT NULL REFERENCES data_provenance(id),
  PRIMARY KEY (symbol, ts_utc, timeframe)
);

-- Canonical indicator names (enforce consistency for Risk ATR filter etc.)
-- Allowed names include at least:
--   RSI_14, MACD, MACD_SIGNAL, MACD_HIST,
--   BB_UPPER, BB_MID, BB_LOWER,
--   SMA_20, SMA_50, SMA_200, EMA_12, EMA_26,
--   ATR_14, ATR_60D_AVG, ATR_RATIO_14_60
CREATE TABLE IF NOT EXISTS indicator_catalog (
  name          TEXT PRIMARY KEY,
  description   TEXT NOT NULL,
  required_for_risk INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS indicators_daily (
  symbol        TEXT NOT NULL,
  session_date  TEXT NOT NULL,
  name          TEXT NOT NULL REFERENCES indicator_catalog(name),
  value         REAL NOT NULL,
  params_json   TEXT,                   -- deterministic params used
  provenance_id INTEGER NOT NULL REFERENCES data_provenance(id),
  PRIMARY KEY (symbol, session_date, name),
  FOREIGN KEY (symbol, session_date) REFERENCES bars_daily(symbol, session_date)
);

CREATE TABLE IF NOT EXISTS regimes (
  symbol        TEXT NOT NULL REFERENCES universe(symbol),
  as_of_date    TEXT NOT NULL,          -- session date label computed
  label         TEXT NOT NULL,          -- e.g. trend_up, range, high_vol, crash
  method        TEXT NOT NULL,          -- algorithm id/version
  score         REAL,
  details_json  TEXT,
  provenance_id INTEGER NOT NULL REFERENCES data_provenance(id),
  PRIMARY KEY (symbol, as_of_date, method)
);

CREATE TABLE IF NOT EXISTS macro_series (
  series_id     TEXT NOT NULL,          -- DXY, VIX, US10Y, ...
  session_date  TEXT NOT NULL,
  value         REAL NOT NULL,
  provenance_id INTEGER NOT NULL REFERENCES data_provenance(id),
  PRIMARY KEY (series_id, session_date)
);

-- News / narrative / X-NLP artifacts for Macro Sentiment packages
CREATE TABLE IF NOT EXISTS news_items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc        TEXT NOT NULL,
  source        TEXT NOT NULL,          -- reuters|bloomberg|x|other
  headline      TEXT,
  url           TEXT,
  symbols_json  TEXT,                   -- optional related symbols
  raw_ref       TEXT,                   -- pointer to stored raw payload (no secrets)
  provenance_id INTEGER NOT NULL REFERENCES data_provenance(id)
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_utc     TEXT NOT NULL,
  scope         TEXT NOT NULL,          -- market|symbol|theme
  scope_key     TEXT,                   -- symbol or theme id when applicable
  score         REAL,
  label         TEXT,
  method        TEXT NOT NULL,          -- model/version
  details_json  TEXT,
  provenance_id INTEGER NOT NULL REFERENCES data_provenance(id)
);

CREATE TABLE IF NOT EXISTS backfill_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at_utc TEXT NOT NULL,
  finished_at_utc TEXT,
  status        TEXT NOT NULL,          -- running|ok|failed|partial
  universe_json TEXT,
  date_start    TEXT,
  date_end      TEXT,
  rows_written  INTEGER,
  gaps_json     TEXT,                   -- structured gap report (holiday vs missing)
  provenance_ids_json TEXT,             -- list of data_provenance.id written in this run
  notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_bars_daily_date ON bars_daily(session_date);
CREATE INDEX IF NOT EXISTS idx_indicators_name ON indicators_daily(name, session_date);
CREATE INDEX IF NOT EXISTS idx_regimes_label ON regimes(label, as_of_date);
CREATE INDEX IF NOT EXISTS idx_news_ts ON news_items(ts_utc);
CREATE INDEX IF NOT EXISTS idx_sentiment_asof ON sentiment_scores(as_of_utc);

-- Seed canonical indicator names (idempotent)
INSERT OR IGNORE INTO indicator_catalog(name, description, required_for_risk) VALUES
 ('RSI_14', '14-period Relative Strength Index', 0),
 ('MACD', 'MACD line', 0),
 ('MACD_SIGNAL', 'MACD signal line', 0),
 ('MACD_HIST', 'MACD histogram', 0),
 ('BB_UPPER', 'Bollinger upper', 0),
 ('BB_MID', 'Bollinger mid', 0),
 ('BB_LOWER', 'Bollinger lower', 0),
 ('SMA_20', '20-session SMA', 0),
 ('SMA_50', '50-session SMA', 0),
 ('SMA_200', '200-session SMA', 0),
 ('EMA_12', '12-session EMA', 0),
 ('EMA_26', '26-session EMA', 0),
 ('ATR_14', '14-period Average True Range', 1),
 ('ATR_60D_AVG', '60-session average of ATR_14', 1),
 ('ATR_RATIO_14_60', 'ATR_14 / ATR_60D_AVG (Risk filter if > 1.8)', 1);
