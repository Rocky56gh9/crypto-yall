"""
backtest/data_fetch.py — Assemble and cache intraday + daily history.

Sources
-------
- Hyperliquid mainnet candleSnapshot (same request shape as
  intraday_data_loader.fetch_candles). The endpoint only serves the most
  recent 5000 candles per coin/interval (~208 days at 1h, ~104 days at 30m),
  so paging backwards stops returning data past that horizon.
- Binance USDT-M perpetual klines (public, no auth) for the multi-year
  history the Hyperliquid endpoint cannot provide. Perp-to-perp is the
  closest available proxy; the overlap with Hyperliquid is validated in
  coverage.csv / proxy_validation.csv.
- Daily: data_loader.fetch_data (yfinance, anchored 2022-03-01).

Everything is cached under backtest/data/ as parquet; reruns read the cache.
Run:  backtest/.venv/bin/python backtest/data_fetch.py [--refresh]
"""

import os
import sys
import time

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from intraday_data_loader import HL_CANDLE_URL, HL_SYMBOL_MAP  # noqa: E402

DATA_DIR = os.path.join(HERE, "data")
RESULTS_DIR = os.path.join(HERE, "results")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

TICKERS = list(HL_SYMBOL_MAP.keys())
INTERVALS = {"30m": 30, "1h": 60}
BINANCE_URL = "https://fapi.binance.com/fapi/v1/klines"
BINANCE_SYMBOL = {t: f"{c}USDT" for t, c in HL_SYMBOL_MAP.items()}
HIST_START = pd.Timestamp("2023-01-01")


def _to_frame(rows, ts_key, cols):
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df[ts_key].astype("int64"), unit="ms")
    df = df.rename(columns=cols)[["Date", "Open", "High", "Low", "Close", "Volume"]]
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        df[c] = df[c].astype(float)
    return df.set_index("Date").sort_index()


def fetch_hyperliquid(coin: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Page backwards in 5000-candle windows until the endpoint returns nothing."""
    step = pd.Timedelta(minutes=INTERVALS[interval] * 5000)
    frames, win_end = [], end
    while win_end > start:
        win_start = max(start, win_end - step)
        body = {"type": "candleSnapshot", "req": {
            "coin": coin, "interval": interval,
            "startTime": int(win_start.value // 1e6), "endTime": int(win_end.value // 1e6)}}
        for attempt in range(4):
            try:
                resp = requests.post(HL_CANDLE_URL, json=body, timeout=30)
                if resp.status_code == 200:
                    rows = resp.json()
                    break
            except requests.RequestException as e:
                print(f"  HL {coin} {interval} retry {attempt + 1}: {e}")
            time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"Hyperliquid fetch failed for {coin} {interval}")
        if not rows:
            break  # past the 5000-candle retention horizon
        frames.append(_to_frame(rows, "t", {"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"}))
        win_end = win_start
        time.sleep(0.3)
    if not frames:
        return _to_frame([], "t", {})
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="last")]


def fetch_binance(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Page forward 1500 klines at a time."""
    frames, cursor = [], int(start.value // 1e6)
    end_ms = int(end.value // 1e6)
    while cursor < end_ms:
        params = {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": 1500}
        for attempt in range(4):
            try:
                resp = requests.get(BINANCE_URL, params=params, timeout=30)
                if resp.status_code == 200:
                    rows = resp.json()
                    break
                print(f"  Binance {symbol} HTTP {resp.status_code}: {resp.text[:120]}")
            except requests.RequestException as e:
                print(f"  Binance {symbol} retry {attempt + 1}: {e}")
            time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"Binance fetch failed for {symbol} {interval}")
        if not rows:
            break
        cols = ["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tb", "tq", "ig"]
        rows = [dict(zip(cols, r)) for r in rows]
        frames.append(_to_frame(rows, "t", {"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"}))
        nxt = int(rows[-1]["t"]) + INTERVALS[interval] * 60_000
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(0.15)
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="last")]


def drop_open_bar(df: pd.DataFrame, interval: str, now: pd.Timestamp) -> pd.DataFrame:
    """Remove the still-forming candle so every cached bar is complete."""
    bar = pd.Timedelta(minutes=INTERVALS[interval])
    return df[df.index + bar <= now]


def cache_path(source: str, ticker: str, interval: str) -> str:
    return os.path.join(DATA_DIR, f"{source}_{HL_SYMBOL_MAP.get(ticker, ticker)}_{interval}.parquet")


def load_intraday(source: str, ticker: str, interval: str) -> pd.DataFrame:
    return pd.read_parquet(cache_path(source, ticker, interval))


def load_daily() -> dict[str, pd.DataFrame]:
    out = {}
    for t in TICKERS:
        p = os.path.join(DATA_DIR, f"daily_{HL_SYMBOL_MAP[t]}.parquet")
        out[t] = pd.read_parquet(p)
    return out


def coverage_row(source, ticker, interval, df) -> dict:
    bar = pd.Timedelta(minutes=INTERVALS[interval])
    if df.empty:
        return {"source": source, "coin": HL_SYMBOL_MAP.get(ticker, ticker), "interval": interval, "bars": 0}
    idx = df.index
    full = pd.date_range(idx[0], idx[-1], freq=bar)
    diffs = pd.Series(idx[1:] - idx[:-1])
    gaps = diffs[diffs > bar]
    bad_ohlc = int(((df["High"] < df[["Open", "Close"]].max(axis=1)) |
                    (df["Low"] > df[["Open", "Close"]].min(axis=1))).sum())
    return {
        "source": source, "coin": HL_SYMBOL_MAP.get(ticker, ticker), "interval": interval,
        "first": idx[0], "last": idx[-1], "days": round((idx[-1] - idx[0]) / pd.Timedelta(days=1), 1),
        "bars": len(df), "expected_bars": len(full),
        "missing_bars": len(full) - len(idx), "gap_events": len(gaps),
        "largest_gap_h": round(gaps.max() / pd.Timedelta(hours=1), 1) if len(gaps) else 0.0,
        "duplicates": int(idx.duplicated().sum()), "zero_volume_bars": int((df["Volume"] == 0).sum()),
        "bad_ohlc": bad_ohlc,
    }


def proxy_validation(ticker, interval) -> dict:
    """Compare Binance perp vs Hyperliquid perp on their overlapping window."""
    hl = load_intraday("hl", ticker, interval)
    bn = load_intraday("binance", ticker, interval)
    j = hl[["Close", "High", "Low"]].join(bn[["Close", "High", "Low"]], lsuffix="_hl", rsuffix="_bn", how="inner")
    if len(j) < 50:
        return {"coin": HL_SYMBOL_MAP[ticker], "interval": interval, "overlap_bars": len(j)}
    r_hl = np.log(j["Close_hl"]).diff()
    r_bn = np.log(j["Close_bn"]).diff()
    basis = (j["Close_hl"] / j["Close_bn"] - 1) * 1e4
    rng_hl = (j["High_hl"] - j["Low_hl"]) / j["Close_hl"]
    rng_bn = (j["High_bn"] - j["Low_bn"]) / j["Close_bn"]
    return {
        "coin": HL_SYMBOL_MAP[ticker], "interval": interval, "overlap_bars": len(j),
        "overlap_start": j.index[0], "overlap_end": j.index[-1],
        "return_corr": round(float(r_hl.corr(r_bn)), 4),
        "median_abs_basis_bps": round(float(basis.abs().median()), 2),
        "p99_abs_basis_bps": round(float(basis.abs().quantile(0.99)), 2),
        "hl_range_over_bn_range": round(float(rng_hl.mean() / rng_bn.mean()), 3),
    }


def main(refresh: bool = False):
    now = pd.Timestamp.utcnow().tz_localize(None)
    rows = []
    for t in TICKERS:
        coin = HL_SYMBOL_MAP[t]
        for iv in INTERVALS:
            for source in ("hl", "binance"):
                p = cache_path(source, t, iv)
                if refresh or not os.path.exists(p):
                    print(f"Fetching {source} {coin} {iv} ...")
                    if source == "hl":
                        df = fetch_hyperliquid(coin, iv, now - pd.Timedelta(days=760), now)
                    else:
                        df = fetch_binance(BINANCE_SYMBOL[t], iv, HIST_START, now)
                    df = drop_open_bar(df, iv, now)
                    df.to_parquet(p)
                df = pd.read_parquet(p)
                rows.append(coverage_row(source, t, iv, df))

    # Daily bars via the repo's own loader
    daily_missing = [t for t in TICKERS if not os.path.exists(os.path.join(DATA_DIR, f"daily_{HL_SYMBOL_MAP[t]}.parquet"))]
    if refresh or daily_missing:
        from data_loader import fetch_data
        print("Fetching daily bars via data_loader.fetch_data ...")
        for t, df in fetch_data(tickers=TICKERS).items():
            df.to_parquet(os.path.join(DATA_DIR, f"daily_{HL_SYMBOL_MAP[t]}.parquet"))
    for t, df in load_daily().items():
        idx = df.index
        full = pd.date_range(idx[0], idx[-1], freq="D")
        rows.append({"source": "yfinance", "coin": HL_SYMBOL_MAP[t], "interval": "1d",
                     "first": idx[0], "last": idx[-1], "days": (idx[-1] - idx[0]).days,
                     "bars": len(df), "expected_bars": len(full), "missing_bars": len(full) - len(idx),
                     "duplicates": int(idx.duplicated().sum()),
                     "zero_volume_bars": int((df["Volume"] == 0).sum())})

    cov = pd.DataFrame(rows)
    cov.to_csv(os.path.join(RESULTS_DIR, "coverage.csv"), index=False)
    val = pd.DataFrame([proxy_validation(t, iv) for t in TICKERS for iv in INTERVALS])
    val.to_csv(os.path.join(RESULTS_DIR, "proxy_validation.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(cov.to_string(index=False))
    print()
    print(val.to_string(index=False))


if __name__ == "__main__":
    main(refresh="--refresh" in sys.argv)
