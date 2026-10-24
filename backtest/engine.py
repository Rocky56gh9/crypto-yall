"""
backtest/engine.py — Fee-inclusive executor replay.

Mirrors what each executor does on a GitHub run, bar by bar:

  * At each *run* bar (cadence mask), the bot sees only the last two signal
    bars, maps them to an action with the bot's own classify_* function, and
    calls the bot's own decide_trades() (imported, not re-implemented).
  * Orders decided at bar t's close fill at bar t+1's open
    (+/- 1 bp slippage, 4.5 bp taker fee per side).
  * Every entry places a reduce-only exchange stop at fill -/+ mult x ATR[t]
    (hyperliquid_executor.stop_price_for). Pyramid adds re-place the stop
    from the latest fill. Stops are checked on every bar, intrabar, against
    the bar's low/high, whether or not a run happens. A stop fills at the
    stop price (or the bar open if the bar gaps through it) minus 2 bp, plus
    the taker fee.
  * A position whose stop fired is "stale owned" at the next run and goes
    into cooldown, exactly as the executors reconcile it.
  * Orders under Hyperliquid's $10 minimum notional are rejected.

Sizing: notional = capital x size_pct x leverage, fixed capital (the executors
read the capital env var, not account equity).
"""

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

TAKER_FEE = 0.00045
SLIPPAGE = 0.0001
STOP_ADVERSE = 0.0002
MIN_NOTIONAL = 10.0


@dataclass
class BotSpec:
    name: str
    capital: float
    size_pct: float
    max_positions: int
    leverage_for: Callable[[str, dict], float]   # (ticker, signal_info) -> leverage
    stop_mult_for: Callable[[str], float]
    classify: Callable                           # (last, prev, row) -> action
    decide: Callable                             # wraps the executor's decide_trades
    pyramid_size_pct: float = 0.0
    hl_map: dict = field(default_factory=dict)


@dataclass
class SimResult:
    trades: pd.DataFrame
    pnl_net: pd.DataFrame      # per-bar cumulative MTM net PnL per ticker
    index: pd.DatetimeIndex
    rejected: int
    runs: int


def align(frames: dict[str, pd.DataFrame], cols: list[str]) -> tuple[pd.DatetimeIndex, dict]:
    """Union index across assets; per-asset numpy arrays (NaN where absent)."""
    idx = frames[next(iter(frames))].index
    for df in frames.values():
        idx = idx.union(df.index)
    out = {}
    for t, df in frames.items():
        d = df.reindex(idx)
        out[t] = {c: (d[c].to_numpy(dtype=float) if pd.api.types.is_numeric_dtype(d[c])
                      else d[c].astype(object).to_numpy())
                  for c in cols if c in d.columns}
    return idx, out


def simulate(spec: BotSpec, frames: dict[str, pd.DataFrame], run_mask: np.ndarray,
             start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> SimResult:
    """frames[ticker] needs Open/High/Low/Close/Signal/ATR/TwoPole_Osc (+ Pyramid,
    Regime, Bull_Prob, Bear_Prob, Leverage when the bot uses them)."""
    cols = ["Open", "High", "Low", "Close", "Signal", "ATR", "TwoPole_Osc", "Pyramid",
            "Regime", "Bull_Prob", "Bear_Prob", "Leverage"]
    idx, A = align(frames, cols)
    tickers = list(frames.keys())
    n = len(idx)
    lo = 0 if start is None else int(idx.searchsorted(start))
    hi = n if end is None else int(idx.searchsorted(end, side="right"))

    pos = {}           # ticker -> dict(dir, size, entry_raw, notional, cost, stop, entry_i, adds)
    owned, cooldown, pyramid_state = set(), set(), {}
    pending = []       # orders to fill at next bar open
    trades = []
    cash = {t: 0.0 for t in tickers}
    mtm = np.zeros((hi - lo, len(tickers)))
    rejected = runs = 0
    coin = spec.hl_map

    def close_pos(t, i, raw_px, reason, adverse):
        p = pos.pop(t)
        px = raw_px * (1 - adverse * p["dir"])
        exit_notional = p["size"] * raw_px
        exit_cost = p["size"] * abs(raw_px - px) + exit_notional * TAKER_FEE
        gross = p["dir"] * p["size"] * (raw_px - p["entry_raw"])
        cash[t] += gross - exit_cost
        trades.append({
            "ticker": t, "side": "long" if p["dir"] > 0 else "short",
            "entry_time": idx[p["entry_i"]], "exit_time": idx[i],
            "entry_px": p["entry_raw"], "exit_px": raw_px, "notional": p["notional"],
            "gross": gross, "costs": p["cost"] + exit_cost, "net": gross - p["cost"] - exit_cost,
            "exit_reason": reason, "pyramid_adds": p["adds"],
        })
        if reason != "stop":
            owned.discard(coin[t])
            pyramid_state.pop(coin[t], None)

    for k, i in enumerate(range(lo, hi)):
        # 1. Fill orders decided at the previous run, at this bar's open
        for o in pending:
            t, a = o["ticker"], A[o["ticker"]]
            op = a["Open"][i]
            if np.isnan(op):
                continue
            if o["action"] == "close":
                if t in pos:
                    close_pos(t, i, op, "signal", SLIPPAGE)
                continue
            d = 1 if o["side"] == "long" else -1
            notional = spec.capital * o["size_pct"] * o["lev"]
            if notional < MIN_NOTIONAL:
                rejected += 1
                continue
            is_pyr = o["action"].startswith("pyramid_")
            if is_pyr and t not in pos:
                continue  # position stopped out before the add could fill
            fill = op * (1 + SLIPPAGE * d)
            size = notional / fill
            cost = size * abs(fill - op) + notional * TAKER_FEE
            cash[t] -= cost
            if is_pyr:
                p = pos[t]
                p["entry_raw"] = (p["entry_raw"] * p["size"] + op * size) / (p["size"] + size)
                p["size"] += size
                p["notional"] += notional
                p["cost"] += cost
                p["adds"] += 1
                pyramid_state[coin[t]] = pyramid_state.get(coin[t], 0) + 1
            else:
                pos[t] = {"dir": d, "size": size, "entry_raw": op, "notional": notional,
                          "cost": cost, "entry_i": i, "adds": 0}
                owned.add(coin[t])
                cooldown.discard(coin[t])
                pyramid_state[coin[t]] = 0
            atr = o["atr"]
            pos[t]["stop"] = (fill - d * o["mult"] * atr) if atr and atr > 0 else np.nan
        pending = []

        # 2. Exchange stops, intrabar
        for t in list(pos.keys()):
            p, a = pos[t], A[t]
            st = p["stop"]
            if np.isnan(st) or np.isnan(a["Low"][i]):
                continue
            if p["dir"] > 0 and a["Low"][i] <= st:
                close_pos(t, i, min(st, a["Open"][i]), "stop", STOP_ADVERSE)
            elif p["dir"] < 0 and a["High"][i] >= st:
                close_pos(t, i, max(st, a["Open"][i]), "stop", STOP_ADVERSE)

        # 3. Executor run at this bar's close
        if run_mask[i] and i + 1 < n:
            runs += 1
            signals = {}
            for t in tickers:
                a = A[t]
                if np.isnan(a["Close"][i]) or i == 0 or np.isnan(a["Signal"][i - 1]):
                    continue
                last, prev = int(a["Signal"][i]), int(a["Signal"][i - 1])
                info = {"signal": last, "price": a["Close"][i],
                        "osc": float(a["TwoPole_Osc"][i]) if "TwoPole_Osc" in a else 0.0,
                        "atr": float(a["ATR"][i]) if not np.isnan(a["ATR"][i]) else 0.0}
                if "Pyramid" in a:
                    pyr, pp = int(a["Pyramid"][i]), int(a["Pyramid"][i - 1])
                    info["pyramid"], info["pyramid_added"] = pyr, pyr > pp
                if "Regime" in a:
                    info["regime"] = a["Regime"][i]
                    info["bull_conf"] = float(np.nan_to_num(a["Bull_Prob"][i]))
                    info["bear_conf"] = float(np.nan_to_num(a["Bear_Prob"][i]))
                    info["leverage"] = float(a["Leverage"][i])
                info["action"] = spec.classify(last, prev, info)
                signals[t] = info

            open_coins = {coin[t] for t in pos}
            stale = owned - open_coins
            if stale:
                owned -= stale
                cooldown |= stale
            for t, s in signals.items():
                if coin[t] in cooldown and s["action"] not in ("hold_long", "hold_short"):
                    cooldown.discard(coin[t])
            managed = {coin[t]: {"size": pos[t]["dir"] * pos[t]["size"]} for t in pos}
            decided = spec.decide(signals, managed, spec.max_positions, pyramid_state, cooldown)
            for tr in decided:
                t = tr["ticker"]
                if tr["action"] == "close":
                    pending.append({"ticker": t, "action": "close"})
                    continue
                is_pyr = tr["action"].startswith("pyramid_")
                pending.append({
                    "ticker": t, "action": tr["action"], "side": tr["side"],
                    "size_pct": spec.pyramid_size_pct if is_pyr else spec.size_pct,
                    "lev": spec.leverage_for(t, signals[t]), "atr": signals[t]["atr"],
                    "mult": spec.stop_mult_for(t),
                })

        # 4. Mark to market at close
        for j, t in enumerate(tickers):
            v = cash[t]
            if t in pos:
                c = A[t]["Close"][i]
                p = pos[t]
                if not np.isnan(c):
                    v += p["dir"] * p["size"] * (c - p["entry_raw"])
            mtm[k, j] = v

    # Close anything still open at the last bar's close (with costs)
    last_i = hi - 1
    for t in list(pos.keys()):
        c = A[t]["Close"][last_i]
        close_pos(t, last_i, c, "end_of_data", SLIPPAGE)
        mtm[-1, tickers.index(t)] = cash[t]

    tdf = pd.DataFrame(trades)
    if len(tdf):
        tdf["hold_h"] = (tdf["exit_time"] - tdf["entry_time"]) / pd.Timedelta(hours=1)
    return SimResult(trades=tdf, pnl_net=pd.DataFrame(mtm, index=idx[lo:hi], columns=tickers),
                     index=idx[lo:hi], rejected=rejected, runs=runs)


# ── Cadence masks ────────────────────────────────────────────────────────────

def full_cadence(n: int) -> np.ndarray:
    return np.ones(n, dtype=bool)


def throttled_cadence(n: int, mean_gap_bars: float, seed: int) -> np.ndarray:
    """Runs separated by geometric gaps (memoryless skips) with the given mean."""
    rng = np.random.default_rng(seed)
    mask = np.zeros(n, dtype=bool)
    i = int(rng.integers(0, max(1, int(mean_gap_bars))))
    p = 1.0 / mean_gap_bars
    while i < n:
        mask[i] = True
        i += int(rng.geometric(p))
    return mask


def bernoulli_cadence(n: int, p: float, seed: int) -> np.ndarray:
    """Each scheduled slot delivered independently with probability p."""
    return np.random.default_rng(seed).random(n) < p
