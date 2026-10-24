# Backtest report: daily, intraday, and aggressive bots

Generated 2026-10-24 from `backtest/` (rerun: `data_fetch.py` → `daily_wf.py` → `run_backtests.py` → `extra_checks.py` → `report_tables.py REPORT.template.md results/REPORT.md`). Every number below comes from `backtest/results/*.csv`.

## Verdict

**No bot earns paid infrastructure.** The daily bot passes your rule in both modes, but it already works on GitHub's free scheduler: losing 87.5% of its daily runs still leaves a positive Sortino. Most of the Sortino it does lose comes back from a free code fix, not from a paid runner (see "Fix the code, not the runner"). The intraday bot fails the random-entry test. The aggressive bot fails every test.

Rule applied: out-of-sample, fee-inclusive Sortino at full cadence > 0; Sortino at or above the 95th percentile of the random-entry control; positive annualized net after removing the single best trade.

{{VERDICT}}

| Bot | Plain-English verdict |
|---|---|
| **Daily, standard** | **Has an edge; no paid infrastructure needed.** Out-of-sample Sortino 3.16 beats all 50 random-entry seeds. Every dollar of profit comes from Bull-regime longs. It survives removing its best trade (+1.03%/yr) and removing XRP, its biggest contributor (Sortino 1.54). At 50% and 12.5% run delivery, returns hold, but Sortino falls to 1.93 and 1.28. A state-based exit rule (free) brings that back to 2.78 and 1.75. Expected net at current sizing: about $41/yr on $2,000. |
| **Daily, aggressive** | **Same edge with more leverage; shorts add nothing.** Sortino 3.02 (98th percentile vs random). The extra return over standard comes from Bull-long leverage. 18 Bear shorts netted +$0.17 in total. That matches the testnet finding: the short leg is risk without return. About $75/yr at current sizing. |
| **Intraday** | **Does not earn it.** As coded (±0.5, 3x stop, no fitting), full-history Sortino is -0.25 at full cadence, at the 54th percentile vs random: no entry edge. The walk-forward version, which mostly picked ±1.0 / 4x, reaches Sortino 0.71. That is the 94.5th percentile over 200 random seeds (11 seeds matched or beat it), and dropping SOL turns it negative (Sortino -0.24). Costs take 55% of gross. Expected net is about $10/yr. |
| **Aggressive** | **No edge; fees destroy it.** Gross edge is 0.8 bps per trade against an 11.3 bps round-trip cost, over about 2,000 trades per year. Out-of-sample: -9.2%/yr, Sortino -1.80, max drawdown -29% of capital. Every threshold/stop pair in the grid loses at full cadence. Since Dec 2025, the best in-sample pair has a negative Sortino in every fold. |

## Is the problem the signal or the infrastructure?

**The signal.** Running the fast bots at full cadence makes them worse, because they trade more and pay more in costs. The throttled cadence looked survivable only because of an executor bug that turns missed exits into accidental long holds. In a 2023-2026 bull market, that earns drift, not edge. At throttled cadence both fast bots sit at the median of their random-entry control (54th and 48th percentile).

The mechanism behind "77 of 88 closes were stops":

```
bar        t0            t1             t2               t3 ... tN
strategy   buy           hold_long      sell_exit        flat ... flat
GitHub     run           (skipped)      (skipped)        run
executor   opens long    -              exit never seen  action = "flat"
                                                         decide_trades has no rule
                                                         for flat + open position
                                                         -> position orphaned
exchange                                                 static stop at entry - 3xATR
                                                         eventually fires (loss)
```

`decide_trades` closes only on the transition actions `sell_exit` / `cover_short` / flips (`intraday_executor.py:151-154`, `aggressive_executor.py:156-159`, `hyperliquid_executor.py:248-254`). Those actions exist for exactly one bar. When the run that would see that bar is skipped, the exit is lost for good.

Replaying Sept 10 to Oct 14 2026 with the stop multipliers you ran then (intraday 2.0x, aggressive 1.5x) reproduces the testnet pattern at throttled cadence: 75-86% stop exits and 10-20% win rate, against 87.5% and 12% live. At full cadence the same window gives 46-59% stop exits and 26-29% win rate. The dollar P&L differs from live because of a different universe, testnet prices, and daily-bot fills mixed into the live total.

{{LIVE}}

### Price of bad infrastructure (full cadence vs throttled, walk-forward OOS, pooled)

Throttled = one run every 5 h on average (geometric gaps), 20 seeds, median shown. The daily rows use per-slot delivery probability instead (0.5 and 0.125), because the daily cron has one slot per day. Those two rates are assumptions; no delivery data exists for the daily workflow.

{{CADENCE}}

Seed distributions (p10 / p50 / p90):

{{SEEDS}}

How to read the gap: for daily standard, full cadence buys at most 0.25 points/yr of return and 1.2-1.9 points of Sortino. Daily aggressive actually earns more when throttled, from the same missed-exit drift. For the intraday bot, cadence buys nothing (Sortino 0.71 vs 0.69). For the aggressive bot, more cadence loses money faster.

### Fix the code, not the runner

This tests a backtest-only wrapper around each executor's `decide_trades`: it also closes any open position whose current strategy signal no longer matches it, which fixes code issue 1. As-coded parameters. Full-cadence rows are identical with and without the fix, as they should be: at every-bar cadence no transition is ever missed. At throttled cadence, the fix pulls the fast bots back to their (edge-less) full-cadence results, which confirms their throttled "gains" were missed-exit drift. For the daily bot, it recovers most of the Sortino lost to skipped runs, at no cost.

{{STATE_FIX}}

## Baselines

Fully invested buy-and-hold over the same windows, yfinance daily closes, one entry fee. The bots deploy 1-6% of capital per position, so compare Sortino, not return. A mostly-flat equity curve also inflates Sortino, which is why the random-entry control (same exits, same exposure profile) is the binding comparison, not buy-and-hold.

{{BASELINES}}

Random-entry controls: coin-flip entries at each strategy's own entry rate per flat bar, per asset, with the strategy's exact exit rules, stops, pyramids, and executor logic. 50 seeds, plus 200 for the intraday walk-forward.

{{RANDOM}}

{{RANDOM200}}

## Daily strategy (walk_forward params, fee-inclusive executor replay)

Parameters per fold come from the repo's own `backtester.walk_forward()` (252-day in-sample, 63-day out-of-sample, Sortino-optimized over 432 combos). OOS signals are regenerated per fold exactly as `walk_forward` does, then replayed through `hyperliquid_executor.decide_trades` with exchange stops (3x large cap, 4x mid cap ATR), next-open fills, fees, and max 4 positions on $2,000. Evaluation window starts 2023-04-01, when the HMM first has 365 days of training data.

Standard mode, per asset:

{{ASSET_DAILY_STD}}

Aggressive mode, per asset:

{{ASSET_DAILY_AGG}}

For reference, `walk_forward()`'s own fee-free numbers. They assume full capital at 1x per asset, re-leverage daily, and ignore stops and fees, so they are not comparable in size to the replay. Its OOS ends at 2026-08-24 for most assets, because it drops the final partial fold.

{{DAILY_FEEFREE}}

## Intraday (1h) and aggressive (30m)

### Full-history grid at full cadence (2023-04-01 to 2026-10-24, pooled, 7 coins)

Each pair replaces both the strategy's `osc_upper/osc_lower`/`atr_stop_mult` and the executor's exchange stop multiplier. Intraday:

{{GRID_INTRADAY}}

Aggressive:

{{GRID_AGGRESSIVE}}

Throttled-cadence Sortino (median of 20 seeds), intraday then aggressive:

{{GRID_INTRADAY_SORTINO_THR}}

{{GRID_AGGRESSIVE_SORTINO_THR}}

### Walk-forward selection (182-day IS, 61-day OOS, pick by pooled IS Sortino at full cadence)

Intraday:

{{FOLDS_INTRADAY}}

Aggressive:

{{FOLDS_AGGRESSIVE}}

### Walk-forward OOS, per asset, full cadence

Intraday:

{{ASSET_INTRADAY}}

Aggressive:

{{ASSET_AGGRESSIVE}}

### As coded (intraday ±0.5 / 3x, aggressive ±0.25 / 3x), per asset, full cadence

{{ASSET_INTRADAY_ASCODED}}

{{ASSET_AGGRESSIVE_ASCODED}}

## Variants (intraday, as-coded parameters)

- **trail**: the zero-cross exit is replaced by a Chandelier exit (highest high since entry - 3x ATR, on close). The executor still places only its static initial stop.
- **gate**: daily HMM regime gate. Longs need Bull or Chop, shorts need Bear or Chop, using the regime of the last completed daily bar.

{{VARIANTS}}

Neither variant fixes the full-cadence result. The trailing exit is worse (-6.1 bps net per trade). The regime gate is neutral at full cadence (-0.28 vs -0.25 Sortino). Its better throttled result comes from the same missed-exit drift capture as above, not from a better signal.

## Regime attribution (daily HMM regime in force at entry)

{{REGIMES}}

By side, walk-forward OOS at full cadence:

{{REGIMES_SIDE}}

What the regime split shows:
- **Daily:** 100% of standard-mode profit is Bull-regime longs, which is by design. Expect roughly zero, not positive, return through a prolonged Bear: the bot sits in cash. The OOS window includes a -53% BTC drawdown, and the daily bot's own max drawdown was about -1% of capital.
- **Intraday:** mean reversion pays in Chop (+35.6 bps/trade) and Bear (+10.7) but loses in Bull (-9.3), where shorts are the worst bucket (-28.6 bps). Even so, gating by regime did not help as coded.
- **Aggressive:** loses in every regime and on both sides.

## Leave-one-asset-out (walk-forward OOS, full cadence)

{{LOO}}

## Hyperliquid vs Binance proxy (same window, as coded, full cadence)

Hyperliquid's `candleSnapshot` only serves the latest 5000 candles: 208 days at 1h, 104 days at 30m (verified: requests older than that return `[]`). The multi-year runs use Binance USDT-M perps. On the overlap, return correlation is 0.996-0.999, median basis is 1-4 bps, and Hyperliquid's bar ranges are 2-7% narrower (`results/proxy_validation.csv`), so the proxy slightly over-triggers stops. Strategy results on the two feeds are near-identical:

{{HL}}

## Code issues found while wiring this up

Update: issue 1 is now fixed in all three executors (branch `claude/state-based-exits`, `docs/FORK_CHANGES.md` §8, verified by `backtest/verify_exit_fix.py`). The other issues remain open. All results above were produced before the change, so the line numbers below refer to that version. Rerunning `run_backtests.py` now replays the fixed executors.

| # | Location | Issue | Effect |
|---|---|---|---|
| 1 | `intraday_executor.py:151-154`, `aggressive_executor.py:156-159`, `hyperliquid_executor.py:248-254` | Exits fire only on the one-bar transition action (`sell_exit`, `cover_short`, flips). A skipped run turns the exit into `flat`, which `decide_trades` ignores while a position is open. | Root cause of 77/88 stop-closed positions. Positions are orphaned until the exchange stop fires. A state-based rule ("strategy flat and position open → close") removes the dependency on run timing. |
| 2 | `intraday_data_loader.py:47` (`end_ms = now`), consumed at `intraday_executor.py:108-113` and `aggressive_executor.py:109-114` via `iloc[-1]` | Hyperliquid returns the still-forming candle (verified: the last candle's close time `T` is after now). Live signals use a partial bar whose close is the current price. | Signals can appear and vanish within the bar (repaint). The backtest uses closed bars only, so live trades on bars the backtest never sees. Not lookahead, but a live/backtest mismatch, and it also drives the one-bar transition actions in issue 1. |
| 3 | `intraday_strategy.py:78-79, 85-86`; `aggressive_strategy.py:85-86, 94-95` | The strategy's internal stop uses the signal-bar close as entry, the current ATR (a moving stop), and is evaluated on close. The exchange stop uses the fill price and the ATR at entry, and is evaluated intrabar. | The two stops disagree. Anything that reads the strategy's `Signal` column as the trade path (dashboards, any naive backtest) misstates stop exits. This backtest uses the exchange stop as the binding one. |
| 4 | `backtester.py:131-133, 264-267` | `walk_forward` returns are `pos × lev × daily_ret`: no fees, no stops, and leverage re-set every day. The daily executor sets leverage once at entry and never adds. | The fee-free table above overstates what the bot can realize, most of all in aggressive mode, where pyramiding exists only as leverage changes the executor never trades. |
| 5 | `backtester.py:90, 96, 100` | Annualizes with 252 days for a 365-day market. "Sortino" divides by the std of negative returns rather than target-zero downside deviation. | Reported ratios are scaled differently from standard definitions. Ranking within the grid is mostly unaffected. |
| 6 | `aggressive_executor.py:54, 350` | Mid-cap pyramid add = 0.5% × $1,000 × 1.995 = $9.975, below Hyperliquid's $10 minimum. | Every mid-cap pyramid add is rejected (300 rejections as coded). The `FORK_CHANGES.md` sizing table lists the pyramid only at ~4x. |
| 7 | `aggressive_executor.py:370-375` | A pyramid add re-places the stop for the whole position at latest fill - mult × ATR. | If the add fills below the original entry, the stop on the now-larger position moves further away, so risk grows with each add. |
| 8 | `hmm_engine.py:161, 165` | `predict` / `predict_proba` run on a single observation, so the HMM's transition matrix never contributes. | The HMM behaves as a per-day Gaussian mixture classifier, and the 5-day confirmation smoothing does all the regime-persistence work. It is causal (no lookahead). |

Lookahead audit: no signal-shift or future-data issue found. Daily signals use bar *t*'s close and fill at *t+1*'s open. The HMM trains on [*t*-756, *t*) and labels *t*. Intraday indicators are causal (`sosfilt`, rolling windows). The mirror loops used for variants reproduce the original generators bar for bar (`signals.parity_check`: 6 intraday, 6 aggressive, and 4 daily configurations).

## Caveats

- **Economics, not just statistics.** At current sizing, expected net is about $41/yr (daily standard), $75/yr (daily aggressive), $10/yr (intraday), and -$83/yr (aggressive). Any paid runner costing more than these amounts is underwater even for the strategies that pass. Returns scale linearly with `capital × size%` until liquidity matters; Sortino does not change with scale.
- **Funding is excluded.** Mean hold times at full cadence: daily about 190-210 h, intraday 22 h, aggressive 11 h; throttled, 60-90 h. Each 10% APR of funding costs about 22 bps/trade for the daily bot (vs +485-638 bps net), 2.5 bps for intraday (vs +9.4: material), and 1.2 bps for aggressive.
- **Bull-market sample.** BTC returned +200% over the walk-forward window. The daily edge is regime-timed long exposure, and the throttled fast-bot "gains" are drift. In a sustained bear, expect the daily bot near zero, not positive.
- **Proxy data** for history before 2026-03-30 (1h) and 2026-07-12 (30m); validated above.
- **Executor defaults assumed:** max positions 2 / 4 / 4, all 7 coins per bot (no `*_COINS` split), no cross-bot netting, drawdown halts not modeled, size rounding to `szDecimals` ignored, capital fixed (the executors don't compound).
- **Stops that gap through** fill at the bar open minus 2 bps, which is slightly more conservative than "stop price minus 2 bps".
- **Path dependence:** live bots replay signals from a roughly 41-day window (1000 h of candles). The backtest replays from 2023-01-01. Simulated position state can differ at any given bar.
- **Walk-forward stitching:** OOS daily P&L includes carry-in from positions opened just before a window. Trade stats count trades by entry time. Net differs by about $4 between the two views for intraday.
- **"Beats random" threshold** is the 95th percentile (one-sided p < 0.05). That choice is mine; your rule didn't specify one.
