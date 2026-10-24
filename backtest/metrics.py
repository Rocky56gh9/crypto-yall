"""
backtest/metrics.py — Performance metrics on daily MTM PnL + trade lists.

Annualization uses 365 days (crypto trades every day). Sortino uses the
target-zero downside deviation sqrt(mean(min(r, 0)^2)). Returns are on the
bot's capital variable, so they are small: notional per trade is 1-6% of
capital. The per-trade bps columns (on notional) read the edge directly.
"""

import numpy as np
import pandas as pd

from daily_wf import load_regimes

ANN = 365.0


def compute_metrics(inc: pd.DataFrame, trades: pd.DataFrame, capital: float, ticker: str | None = None) -> dict:
    pnl = inc[ticker] if ticker else inc.sum(axis=1)
    tr = trades[trades["ticker"] == ticker] if (ticker and len(trades)) else trades
    days = max(len(pnl), 1)
    yrs = days / ANN
    eq = capital + pnl.cumsum()
    r = eq.pct_change()
    r.iloc[0] = pnl.iloc[0] / capital
    net = float(pnl.sum())
    ann = lambda x: ((1 + x / capital) ** (1 / yrs) - 1) * 100 if capital + x > 0 else -100.0  # noqa: E731
    sd = r.std()
    dd = np.sqrt(np.mean(np.minimum(r.to_numpy(), 0) ** 2))
    peak = eq.cummax()
    n = len(tr)
    m = {
        "days": days, "ann_net_pct": ann(net), "sharpe": float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0,
        "sortino": float(r.mean() / dd * np.sqrt(ANN)) if dd > 0 else 0.0,
        "max_dd_pct": float(((eq - peak) / peak).min() * 100), "net_usd": net, "trades": n,
        "trades_per_year": n / yrs,
    }
    if n == 0:
        return {**m, "ann_gross_pct": 0.0, "gross_usd": 0.0, "costs_usd": 0.0, "cost_drag_pct_of_gross": np.nan,
                "win_rate_pct": np.nan, "avg_win_usd": np.nan, "avg_loss_usd": np.nan, "payoff": np.nan,
                "median_hold_h": np.nan, "mean_hold_h": np.nan, "pct_stop_exits": np.nan,
                "ann_net_ex_best_pct": m["ann_net_pct"], "best_trade_usd": np.nan, "avg_gross_bps": np.nan,
                "avg_net_bps": np.nan, "avg_cost_bps": np.nan, "long_net_usd": 0.0, "short_net_usd": 0.0}
    gross, costs = float(tr["gross"].sum()), float(tr["costs"].sum())
    wins = tr["net"] > 0
    avg_win = float(tr.loc[wins, "net"].mean()) if wins.any() else 0.0
    avg_loss = float(tr.loc[~wins, "net"].mean()) if (~wins).any() else 0.0
    best = float(tr["net"].max())
    return {
        **m, "ann_gross_pct": ann(gross), "gross_usd": gross, "costs_usd": costs,
        "cost_drag_pct_of_gross": costs / abs(gross) * 100 if gross else np.nan,
        "win_rate_pct": float(wins.mean() * 100), "avg_win_usd": avg_win, "avg_loss_usd": avg_loss,
        "payoff": avg_win / abs(avg_loss) if avg_loss else np.nan,
        "median_hold_h": float(tr["hold_h"].median()), "mean_hold_h": float(tr["hold_h"].mean()),
        "pct_stop_exits": float((tr["exit_reason"] == "stop").mean() * 100),
        "ann_net_ex_best_pct": ann(net - best), "best_trade_usd": best,
        "avg_gross_bps": float((tr["gross"] / tr["notional"]).mean() * 1e4),
        "avg_net_bps": float((tr["net"] / tr["notional"]).mean() * 1e4),
        "avg_cost_bps": float((tr["costs"] / tr["notional"]).mean() * 1e4),
        "long_net_usd": float(tr.loc[tr["side"] == "long", "net"].sum()),
        "short_net_usd": float(tr.loc[tr["side"] == "short", "net"].sum()),
    }


_REG = {}


def regime_at_entry(trades: pd.DataFrame) -> pd.Series:
    """Daily HMM regime in force when the entry decision was made: day D's
    regime is known from D+1 00:00 UTC."""
    out = pd.Series("None", index=trades.index, dtype=object)
    for t, grp in trades.groupby("ticker"):
        if t not in _REG:
            reg = load_regimes(t)["Regime"].dropna().copy()
            reg.index = reg.index + pd.Timedelta(days=1)
            _REG[t] = reg
        reg = _REG[t]
        pos = reg.index.searchsorted(grp["entry_time"].to_numpy(), side="right") - 1
        vals = np.where(pos >= 0, reg.to_numpy()[np.clip(pos, 0, None)], "None")
        out.loc[grp.index] = vals
    return out


def regime_table(trades: pd.DataFrame, bot: str, label: str) -> list[dict]:
    tr = trades.copy()
    tr["regime"] = regime_at_entry(tr)
    rows = []
    for (reg, side), g in tr.groupby(["regime", "side"]):
        rows.append({"bot": bot, "scenario": label, "regime": reg, "side": side, "trades": len(g),
                     "win_rate_pct": float((g["net"] > 0).mean() * 100), "net_usd": float(g["net"].sum()),
                     "gross_usd": float(g["gross"].sum()), "avg_net_bps": float((g["net"] / g["notional"]).mean() * 1e4),
                     "pct_stop_exits": float((g["exit_reason"] == "stop").mean() * 100),
                     "median_hold_h": float(g["hold_h"].median())})
    for reg, g in tr.groupby("regime"):
        rows.append({"bot": bot, "scenario": label, "regime": reg, "side": "all", "trades": len(g),
                     "win_rate_pct": float((g["net"] > 0).mean() * 100), "net_usd": float(g["net"].sum()),
                     "gross_usd": float(g["gross"].sum()), "avg_net_bps": float((g["net"] / g["notional"]).mean() * 1e4),
                     "pct_stop_exits": float((g["exit_reason"] == "stop").mean() * 100),
                     "median_hold_h": float(g["hold_h"].median())})
    return rows
