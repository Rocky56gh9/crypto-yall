"""
aggressive_strategy.py — 30-min 2-pole oscillator with tighter entries,
pyramiding, and tighter ATR stops.

Designed to fire more trades than the standard intraday bot while keeping
risk controlled via tighter stops and a lower drawdown halt threshold.
"""

import pandas as pd
import numpy as np

from indicators import butterworth_lowpass, two_pole_oscillator, average_true_range


# Parameters tuned for 30-min bars (faster than 1h)
BW_CUTOFF_30M = 0.1
SMA_PERIOD_30M = 20
OSC_UPPER = 0.25         # Tighter entry threshold — more signals
OSC_LOWER = -0.25
ATR_PERIOD = 14
ATR_STOP_MULT = 3.0      # Was 1.5; see docs/FORK_CHANGES.md §7


def generate_aggressive_signals(
    df: pd.DataFrame,
    allow_short: bool = True,
    bw_cutoff: float = BW_CUTOFF_30M,
    sma_period: int = SMA_PERIOD_30M,
    osc_upper: float = OSC_UPPER,
    osc_lower: float = OSC_LOWER,
    atr_stop_mult: float = ATR_STOP_MULT,
) -> pd.DataFrame:
    """
    Generate aggressive 2-pole oscillator signals on 30-min data.

    Signal column: 1 = long, -1 = short, 0 = flat.
    Pyramid column: int 0/1/2 indicating how many pyramid adds to apply.

    Entry rules:
      - Long:   oscillator crosses up through osc_lower (from below)
      - Short:  oscillator crosses down through osc_upper (from above)
    Exit rules:
      - Long:   oscillator crosses down through 0, or ATR stop hit
      - Short:  oscillator crosses up through 0, or ATR stop hit
    Pyramid rules (winners only):
      - In a long, if oscillator dips back to osc_lower then recovers, add
      - In a short, if oscillator pops to osc_upper then fades, add
      - Max 2 pyramid adds per position
    """
    out = df.copy()

    bw = butterworth_lowpass(df["Close"], cutoff=bw_cutoff)
    osc_raw = two_pole_oscillator(df["Close"], cutoff=bw_cutoff, sma_period=sma_period)
    atr = average_true_range(df["High"], df["Low"], df["Close"], period=ATR_PERIOD)

    # Normalize oscillator to z-score (same approach as standard intraday)
    zscore_window = 100
    osc_mean = osc_raw.rolling(zscore_window, min_periods=20).mean()
    osc_std = osc_raw.rolling(zscore_window, min_periods=20).std()
    osc = (osc_raw - osc_mean) / osc_std.replace(0, np.nan)
    osc = osc.fillna(0)

    out["BW_Filter"] = bw
    out["TwoPole_Osc"] = osc
    out["ATR"] = atr

    signals = np.zeros(len(df), dtype=int)
    pyramids = np.zeros(len(df), dtype=int)  # tracks current pyramid count per bar
    entry_price = np.nan
    position = 0
    pyramid_count = 0  # 0, 1, or 2

    osc_vals = osc.values
    close_vals = df["Close"].values
    atr_vals = atr.values

    for i in range(1, len(df)):
        prev_osc = osc_vals[i - 1]
        curr_osc = osc_vals[i]
        price = close_vals[i]
        atr_now = atr_vals[i] if not np.isnan(atr_vals[i]) else 0

        # Stop-loss check first
        if position == 1 and not np.isnan(entry_price):
            stop = entry_price - atr_stop_mult * atr_now
            if price <= stop:
                position = 0
                entry_price = np.nan
                pyramid_count = 0
                signals[i] = 0
                pyramids[i] = 0
                continue
        elif position == -1 and not np.isnan(entry_price):
            stop = entry_price + atr_stop_mult * atr_now
            if price >= stop:
                position = 0
                entry_price = np.nan
                pyramid_count = 0
                signals[i] = 0
                pyramids[i] = 0
                continue

        # Exit on zero crossing
        if position == 1 and prev_osc > 0 >= curr_osc:
            position = 0
            entry_price = np.nan
            pyramid_count = 0
            signals[i] = 0
            pyramids[i] = 0
            continue
        if position == -1 and prev_osc < 0 <= curr_osc:
            position = 0
            entry_price = np.nan
            pyramid_count = 0
            signals[i] = 0
            pyramids[i] = 0
            continue

        # Entry rules
        if position == 0:
            if np.isnan(prev_osc) or np.isnan(curr_osc):
                signals[i] = 0
                pyramids[i] = 0
                continue
            if prev_osc <= osc_lower < curr_osc:
                position = 1
                entry_price = price
                pyramid_count = 0
                signals[i] = 1
                pyramids[i] = 0
                continue
            if allow_short and prev_osc >= osc_upper > curr_osc:
                position = -1
                entry_price = price
                pyramid_count = 0
                signals[i] = -1
                pyramids[i] = 0
                continue

        # Pyramid rules: add on a re-entry within an existing winning position
        if position == 1 and pyramid_count < 2:
            if prev_osc <= osc_lower < curr_osc:
                pyramid_count += 1
        elif position == -1 and pyramid_count < 2:
            if prev_osc >= osc_upper > curr_osc:
                pyramid_count += 1

        signals[i] = position
        pyramids[i] = pyramid_count

    out["Signal"] = signals
    out["Pyramid"] = pyramids
    return out


def classify_aggressive_signal(last_signal: int, prev_signal: int) -> str:
    """Map signal values to human-readable action keys."""
    if last_signal == 1 and prev_signal != 1:
        return "buy"
    if last_signal == -1 and prev_signal != -1:
        return "enter_short"
    if last_signal == 0 and prev_signal == 1:
        return "sell_exit"
    if last_signal == 0 and prev_signal == -1:
        return "cover_short"
    if last_signal == 1:
        return "hold_long"
    if last_signal == -1:
        return "hold_short"
    return "flat"
