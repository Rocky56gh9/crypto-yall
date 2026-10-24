"""
backtest/daily_wf.py — Cache daily HMM regimes once, then run the repo's own
backtester.walk_forward() per asset for standard and aggressive modes.

walk_forward() picks parameters on each 252-day IS window and scores the next
63-day OOS window. Its own return model is fee-free and rebalances leverage
every day, so its numbers are saved as-is (daily_walkforward_feefree.csv) and
the chosen per-fold parameters are saved for the fee-inclusive execution
replay in run_backtests.py.

Run:  backtest/.venv/bin/python backtest/daily_wf.py
"""

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from data_fetch import DATA_DIR, RESULTS_DIR, TICKERS, load_daily  # noqa: E402
from intraday_data_loader import HL_SYMBOL_MAP  # noqa: E402


def regime_path(ticker):
    return os.path.join(DATA_DIR, f"regimes_{HL_SYMBOL_MAP[ticker]}.parquet")


def _compute_regimes(ticker):
    from indicators import compute_all
    from hmm_engine import causal_hmm_regimes
    t0 = time.time()
    raw = load_daily()[ticker]
    df = compute_all(raw)
    regimes, bull, bear = causal_hmm_regimes(df)
    df["Regime"] = regimes
    df["Bull_Prob"] = bull
    df["Bear_Prob"] = bear
    df.to_parquet(regime_path(ticker))
    return ticker, time.time() - t0


def load_regimes(ticker) -> pd.DataFrame:
    """Daily frame with indicators + causal Regime/Bull_Prob/Bear_Prob."""
    return pd.read_parquet(regime_path(ticker))


def _run_wf(job):
    from backtester import walk_forward, IS_DAYS, OOS_DAYS
    ticker, mode = job
    t0 = time.time()
    df = load_regimes(ticker)
    pre = (df, df["Regime"], df["Bull_Prob"], df["Bear_Prob"])
    res = walk_forward(df, aggressive=(mode == "aggressive"), ticker=ticker, precomputed=pre)
    # Replicate walk_forward's fold cursor so OOS windows can be rebuilt exactly
    folds, cursor, n = [], IS_DAYS, len(df)
    for params in res.best_params_per_fold:
        folds.append({"oos_start": str(df.index[cursor].date()),
                      "oos_end": str(df.index[min(cursor + OOS_DAYS, n) - 1].date()),
                      "iloc_start": cursor, "iloc_end": min(cursor + OOS_DAYS, n),
                      "params": params})
        cursor += OOS_DAYS
    summary = {"coin": HL_SYMBOL_MAP[ticker], "mode": mode,
               "oos_start": folds[0]["oos_start"] if folds else None,
               "oos_end": folds[-1]["oos_end"] if folds else None,
               "folds": len(folds), "total_return": res.total_return,
               "max_drawdown": res.max_drawdown, "sharpe_252": res.sharpe_ratio,
               "sortino_252": res.sortino_ratio,
               "pct_days_in_market": float((res.signal_series != 0).mean()) if len(res.signal_series) else 0.0}
    return ticker, mode, folds, summary, time.time() - t0


def main():
    missing = [t for t in TICKERS if not os.path.exists(regime_path(t))]
    if missing:
        with ProcessPoolExecutor(max_workers=7) as ex:
            for t, secs in ex.map(_compute_regimes, missing):
                print(f"regimes {t}: {secs:.0f}s", flush=True)

    jobs = [(t, m) for t in TICKERS for m in ("standard", "aggressive")]
    all_folds, rows = {}, []
    with ProcessPoolExecutor(max_workers=11) as ex:
        for t, mode, folds, summary, secs in ex.map(_run_wf, jobs):
            print(f"walk_forward {t} {mode}: {len(folds)} folds, {secs:.0f}s", flush=True)
            all_folds[f"{t}|{mode}"] = folds
            rows.append(summary)
    with open(os.path.join(RESULTS_DIR, "daily_wf_folds.json"), "w") as f:
        json.dump(all_folds, f, indent=1)
    pd.DataFrame(rows).to_csv(os.path.join(RESULTS_DIR, "daily_walkforward_feefree.csv"), index=False)


if __name__ == "__main__":
    main()
