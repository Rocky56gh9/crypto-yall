"""
backtest/signals.py — Signal generation for the backtest.

As-coded runs call the repo's own generate_intraday_signals /
generate_aggressive_signals / generate_signals. Variants that need a hook the
originals don't expose (coin-flip entries, trailing exit, regime gate) use
mirror loops below; parity_check() proves each mirror reproduces its original
bar-for-bar when the hook is off.
"""

import numpy as np
import pandas as pd

from intraday_strategy import generate_intraday_signals
from aggressive_strategy import generate_aggressive_signals
from strategy import generate_signals


# ── Intraday / aggressive mirror ─────────────────────────────────────────────

def osc_loop(base: pd.DataFrame, allow_short: bool, osc_lower: float, osc_upper: float,
             atr_stop_mult: float, pyramid: bool, entry: str = "threshold",
             exit_mode: str = "zero", p_entry: float = 0.0, seed: int = 0,
             gate: np.ndarray | None = None, trail_mult: float = 3.0) -> pd.DataFrame:
    """Same state machine as intraday_strategy / aggressive_strategy.

    base: output of the original generator (supplies TwoPole_Osc, ATR, OHLC).
    entry: "threshold" (original) | "random" (coin-flip with prob p_entry/bar).
    exit_mode: "zero" (original zero-cross) | "trail" (Chandelier trail_mult x ATR).
    gate: per-bar daily regime labels; longs need Bull/Chop, shorts Bear/Chop.
    """
    rng = np.random.default_rng(seed)
    osc = base["TwoPole_Osc"].to_numpy()
    close = base["Close"].to_numpy()
    high = base["High"].to_numpy()
    low = base["Low"].to_numpy()
    atr = base["ATR"].to_numpy()
    n = len(base)
    signals = np.zeros(n, dtype=int)
    pyrs = np.zeros(n, dtype=int)
    position, entry_price, count = 0, np.nan, 0
    hh = ll = np.nan

    for i in range(1, n):
        prev_osc, curr_osc, price = osc[i - 1], osc[i], close[i]
        atr_now = atr[i] if not np.isnan(atr[i]) else 0

        if position == 1 and not np.isnan(entry_price):
            if price <= entry_price - atr_stop_mult * atr_now:
                position, entry_price, count = 0, np.nan, 0
                continue
        elif position == -1 and not np.isnan(entry_price):
            if price >= entry_price + atr_stop_mult * atr_now:
                position, entry_price, count = 0, np.nan, 0
                continue

        if exit_mode == "zero":
            if position == 1 and prev_osc > 0 >= curr_osc:
                position, entry_price, count = 0, np.nan, 0
                continue
            if position == -1 and prev_osc < 0 <= curr_osc:
                position, entry_price, count = 0, np.nan, 0
                continue
        else:
            if position == 1:
                hh = max(hh, high[i])
                if price <= hh - trail_mult * atr_now:
                    position, entry_price, count = 0, np.nan, 0
                    continue
            elif position == -1:
                ll = min(ll, low[i])
                if price >= ll + trail_mult * atr_now:
                    position, entry_price, count = 0, np.nan, 0
                    continue

        if position == 0:
            if np.isnan(prev_osc) or np.isnan(curr_osc):
                continue
            if entry == "threshold":
                go_long = prev_osc <= osc_lower < curr_osc
                go_short = allow_short and prev_osc >= osc_upper > curr_osc
            else:
                go_long = go_short = False
                if rng.random() < p_entry:
                    if allow_short and rng.random() < 0.5:
                        go_short = True
                    else:
                        go_long = True
            if gate is not None:
                g = gate[i]
                go_long = go_long and g != "Bear"
                go_short = go_short and g != "Bull"
            if go_long:
                position, entry_price, count, hh = 1, price, 0, high[i]
                signals[i] = 1
                continue
            if go_short:
                position, entry_price, count, ll = -1, price, 0, low[i]
                signals[i] = -1
                continue

        if pyramid:
            if position == 1 and count < 2 and prev_osc <= osc_lower < curr_osc:
                count += 1
            elif position == -1 and count < 2 and prev_osc >= osc_upper > curr_osc:
                count += 1

        signals[i] = position
        pyrs[i] = count

    out = base[["Open", "High", "Low", "Close", "TwoPole_Osc", "ATR"]].copy()
    out["Signal"] = signals
    if pyramid:
        out["Pyramid"] = pyrs
    return out


def base_signals(bot: str, df: pd.DataFrame, allow_short: bool, thr: float, mult: float) -> pd.DataFrame:
    """Run the repo's own generator (bot = 'intraday' | 'aggressive')."""
    fn = generate_intraday_signals if bot == "intraday" else generate_aggressive_signals
    out = fn(df, allow_short=allow_short, osc_upper=thr, osc_lower=-thr, atr_stop_mult=mult)
    cols = ["Open", "High", "Low", "Close", "TwoPole_Osc", "ATR", "Signal"]
    if bot == "aggressive":
        cols.append("Pyramid")
    return out[cols]


def entry_rate(sig: pd.Series) -> float:
    """Entries per flat bar: what a coin-flip control must match."""
    s = sig.to_numpy()
    entries = int(((s[1:] != 0) & (s[:-1] == 0)).sum())
    flat = int((s[:-1] == 0).sum())
    return entries / flat if flat else 0.0


# ── Daily mirror (strategy.generate_signals with an entry hook) ──────────────

def daily_loop(df, regimes, bull_probs=None, bear_probs=None, osc_lower=-1.0, osc_upper=1.0,
               zscore_entry=-2.0, zscore_exit=2.0, mom_threshold=0.0, aggressive=False,
               atr_mult=3.0, bull_leverage=3.0, allow_short=True,
               random_p: float | None = None, seed: int = 0) -> pd.DataFrame:
    """Line-for-line copy of strategy.generate_signals. With random_p set,
    every flat-state entry condition is replaced by a coin flip (prob random_p
    per eligible bar); directions stay those the regime permits."""
    rng = np.random.default_rng(seed)
    flip = (lambda: rng.random() < random_p) if random_p is not None else None
    osc, zscore_s, mom = df["TwoPole_Osc"], df["ZScore"], df["VolScaled_Mom"]
    close, high, low, atr = df["Close"], df["High"], df["Low"], df["ATR"]
    n = len(df)
    signal = np.zeros(n, dtype=int)
    leverage = np.zeros(n, dtype=float)
    position, highest_since, lowest_since = 0, np.nan, np.nan
    pyramid_bonus, day_high_streak = 0.0, 0
    osc_v, z_v, mom_v = osc.to_numpy(), zscore_s.to_numpy(), mom.to_numpy()
    c_v, h_v, l_v, a_v = close.to_numpy(), high.to_numpy(), low.to_numpy(), atr.to_numpy()
    reg_v = regimes.to_numpy()
    bp_v = bull_probs.to_numpy() if bull_probs is not None else None
    br_v = bear_probs.to_numpy() if bear_probs is not None else None
    nz = lambda x: 0.0 if np.isnan(x) else x  # noqa: E731

    for i in range(1, n):
        regime = reg_v[i]
        prev_osc, curr_osc = nz(osc_v[i - 1]), nz(osc_v[i])
        curr_z, curr_mom = nz(z_v[i]), nz(mom_v[i])
        curr_close, curr_high, curr_low = c_v[i], h_v[i], l_v[i]
        curr_atr = nz(a_v[i])
        bp = float(bp_v[i]) if bp_v is not None and not np.isnan(bp_v[i]) else 0.5
        bear_p = float(br_v[i]) if br_v is not None and not np.isnan(br_v[i]) else 0.5

        if aggressive and position == 1:
            highest_since = max(highest_since, curr_high) if not np.isnan(highest_since) else curr_high
            if curr_close <= highest_since - atr_mult * curr_atr:
                position, highest_since, pyramid_bonus, day_high_streak = 0, np.nan, 0.0, 0
                continue
        if aggressive and position == -1:
            lowest_since = min(lowest_since, curr_low) if not np.isnan(lowest_since) else curr_low
            if curr_close >= lowest_since + atr_mult * curr_atr:
                position, lowest_since = 0, np.nan
                continue

        if regime == "Bear":
            if aggressive:
                if position == 1:
                    position, highest_since, pyramid_bonus, day_high_streak = 0, np.nan, 0.0, 0
                if position == 0 and allow_short:
                    cond = prev_osc >= osc_upper > curr_osc and curr_mom < mom_threshold
                    if flip() if flip else cond:
                        position, lowest_since = -1, curr_low
                elif position == -1:
                    if prev_osc <= osc_lower < curr_osc:
                        position, lowest_since = 0, np.nan
            else:
                position, highest_since, pyramid_bonus, day_high_streak = 0, np.nan, 0.0, 0

        elif regime == "Chop":
            if position == 0:
                if aggressive:
                    if flip:
                        if flip():
                            if allow_short and rng.random() < 0.5:
                                position, lowest_since = -1, curr_low
                            else:
                                position, highest_since, pyramid_bonus, day_high_streak = 1, curr_high, 0.0, 0
                    elif prev_osc <= osc_lower < curr_osc:
                        position, highest_since, pyramid_bonus, day_high_streak = 1, curr_high, 0.0, 0
                    elif allow_short and prev_osc >= osc_upper > curr_osc and curr_mom < -0.5:
                        position, lowest_since = -1, curr_low
                else:
                    cond = prev_osc <= osc_lower < curr_osc and curr_z < zscore_entry
                    if flip() if flip else cond:
                        position = 1
            elif position == 1:
                if (prev_osc >= osc_upper > curr_osc) or curr_z > zscore_exit:
                    position = 0
                    if aggressive:
                        highest_since, pyramid_bonus, day_high_streak = np.nan, 0.0, 0
            elif position == -1:
                if prev_osc <= osc_lower < curr_osc or curr_mom > 0:
                    position, lowest_since = 0, np.nan

        elif regime == "Bull":
            if position == -1:
                position, lowest_since = 0, np.nan
            if position == 0:
                cond = curr_mom > mom_threshold and prev_osc < 0 and curr_osc > prev_osc
                if flip() if flip else cond:
                    position = 1
                    highest_since = curr_high if aggressive else np.nan
                    pyramid_bonus, day_high_streak = 0.0, 0
            elif position == 1:
                if aggressive and i >= 2:
                    if curr_high > max(h_v[i - 1], h_v[i - 2]):
                        day_high_streak += 1
                        pyramid_bonus = min(day_high_streak * 0.3, bull_leverage * 0.5)
                    else:
                        pyramid_bonus = max(0.0, pyramid_bonus - 0.1)
                if curr_mom < 0:
                    position, highest_since, pyramid_bonus, day_high_streak = 0, np.nan, 0.0, 0
        else:
            position, highest_since, lowest_since, pyramid_bonus, day_high_streak = 0, np.nan, np.nan, 0.0, 0

        signal[i] = position
        if aggressive and position == 1:
            leverage[i] = min(bull_leverage * bp + pyramid_bonus, bull_leverage * 1.5) if regime == "Bull" else 1.0
        elif aggressive and position == -1:
            leverage[i] = min(2.0 * bear_p, 2.0) if regime == "Bear" else min(1.5 * bear_p, 1.5)
        elif not aggressive and position == 1:
            leverage[i] = 1.0

    out = df[["Close"]].copy()
    out["Signal"] = signal
    out["Leverage"] = leverage
    out["Regime"] = regimes
    return out


# ── Parity ───────────────────────────────────────────────────────────────────

def parity_check(intraday_df: pd.DataFrame, thirty_df: pd.DataFrame, daily_df: pd.DataFrame) -> list[str]:
    """Return a list of human-readable parity results (raises on mismatch)."""
    msgs = []
    for bot, df in (("intraday", intraday_df), ("aggressive", thirty_df)):
        for allow_short in (True, False):
            for thr, mult in ((0.5, 3.0), (0.25, 1.5), (1.0, 4.0)):
                orig = base_signals(bot, df, allow_short, thr, mult)
                mir = osc_loop(orig, allow_short, -thr, thr, mult, pyramid=(bot == "aggressive"))
                assert (orig["Signal"].to_numpy() == mir["Signal"].to_numpy()).all(), (bot, thr, mult)
                if bot == "aggressive":
                    assert (orig["Pyramid"].to_numpy() == mir["Pyramid"].to_numpy()).all()
        msgs.append(f"{bot}: mirror == original on {len(df)} bars x 6 configs")
    for aggressive in (False, True):
        for allow_short in (True, False):
            kw = dict(aggressive=aggressive, allow_short=allow_short, atr_mult=3.0, bull_leverage=3.0)
            o = generate_signals(daily_df, daily_df["Regime"], daily_df["Bull_Prob"], daily_df["Bear_Prob"], **kw)
            m = daily_loop(daily_df, daily_df["Regime"], daily_df["Bull_Prob"], daily_df["Bear_Prob"], **kw)
            assert (o["Signal"].to_numpy() == m["Signal"].to_numpy()).all(), kw
            assert np.allclose(o["Leverage"].to_numpy(), m["Leverage"].to_numpy()), kw
    msgs.append(f"daily: mirror == original on {len(daily_df)} bars x 4 configs")
    return msgs
