# Backtest report: daily, intraday, and aggressive bots

Generated 2026-10-24 from `backtest/` (rerun: `data_fetch.py` → `daily_wf.py` → `run_backtests.py` → `extra_checks.py` → `report_tables.py REPORT.template.md results/REPORT.md`). Every number below comes from `backtest/results/*.csv`.

## Verdict

**No bot earns paid infrastructure.** The daily bot passes your rule in both modes, but it already works on GitHub's free scheduler: losing 87.5% of its daily runs still leaves a positive Sortino. Most of the Sortino it does lose comes back from a free code fix, not from a paid runner (see "Fix the code, not the runner"). The intraday bot fails the random-entry test. The aggressive bot fails every test.

Rule applied: out-of-sample, fee-inclusive Sortino at full cadence > 0; Sortino at or above the 95th percentile of the random-entry control; positive annualized net after removing the single best trade.

| Bot              |   OOS Sortino (full cadence) |   Ann. net % |   Pctile vs random |   Random seeds | Random Sortino p50 / p95   |   Ann. net ex best trade % |   Trades | Sortino > 0   | Beats random (>=p95)   | Survives best-trade removal   | Earns infrastructure   |
|:-----------------|-----------------------------:|-------------:|-------------------:|---------------:|:---------------------------|---------------------------:|---------:|:--------------|:-----------------------|:------------------------------|:-----------------------|
| intraday         |                         0.71 |         1.03 |              94.50 |            200 | -0.04 / 0.71               |                       0.75 |     1937 | yes           | NO                     | yes                           | NO                     |
| aggressive       |                        -1.80 |        -9.19 |              68.00 |             50 | -2.17 / -1.16              |                      -9.64 |     6254 | NO            | NO                     | NO                            | NO                     |
| daily_standard   |                         3.16 |         2.02 |             100.00 |             50 | 1.20 / 2.68                |                       1.03 |      115 | yes           | yes                    | yes                           | YES                    |
| daily_aggressive |                         3.02 |         3.58 |              98.00 |             50 | 1.53 / 2.69                |                       2.13 |      167 | yes           | yes                    | yes                           | YES                    |

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

| bot        | cadence   |    runs |   trades |   net_usd |   costs_usd |   win_rate_pct |   pct_stop_exits |   median_hold_h |
|:-----------|:----------|--------:|---------:|----------:|------------:|---------------:|-----------------:|----------------:|
| aggressive | full      | 1680.00 |   224.00 |     -6.73 |       10.49 |          26.34 |            59.38 |            5.75 |
| aggressive | throttled |  168.00 |    81.50 |      3.18 |        3.87 |           9.96 |            86.03 |            5.62 |
| intraday   | full      |  840.00 |    68.00 |      5.11 |        1.56 |          29.41 |            45.59 |           14.50 |
| intraday   | throttled |  168.50 |    28.50 |      4.59 |        0.67 |          20.00 |            74.68 |           24.75 |

### Price of bad infrastructure (full cadence vs throttled, walk-forward OOS, pooled)

Throttled = one run every 5 h on average (geometric gaps), 20 seeds, median shown. The daily rows use per-slot delivery probability instead (0.5 and 0.125), because the daily cron has one slot per day. Those two rates are assumptions; no delivery data exists for the daily workflow.

| Bot              | Cadence               |   Ann. net % |   Ann. gross % |   Sortino |   Sharpe |   Max DD % |   Trades |   Win % |   Payoff |   Gross bps/trade |   Net bps/trade |   Cost % of gross |   Stop exits % |   Median hold h |   Mean hold h |
|:-----------------|:----------------------|-------------:|---------------:|----------:|---------:|-----------:|---------:|--------:|---------:|------------------:|----------------:|------------------:|---------------:|----------------:|--------------:|
| intraday         | full                  |         1.03 |           2.53 |      0.71 |     0.44 |      -4.76 |  1937.00 |   37.84 |     1.76 |             20.60 |            9.36 |             54.57 |          24.01 |           17.00 |         22.24 |
| intraday         | throttled_median      |         1.23 |           1.33 |      0.69 |     0.44 |      -3.77 |   539.50 |   25.89 |     3.27 |             39.30 |           27.66 |             29.61 |          63.44 |           32.00 |         92.68 |
| aggressive       | full                  |        -9.19 |           0.71 |     -1.80 |    -1.20 |     -29.33 |  6254.00 |   32.72 |     1.82 |              0.83 |          -10.51 |           1287.96 |          33.99 |            8.50 |         10.65 |
| aggressive       | throttled_median      |         4.02 |           6.92 |      0.95 |     0.60 |     -12.04 |  1564.50 |   18.27 |     4.96 |             42.52 |           30.74 |             32.17 |          76.14 |           14.50 |         58.82 |
| daily_standard   | full                  |         2.02 |           2.06 |      3.16 |     1.59 |      -1.00 |   115.00 |   43.48 |     4.98 |            649.67 |          638.30 |              1.75 |           0.87 |           72.00 |        188.66 |
| daily_standard   | delivery_0.5_median   |         1.99 |           2.01 |      1.93 |     1.15 |      -1.83 |    64.00 |   44.64 |     4.62 |           1102.29 |         1090.53 |              1.07 |          14.29 |          318.00 |        573.70 |
| daily_standard   | delivery_0.125_median |         1.77 |           1.78 |      1.28 |     0.82 |      -2.15 |    33.50 |   38.93 |     4.96 |           1988.37 |         1975.92 |              0.63 |          34.33 |          768.00 |       1224.43 |
| daily_aggressive | full                  |         3.58 |           3.66 |      3.02 |     1.60 |      -1.81 |   167.00 |   44.91 |     3.42 |            496.19 |          484.93 |              2.46 |           2.99 |          144.00 |        210.40 |
| daily_aggressive | delivery_0.5_median   |         4.28 |           4.34 |      2.03 |     1.24 |      -3.06 |   101.00 |   45.89 |     3.54 |            898.87 |          887.34 |              1.29 |          15.86 |          312.00 |        566.16 |
| daily_aggressive | delivery_0.125_median |         4.80 |           4.83 |      1.50 |     0.99 |      -5.55 |    51.00 |   44.20 |     4.84 |           2064.88 |         2052.58 |              0.65 |          29.17 |          636.00 |       1270.37 |

Seed distributions (p10 / p50 / p90):

| Bot              | Scenario                        |   Seeds | Ann. net % p10 / p50 / p90   | Sortino p10 / p50 / p90   |   Stop exits % p50 |   Trades p50 |   Net bps/trade p50 |
|:-----------------|:--------------------------------|--------:|:-----------------------------|:--------------------------|-------------------:|-------------:|--------------------:|
| aggressive       | as_coded_full_history           |      20 | -0.94 / 1.62 / 3.41          | -0.13 / 0.40 / 0.82       |              72.01 |      1816.50 |               13.74 |
| aggressive       | walk_forward_oos                |      20 | 2.39 / 4.02 / 6.60           | 0.58 / 0.95 / 1.59        |              76.14 |      1564.50 |               30.74 |
| daily_aggressive | walk_forward_oos_delivery_0.125 |      20 | 3.65 / 4.80 / 5.87           | 0.95 / 1.50 / 1.94        |              29.17 |        51.00 |             2052.58 |
| daily_aggressive | walk_forward_oos_delivery_0.5   |      20 | 3.60 / 4.28 / 5.95           | 1.71 / 2.03 / 2.48        |              15.86 |       101.00 |              887.34 |
| daily_standard   | walk_forward_oos_delivery_0.125 |      20 | 0.92 / 1.77 / 2.37           | 0.72 / 1.28 / 1.69        |              34.33 |        33.50 |             1975.92 |
| daily_standard   | walk_forward_oos_delivery_0.5   |      20 | 1.60 / 1.99 / 2.46           | 1.59 / 1.93 / 2.41        |              14.29 |        64.00 |             1090.53 |
| intraday         | as_coded_full_history           |      20 | -0.27 / 0.98 / 2.11          | -0.13 / 0.65 / 1.36       |              59.62 |       701.50 |               25.70 |
| intraday         | walk_forward_oos                |      20 | 0.35 / 1.23 / 2.26           | 0.20 / 0.69 / 1.49        |              63.44 |       539.50 |               27.66 |

How to read the gap: for daily standard, full cadence buys at most 0.25 points/yr of return and 1.2-1.9 points of Sortino. Daily aggressive actually earns more when throttled, from the same missed-exit drift. For the intraday bot, cadence buys nothing (Sortino 0.71 vs 0.69). For the aggressive bot, more cadence loses money faster.

### Fix the code, not the runner

This tests a backtest-only wrapper around each executor's `decide_trades`: it also closes any open position whose current strategy signal no longer matches it, which fixes code issue 1. As-coded parameters. Full-cadence rows are identical with and without the fix, as they should be: at every-bar cadence no transition is ever missed. At throttled cadence, the fix pulls the fast bots back to their (edge-less) full-cadence results, which confirms their throttled "gains" were missed-exit drift. For the daily bot, it recovers most of the Sortino lost to skipped runs, at no cost.

| bot              | cadence        | exit_rule       |   ann_net_pct |   sortino |   trades |   pct_stop_exits |   avg_net_bps |   median_hold_h |
|:-----------------|:---------------|:----------------|--------------:|----------:|---------:|-----------------:|--------------:|----------------:|
| aggressive       | full           | as_coded        |        -13.05 |     -2.16 |  8243.00 |            25.68 |        -11.96 |            8.50 |
| aggressive       | full           | state_based_fix |        -13.05 |     -2.16 |  8243.00 |            25.68 |        -11.96 |            8.50 |
| aggressive       | throttled      | as_coded        |          1.62 |      0.40 |  1816.50 |            72.01 |         13.74 |           19.50 |
| aggressive       | throttled      | state_based_fix |         -6.24 |     -1.35 |  5149.50 |            36.73 |         -7.96 |           10.50 |
| daily_aggressive | delivery_0.125 | as_coded        |          4.80 |      1.50 |    51.00 |            29.17 |       2052.58 |          636.00 |
| daily_aggressive | delivery_0.125 | state_based_fix |          2.99 |      2.12 |    77.50 |            11.48 |        679.97 |          312.00 |
| daily_aggressive | delivery_0.5   | as_coded        |          4.28 |      2.03 |   101.00 |            15.86 |        887.34 |          312.00 |
| daily_aggressive | delivery_0.5   | state_based_fix |          3.39 |      2.80 |   130.00 |             5.99 |        568.54 |          216.00 |
| daily_aggressive | full           | as_coded        |          3.58 |      3.02 |   167.00 |             2.99 |        484.93 |          144.00 |
| daily_aggressive | full           | state_based_fix |          3.58 |      3.02 |   167.00 |             2.99 |        484.93 |          144.00 |
| daily_standard   | delivery_0.125 | as_coded        |          1.77 |      1.28 |    33.50 |            34.33 |       1975.92 |          768.00 |
| daily_standard   | delivery_0.125 | state_based_fix |          1.18 |      1.75 |    47.50 |             9.01 |        877.39 |          336.00 |
| daily_standard   | delivery_0.5   | as_coded        |          1.99 |      1.93 |    64.00 |            14.29 |       1090.53 |          318.00 |
| daily_standard   | delivery_0.5   | state_based_fix |          1.79 |      2.78 |    82.00 |             3.49 |        764.56 |          192.00 |
| daily_standard   | full           | as_coded        |          2.02 |      3.16 |   115.00 |             0.87 |        638.30 |           72.00 |
| daily_standard   | full           | state_based_fix |          2.02 |      3.16 |   115.00 |             0.87 |        638.30 |           72.00 |
| intraday         | full           | as_coded        |         -0.45 |     -0.25 |  2657.00 |            23.52 |         -2.97 |           16.00 |
| intraday         | full           | state_based_fix |         -0.45 |     -0.25 |  2657.00 |            23.52 |         -2.97 |           16.00 |
| intraday         | throttled      | as_coded        |          0.98 |      0.65 |   701.50 |            59.62 |         25.70 |           36.00 |
| intraday         | throttled      | state_based_fix |         -0.33 |     -0.21 |  2000.50 |            29.58 |         -2.94 |           19.00 |

## Baselines

Fully invested buy-and-hold over the same windows, yfinance daily closes, one entry fee. The bots deploy 1-6% of capital per position, so compare Sortino, not return. A mostly-flat equity curve also inflates Sortino, which is why the random-entry control (same exits, same exposure profile) is the binding comparison, not buy-and-hold.

| window           | start      | end        | baseline       |   ann_net_pct |   sharpe |   sortino |   max_dd_pct |   total_return_pct |
|:-----------------|:-----------|:-----------|:---------------|--------------:|---------:|----------:|-------------:|-------------------:|
| full_history     | 2023-04-01 | 2026-10-23 | buy_hold_BTC   |         34.15 |     0.87 |      1.33 |       -53.06 |             185.20 |
| full_history     | 2023-04-01 | 2026-10-23 | equal_weight_7 |         25.56 |     0.67 |      0.99 |       -70.82 |             125.22 |
| walk_forward_oos | 2023-09-30 | 2026-10-23 | buy_hold_BTC   |         43.12 |     1.00 |      1.53 |       -53.06 |             200.47 |
| walk_forward_oos | 2023-09-30 | 2026-10-23 | equal_weight_7 |         39.33 |     0.83 |      1.23 |       -70.82 |             176.72 |

Random-entry controls: coin-flip entries at each strategy's own entry rate per flat bar, per asset, with the strategy's exact exit rules, stops, pyramids, and executor logic. 50 seeds, plus 200 for the intraday walk-forward.

| bot              | scenario           |   strategy_sortino |   random_sortino_p05 |   random_sortino_median |   random_sortino_p95 |   strategy_pctile_vs_random |   strategy_ann_net_pct |   random_ann_net_median |   strategy_trades |   random_trades_median |
|:-----------------|:-------------------|-------------------:|---------------------:|------------------------:|---------------------:|----------------------------:|-----------------------:|------------------------:|------------------:|-----------------------:|
| intraday         | as_coded_full      |              -0.25 |                -0.97 |                   -0.33 |                 0.29 |                       54.00 |                  -0.45 |                   -0.58 |           2657.00 |                2668.00 |
| intraday         | as_coded_throttled |               0.65 |                -0.20 |                    0.49 |                 1.30 |                       54.00 |                   0.98 |                    0.87 |            701.50 |                 717.50 |
| intraday         | walk_forward_full  |               0.71 |                -0.94 |                   -0.05 |                 0.50 |                       96.00 |                   1.03 |                   -0.11 |           1937.00 |                2134.50 |
| aggressive       | as_coded_full      |              -2.16 |                -2.79 |                   -2.24 |                -1.67 |                       62.00 |                 -13.05 |                  -12.18 |           8243.00 |                8091.50 |
| aggressive       | as_coded_throttled |               0.40 |                -0.21 |                    0.40 |                 1.05 |                       48.00 |                   1.62 |                    1.58 |           1816.50 |                1824.00 |
| aggressive       | walk_forward_full  |              -1.80 |                -2.99 |                   -2.17 |                -1.16 |                       68.00 |                  -9.19 |                   -9.80 |           6254.00 |                6519.00 |
| daily_standard   | walk_forward_full  |               3.16 |                 0.19 |                    1.20 |                 2.68 |                      100.00 |                   2.02 |                    0.57 |            115.00 |                 119.50 |
| daily_aggressive | walk_forward_full  |               3.02 |                 0.58 |                    1.53 |                 2.69 |                       98.00 |                   3.58 |                    1.48 |            167.00 |                 175.50 |

| bot      | scenario          |   seeds |   strategy_sortino |   random_median |   random_p95 |   random_p99 |   seeds_beating_strategy |   strategy_pctile |
|:---------|:------------------|--------:|-------------------:|----------------:|-------------:|-------------:|-------------------------:|------------------:|
| intraday | walk_forward_full |     200 |               0.71 |           -0.04 |         0.71 |         0.90 |                       11 |             94.50 |

## Daily strategy (walk_forward params, fee-inclusive executor replay)

Parameters per fold come from the repo's own `backtester.walk_forward()` (252-day in-sample, 63-day out-of-sample, Sortino-optimized over 432 combos). OOS signals are regenerated per fold exactly as `walk_forward` does, then replayed through `hyperliquid_executor.decide_trades` with exchange stops (3x large cap, 4x mid cap ATR), next-open fills, fees, and max 4 positions on $2,000. Evaluation window starts 2023-04-01, when the HMM first has 365 days of training data.

Standard mode, per asset:

| Asset   |   Ann. net % |   Ann. gross % |   Sortino |   Sharpe |   Max DD % |   Trades |   Win % |   Avg win $ |   Avg loss $ |   Payoff |   Net bps/trade |   Cost % of gross |   Stop % |   Med hold h |   Ann. net ex-best % |   Long net $ |   Short net $ |
|:--------|-------------:|---------------:|----------:|---------:|-----------:|---------:|--------:|------------:|-------------:|---------:|----------------:|------------------:|---------:|-------------:|---------------------:|-------------:|--------------:|
| POOLED  |         2.02 |           2.06 |      3.16 |     1.59 |      -1.00 |   115.00 |   43.48 |        3.97 |        -0.80 |     4.98 |          638.30 |              1.75 |     0.87 |        72.00 |                 1.03 |       146.81 |          0.00 |
| BTC     |         0.16 |           0.17 |      1.98 |     1.03 |      -0.19 |    22.00 |   45.45 |        1.69 |        -0.46 |     3.68 |          259.27 |              4.12 |     0.00 |        96.00 |                 0.09 |        11.41 |          0.00 |
| ETH     |         0.36 |           0.36 |      2.42 |     1.14 |      -0.32 |    19.00 |   52.63 |        3.11 |        -0.65 |     4.77 |          664.81 |              1.68 |     0.00 |        72.00 |                 0.19 |        25.26 |          0.00 |
| SOL     |        -0.02 |          -0.02 |     -0.33 |    -0.25 |      -0.19 |     3.00 |   33.33 |        0.26 |        -1.01 |     0.26 |         -292.84 |              3.85 |     0.00 |       264.00 |                -0.03 |        -1.76 |          0.00 |
| AVAX    |         0.20 |           0.21 |      0.78 |     0.47 |      -0.40 |    18.00 |   33.33 |        4.16 |        -0.87 |     4.78 |          402.93 |              2.71 |     0.00 |        24.00 |                -0.02 |        14.51 |          0.00 |
| LINK    |         0.13 |           0.14 |      0.54 |     0.33 |      -0.73 |    30.00 |   43.33 |        2.14 |        -1.10 |     1.95 |          152.08 |              6.80 |     0.00 |        48.00 |                -0.09 |         9.12 |          0.00 |
| SUI     |         0.02 |           0.02 |      0.16 |     0.09 |      -0.36 |     6.00 |   33.33 |        2.73 |        -0.98 |     2.77 |          126.82 |              8.03 |     0.00 |       192.00 |                -0.05 |         1.52 |          0.00 |
| XRP     |         1.21 |           1.21 |      4.67 |     1.40 |      -0.38 |    17.00 |   47.06 |       11.52 |        -0.60 |    19.23 |         2551.30 |              0.49 |     5.88 |       144.00 |                 0.19 |        86.74 |          0.00 |

Aggressive mode, per asset:

| Asset   |   Ann. net % |   Ann. gross % |   Sortino |   Sharpe |   Max DD % |   Trades |   Win % |   Avg win $ |   Avg loss $ |   Payoff |   Net bps/trade |   Cost % of gross |   Stop % |   Med hold h |   Ann. net ex-best % |   Long net $ |   Short net $ |
|:--------|-------------:|---------------:|----------:|---------:|-----------:|---------:|--------:|------------:|-------------:|---------:|----------------:|------------------:|---------:|-------------:|---------------------:|-------------:|--------------:|
| POOLED  |         3.58 |           3.66 |      3.02 |     1.60 |      -1.81 |   167.00 |   44.91 |        5.51 |        -1.61 |     3.42 |          484.93 |              2.46 |     2.99 |       144.00 |                 2.13 |       254.19 |         10.63 |
| BTC     |         0.46 |           0.49 |      1.44 |     0.85 |      -0.76 |    38.00 |   42.11 |        4.28 |        -1.63 |     2.63 |          179.23 |              5.85 |     7.89 |       168.00 |                 0.24 |        31.58 |          1.04 |
| ETH     |         0.87 |           0.89 |      1.77 |     0.94 |      -0.80 |    37.00 |   51.35 |        5.04 |        -1.86 |     2.71 |          419.04 |              2.75 |     2.70 |       144.00 |                 0.38 |        52.71 |          9.59 |
| SOL     |         0.04 |           0.05 |      0.21 |     0.14 |      -0.39 |    16.00 |   50.00 |        2.30 |        -1.94 |     1.18 |          101.27 |             11.90 |     0.00 |       264.00 |                -0.05 |         2.86 |          0.00 |
| AVAX    |         0.31 |           0.32 |      0.77 |     0.48 |      -0.84 |    23.00 |   34.78 |        5.25 |        -1.33 |     3.94 |          353.79 |              3.20 |     0.00 |        24.00 |                -0.03 |        22.04 |          0.00 |
| LINK    |         0.15 |           0.16 |      0.44 |     0.28 |      -1.03 |    30.00 |   46.67 |        2.86 |        -1.84 |     1.56 |          149.34 |              8.03 |     0.00 |       108.00 |                -0.07 |        10.65 |          0.00 |
| SUI     |         0.03 |           0.04 |      0.16 |     0.09 |      -0.54 |     6.00 |   33.33 |        4.09 |        -1.48 |     2.77 |          126.82 |              8.03 |     0.00 |       192.00 |                -0.07 |         2.28 |          0.00 |
| XRP     |         1.82 |           1.83 |      4.56 |     1.41 |      -0.56 |    17.00 |   47.06 |       17.53 |        -0.91 |    19.31 |         2568.77 |              0.49 |     5.88 |       144.00 |                 0.32 |       132.06 |          0.00 |

For reference, `walk_forward()`'s own fee-free numbers. They assume full capital at 1x per asset, re-leverage daily, and ignore stops and fees, so they are not comparable in size to the replay. Its OOS ends at 2026-08-24 for most assets, because it drops the final partial fold.

| coin   | mode       | oos_start   | oos_end    |   folds |   total_return |   max_drawdown |   sharpe_252 |   sortino_252 |   pct_days_in_market |
|:-------|:-----------|:------------|:-----------|--------:|---------------:|---------------:|-------------:|--------------:|---------------------:|
| BTC    | standard   | 2022-11-08  | 2026-08-24 |      22 |           0.61 |          -0.14 |         0.79 |          0.57 |                 0.13 |
| BTC    | aggressive | 2022-11-08  | 2026-08-24 |      22 |           1.21 |          -0.58 |         0.54 |          0.45 |                 0.27 |
| ETH    | standard   | 2022-11-08  | 2026-08-24 |      22 |           1.92 |          -0.20 |         1.02 |          0.85 |                 0.13 |
| ETH    | aggressive | 2022-11-08  | 2026-08-24 |      22 |          12.98 |          -0.65 |         0.93 |          0.93 |                 0.28 |
| SOL    | standard   | 2022-11-08  | 2026-08-24 |      22 |          -0.16 |          -0.20 |        -0.29 |         -0.08 |                 0.03 |
| SOL    | aggressive | 2022-11-08  | 2026-08-24 |      22 |          -0.19 |          -0.37 |        -0.02 |         -0.01 |                 0.12 |
| AVAX   | standard   | 2022-11-08  | 2026-08-24 |      22 |           0.83 |          -0.30 |         0.54 |          0.35 |                 0.11 |
| AVAX   | aggressive | 2022-11-08  | 2026-08-24 |      22 |           1.72 |          -0.43 |         0.59 |          0.37 |                 0.11 |
| LINK   | standard   | 2022-11-08  | 2026-08-24 |      22 |           0.34 |          -0.39 |         0.33 |          0.25 |                 0.13 |
| LINK   | aggressive | 2022-11-08  | 2026-08-24 |      22 |          -0.10 |          -0.76 |         0.19 |          0.13 |                 0.16 |
| SUI    | standard   | 2024-01-10  | 2026-10-13 |      16 |           0.05 |          -0.30 |         0.16 |          0.08 |                 0.05 |
| SUI    | aggressive | 2024-01-10  | 2026-10-13 |      16 |          -0.10 |          -0.51 |         0.10 |          0.05 |                 0.05 |
| XRP    | standard   | 2022-11-08  | 2026-08-24 |      22 |          11.27 |          -0.21 |         1.22 |          1.44 |                 0.12 |
| XRP    | aggressive | 2022-11-08  | 2026-08-24 |      22 |          70.38 |          -0.37 |         1.29 |          1.36 |                 0.12 |

## Intraday (1h) and aggressive (30m)

### Full-history grid at full cadence (2023-04-01 to 2026-10-24, pooled, 7 coins)

Each pair replaces both the strategy's `osc_upper/osc_lower`/`atr_stop_mult` and the executor's exchange stop multiplier. Intraday:

|   Thr |   Stop |   Ann. net % |   Ann. gross % |   Sortino |   Trades |   Win % |   Gross bps |   Net bps |   Stop % |   Med hold h |
|------:|-------:|-------------:|---------------:|----------:|---------:|--------:|------------:|----------:|---------:|-------------:|
|  0.25 |   1.50 |        -0.73 |           1.34 |     -0.46 |  3230.00 |   29.57 |        7.52 |     -3.99 |    50.80 |         9.00 |
|  0.25 |   2.00 |         0.16 |           2.03 |      0.12 |  3023.00 |   33.58 |       12.30 |      0.92 |    38.07 |        12.00 |
|  0.25 |   3.00 |        -0.51 |           1.22 |     -0.29 |  2771.00 |   36.67 |        7.97 |     -3.24 |    21.22 |        15.00 |
|  0.25 |   4.00 |         0.39 |           1.97 |      0.26 |  2618.00 |   38.20 |       13.80 |      2.68 |    12.30 |        17.00 |
|  0.50 |   1.50 |        -0.07 |           1.86 |     -0.03 |  3071.00 |   28.92 |       11.08 |     -0.43 |    51.74 |         9.00 |
|  0.50 |   2.00 |        -0.27 |           1.54 |     -0.15 |  2879.00 |   32.34 |        9.73 |     -1.67 |    39.70 |        13.00 |
|  0.50 |   3.00 |        -0.45 |           1.21 |     -0.25 |  2657.00 |   35.83 |        8.26 |     -2.97 |    23.52 |        16.00 |
|  0.50 |   4.00 |         0.45 |           1.96 |      0.30 |  2492.00 |   37.92 |       14.37 |      3.23 |    13.64 |        18.00 |
|  1.00 |   1.50 |         0.54 |           2.05 |      0.43 |  2415.00 |   30.02 |       15.53 |      4.00 |    52.84 |        10.00 |
|  1.00 |   2.00 |         0.73 |           2.15 |      0.56 |  2297.00 |   33.96 |       17.14 |      5.74 |    40.01 |        14.00 |
|  1.00 |   3.00 |         1.20 |           2.47 |      0.85 |  2113.00 |   38.38 |       21.51 |     10.26 |    25.18 |        19.00 |
|  1.00 |   4.00 |         1.98 |           3.17 |      1.38 |  2020.00 |   40.94 |       29.14 |     17.99 |    14.41 |        20.00 |

Aggressive:

|   Thr |   Stop |   Ann. net % |   Ann. gross % |   Sortino |   Trades |   Win % |   Gross bps |   Net bps |   Stop % |   Med hold h |
|------:|-------:|-------------:|---------------:|----------:|---------:|--------:|------------:|----------:|---------:|-------------:|
|  0.25 |   1.50 |       -12.10 |           1.34 |     -2.54 |  9020.00 |   27.47 |        0.68 |    -10.88 |    56.41 |         5.00 |
|  0.25 |   2.00 |       -11.08 |           1.43 |     -2.16 |  8674.00 |   31.01 |        0.79 |    -10.64 |    43.53 |         7.00 |
|  0.25 |   3.00 |       -13.05 |          -0.76 |     -2.16 |  8243.00 |   33.87 |       -0.71 |    -11.96 |    25.68 |         8.50 |
|  0.25 |   4.00 |       -12.80 |          -1.01 |     -2.11 |  7987.00 |   34.97 |       -0.46 |    -11.60 |    15.14 |         9.00 |
|  0.50 |   1.50 |       -12.64 |           0.15 |     -2.72 |  8381.00 |   27.09 |       -0.52 |    -12.10 |    57.79 |         5.00 |
|  0.50 |   2.00 |       -11.24 |           0.57 |     -2.32 |  8063.00 |   30.68 |        0.05 |    -11.40 |    45.34 |         7.00 |
|  0.50 |   3.00 |        -9.39 |           1.19 |     -1.80 |  7598.00 |   34.50 |       -0.27 |    -11.54 |    27.76 |         9.00 |
|  0.50 |   4.00 |       -10.25 |           0.14 |     -1.92 |  7336.00 |   36.16 |       -0.43 |    -11.59 |    17.08 |        10.00 |
|  1.00 |   1.50 |        -9.98 |          -0.36 |     -2.66 |  6447.00 |   26.59 |       -0.09 |    -11.67 |    58.71 |         5.50 |
|  1.00 |   2.00 |        -9.05 |          -0.02 |     -2.18 |  6250.00 |   30.67 |        1.46 |    -10.01 |    46.99 |         7.50 |
|  1.00 |   3.00 |       -10.01 |          -1.33 |     -2.14 |  5936.00 |   35.44 |       -0.45 |    -11.75 |    30.14 |        10.00 |
|  1.00 |   4.00 |        -7.93 |          -0.03 |     -1.69 |  5677.00 |   37.52 |        1.44 |     -9.76 |    19.92 |        11.00 |

Throttled-cadence Sortino (median of 20 seeds), intraday then aggressive:

| threshold   |   stop 1.5x |   stop 2.0x |   stop 3.0x |   stop 4.0x |
|:------------|------------:|------------:|------------:|------------:|
| +/-0.25     |        0.13 |        0.53 |        0.80 |        1.09 |
| +/-0.5      |        0.33 |        0.34 |        0.65 |        0.71 |
| +/-1.0      |        0.33 |        0.77 |        0.85 |        0.93 |

| threshold   |   stop 1.5x |   stop 2.0x |   stop 3.0x |   stop 4.0x |
|:------------|------------:|------------:|------------:|------------:|
| +/-0.25     |        0.05 |        0.53 |        0.40 |        0.15 |
| +/-0.5      |        0.04 |        0.19 |        0.48 |        0.70 |
| +/-1.0      |        0.41 |        0.41 |        0.72 |        0.77 |

### Walk-forward selection (182-day IS, 61-day OOS, pick by pooled IS Sortino at full cadence)

Intraday:

| oos_start   | oos_end    |   thr |   stop_mult |   is_sortino |
|:------------|:-----------|------:|------------:|-------------:|
| 2023-09-30  | 2023-11-30 |  0.50 |        4.00 |         1.27 |
| 2023-11-30  | 2024-01-30 |  0.50 |        4.00 |         3.79 |
| 2024-01-30  | 2024-03-31 |  1.00 |        3.00 |         4.07 |
| 2024-03-31  | 2024-05-31 |  0.25 |        1.50 |         2.45 |
| 2024-05-31  | 2024-07-31 |  1.00 |        3.00 |         0.18 |
| 2024-07-31  | 2024-09-30 |  0.25 |        3.00 |        -1.19 |
| 2024-09-30  | 2024-11-30 |  1.00 |        4.00 |         0.60 |
| 2024-11-30  | 2025-01-30 |  0.50 |        4.00 |         5.09 |
| 2025-01-30  | 2025-04-01 |  1.00 |        4.00 |         5.06 |
| 2025-04-01  | 2025-06-01 |  1.00 |        4.00 |         3.66 |
| 2025-06-01  | 2025-08-01 |  1.00 |        4.00 |         1.26 |
| 2025-08-01  | 2025-10-01 |  1.00 |        4.00 |         1.80 |
| 2025-10-01  | 2025-12-01 |  1.00 |        4.00 |         2.35 |
| 2025-12-01  | 2026-01-31 |  1.00 |        4.00 |        -0.35 |
| 2026-01-31  | 2026-04-02 |  1.00 |        4.00 |        -0.80 |
| 2026-04-02  | 2026-06-02 |  1.00 |        2.00 |         0.08 |
| 2026-06-02  | 2026-08-02 |  1.00 |        2.00 |         5.43 |
| 2026-08-02  | 2026-10-02 |  1.00 |        2.00 |         2.33 |
| 2026-10-02  | 2026-10-24 |  1.00 |        1.50 |         3.22 |

Aggressive:

| oos_start   | oos_end    |   thr |   stop_mult |   is_sortino |
|:------------|:-----------|------:|------------:|-------------:|
| 2023-09-30  | 2023-11-30 |  1.00 |        3.00 |        -1.04 |
| 2023-11-30  | 2024-01-30 |  1.00 |        2.00 |         0.59 |
| 2024-01-30  | 2024-03-31 |  1.00 |        4.00 |        -0.01 |
| 2024-03-31  | 2024-05-31 |  0.50 |        4.00 |         0.87 |
| 2024-05-31  | 2024-07-31 |  0.25 |        1.50 |         0.79 |
| 2024-07-31  | 2024-09-30 |  0.50 |        3.00 |        -0.33 |
| 2024-09-30  | 2024-11-30 |  1.00 |        3.00 |         0.09 |
| 2024-11-30  | 2025-01-30 |  1.00 |        3.00 |         0.88 |
| 2025-01-30  | 2025-04-01 |  1.00 |        3.00 |         0.74 |
| 2025-04-01  | 2025-06-01 |  1.00 |        4.00 |         0.47 |
| 2025-06-01  | 2025-08-01 |  1.00 |        4.00 |         0.47 |
| 2025-08-01  | 2025-10-01 |  0.50 |        3.00 |         0.93 |
| 2025-10-01  | 2025-12-01 |  0.25 |        1.50 |         1.19 |
| 2025-12-01  | 2026-01-31 |  0.25 |        1.50 |        -1.14 |
| 2026-01-31  | 2026-04-02 |  0.25 |        2.00 |        -3.69 |
| 2026-04-02  | 2026-06-02 |  0.25 |        2.00 |        -4.52 |
| 2026-06-02  | 2026-08-02 |  0.25 |        3.00 |        -3.47 |
| 2026-08-02  | 2026-10-02 |  0.25 |        4.00 |        -4.00 |
| 2026-10-02  | 2026-10-24 |  0.25 |        4.00 |        -1.24 |

### Walk-forward OOS, per asset, full cadence

Intraday:

| Asset   |   Ann. net % |   Ann. gross % |   Sortino |   Sharpe |   Max DD % |   Trades |   Win % |   Avg win $ |   Avg loss $ |   Payoff |   Net bps/trade |   Cost % of gross |   Stop % |   Med hold h |   Ann. net ex-best % |   Long net $ |   Short net $ |
|:--------|-------------:|---------------:|----------:|---------:|-----------:|---------:|--------:|------------:|-------------:|---------:|----------------:|------------------:|---------:|-------------:|---------------------:|-------------:|--------------:|
| POOLED  |         1.03 |           2.53 |      0.71 |     0.44 |      -4.76 |  1937.00 |   37.84 |        0.73 |        -0.42 |     1.76 |            9.36 |             54.57 |    24.01 |        17.00 |                 0.75 |        28.68 |          7.58 |
| BTC     |         0.25 |           0.52 |      0.81 |     0.47 |      -0.84 |   355.00 |   40.00 |        0.44 |        -0.26 |     1.72 |           11.24 |             50.01 |    23.94 |        20.00 |                 0.17 |         3.29 |          4.68 |
| ETH     |         0.24 |           0.49 |      0.58 |     0.32 |      -1.46 |   341.00 |   33.72 |        0.76 |        -0.35 |     2.15 |           10.89 |             50.89 |    27.86 |        19.00 |                 0.07 |         4.52 |          2.90 |
| SOL     |         1.38 |           1.58 |      3.31 |     1.59 |      -0.62 |   260.00 |   45.38 |        0.85 |        -0.40 |     2.12 |           83.54 |             11.86 |    19.62 |        17.00 |                 1.23 |        43.44 |          0.00 |
| AVAX    |        -0.31 |          -0.10 |     -0.57 |    -0.36 |      -1.45 |   259.00 |   38.22 |        0.75 |        -0.52 |     1.44 |          -16.94 |            196.96 |    24.71 |        19.00 |                -0.42 |        -8.77 |          0.00 |
| LINK    |        -0.25 |          -0.09 |     -0.53 |    -0.35 |      -1.48 |   228.00 |   37.28 |        0.72 |        -0.48 |     1.49 |          -17.29 |            183.85 |    21.05 |        15.00 |                -0.39 |        -7.88 |          0.00 |
| SUI     |        -0.75 |          -0.46 |     -1.31 |    -0.81 |      -2.82 |   245.00 |   31.84 |        0.98 |        -0.58 |     1.70 |          -39.98 |             39.00 |    24.49 |        15.00 |                -0.98 |       -19.59 |          0.00 |
| XRP     |         0.44 |           0.62 |      1.05 |     0.58 |      -1.22 |   249.00 |   38.55 |        0.79 |        -0.40 |     1.95 |           27.45 |             29.10 |    24.90 |        17.00 |                 0.15 |        13.67 |          0.00 |

Aggressive:

| Asset   |   Ann. net % |   Ann. gross % |   Sortino |   Sharpe |   Max DD % |   Trades |   Win % |   Avg win $ |   Avg loss $ |   Payoff |   Net bps/trade |   Cost % of gross |   Stop % |   Med hold h |   Ann. net ex-best % |   Long net $ |   Short net $ |
|:--------|-------------:|---------------:|----------:|---------:|-----------:|---------:|--------:|------------:|-------------:|---------:|----------------:|------------------:|---------:|-------------:|---------------------:|-------------:|--------------:|
| POOLED  |        -9.19 |           0.71 |     -1.80 |    -1.20 |     -29.33 |  6254.00 |   32.72 |        0.98 |        -0.54 |     1.82 |          -10.51 |           1287.96 |    33.99 |         8.50 |                -9.64 |      -159.05 |       -101.22 |
| BTC     |        -2.47 |          -0.16 |     -2.07 |    -1.31 |      -8.86 |   996.00 |   31.12 |        0.96 |        -0.54 |     1.77 |          -12.03 |           1381.60 |    35.24 |         8.50 |                -2.66 |        -6.43 |        -67.20 |
| ETH     |        -1.71 |           0.55 |     -1.07 |    -0.62 |      -6.90 |  1006.00 |   33.50 |        1.33 |        -0.75 |     1.78 |           -8.85 |            410.77 |    36.28 |         9.00 |                -2.10 |       -18.50 |        -34.02 |
| SOL     |        -0.81 |           0.15 |     -0.88 |    -0.52 |      -3.44 |   864.00 |   33.80 |        0.86 |        -0.48 |     1.78 |           -9.49 |            616.12 |    33.45 |         8.00 |                -1.01 |       -24.54 |          0.00 |
| AVAX    |        -0.76 |           0.15 |     -0.79 |    -0.48 |      -3.73 |   863.00 |   34.41 |        0.89 |        -0.51 |     1.74 |           -9.53 |            630.56 |    33.37 |         8.50 |                -0.94 |       -24.61 |          0.00 |
| LINK    |        -0.86 |           0.04 |     -0.93 |    -0.56 |      -4.12 |   848.00 |   32.90 |        0.86 |        -0.47 |     1.83 |          -10.81 |           2205.78 |    32.90 |         8.50 |                -1.05 |       -27.43 |          0.00 |
| SUI     |        -0.08 |           0.84 |     -0.05 |    -0.03 |      -3.12 |   856.00 |   33.18 |        1.20 |        -0.60 |     2.00 |           -1.18 |            111.61 |    31.78 |         9.00 |                -0.42 |        -3.01 |          0.00 |
| XRP     |        -1.81 |          -0.88 |     -2.23 |    -1.39 |      -5.83 |   821.00 |   30.09 |        0.68 |        -0.39 |     1.76 |          -22.19 |            104.31 |    34.35 |         8.00 |                -2.04 |       -54.53 |          0.00 |

### As coded (intraday ±0.5 / 3x, aggressive ±0.25 / 3x), per asset, full cadence

| Asset   |   Ann. net % |   Ann. gross % |   Sortino |   Sharpe |   Max DD % |   Trades |   Win % |   Avg win $ |   Avg loss $ |   Payoff |   Net bps/trade |   Cost % of gross |   Stop % |   Med hold h |   Ann. net ex-best % |   Long net $ |   Short net $ |
|:--------|-------------:|---------------:|----------:|---------:|-----------:|---------:|--------:|------------:|-------------:|---------:|----------------:|------------------:|---------:|-------------:|---------------------:|-------------:|--------------:|
| BTC     |        -0.16 |           0.13 |     -0.50 |    -0.29 |      -1.48 |   462.00 |   35.06 |        0.42 |        -0.25 |     1.71 |           -6.15 |            220.75 |    24.24 |        18.00 |                -0.24 |        -0.47 |         -5.21 |
| ETH     |        -0.41 |          -0.12 |     -0.93 |    -0.57 |      -2.15 |   459.00 |   33.12 |        0.60 |        -0.35 |     1.74 |          -15.78 |            252.32 |    29.19 |        17.00 |                -0.53 |         1.61 |        -16.10 |
| SOL     |         0.84 |           1.06 |      1.86 |     0.99 |      -1.37 |   360.00 |   40.56 |        0.78 |        -0.39 |     2.00 |           42.07 |             21.00 |    15.83 |        17.00 |                 0.72 |        30.29 |          0.00 |
| AVAX    |        -0.15 |           0.06 |     -0.31 |    -0.20 |      -1.62 |   346.00 |   36.71 |        0.72 |        -0.44 |     1.63 |           -7.97 |            346.00 |    21.39 |        16.50 |                -0.24 |        -5.51 |          0.00 |
| LINK    |        -0.64 |          -0.43 |     -1.34 |    -0.87 |      -2.62 |   335.00 |   31.94 |        0.71 |        -0.43 |     1.64 |          -33.82 |             49.54 |    22.39 |        13.00 |                -0.80 |       -22.66 |          0.00 |
| SUI     |        -0.17 |           0.05 |     -0.26 |    -0.15 |      -2.32 |   348.00 |   36.49 |        0.97 |        -0.58 |     1.66 |           -8.48 |            407.21 |    24.43 |        15.00 |                -0.38 |        -5.90 |          0.00 |
| XRP     |         0.23 |           0.44 |      0.54 |     0.21 |      -1.77 |   347.00 |   37.75 |        0.69 |        -0.38 |     1.81 |           11.74 |             48.94 |    25.36 |        15.00 |                -0.13 |         8.15 |          0.00 |
| POOLED  |        -0.45 |           1.21 |     -0.25 |    -0.16 |      -6.15 |  2657.00 |   35.83 |        0.69 |        -0.39 |     1.75 |           -2.97 |            135.98 |    23.52 |        16.00 |                -0.81 |         5.51 |        -21.31 |

| Asset   |   Ann. net % |   Ann. gross % |   Sortino |   Sharpe |   Max DD % |   Trades |   Win % |   Avg win $ |   Avg loss $ |   Payoff |   Net bps/trade |   Cost % of gross |   Stop % |   Med hold h |   Ann. net ex-best % |   Long net $ |   Short net $ |
|:--------|-------------:|---------------:|----------:|---------:|-----------:|---------:|--------:|------------:|-------------:|---------:|----------------:|------------------:|---------:|-------------:|---------------------:|-------------:|--------------:|
| BTC     |        -3.33 |          -0.77 |     -2.54 |    -1.71 |     -12.73 |  1261.00 |   31.96 |        0.86 |        -0.54 |     1.60 |          -15.25 |            319.47 |    29.02 |         8.50 |                -3.47 |       -41.38 |        -72.50 |
| ETH     |        -2.60 |          -0.07 |     -1.55 |    -0.95 |     -10.04 |  1270.00 |   34.80 |        1.14 |        -0.72 |     1.59 |          -12.65 |           3389.95 |    27.32 |         8.50 |                -2.94 |       -27.36 |        -62.53 |
| SOL     |        -1.27 |          -0.17 |     -1.26 |    -0.78 |      -4.82 |  1147.00 |   34.00 |        0.82 |        -0.48 |     1.70 |          -13.02 |            632.34 |    25.28 |         8.00 |                -1.43 |       -44.70 |          0.00 |
| AVAX    |        -1.13 |          -0.05 |     -1.09 |    -0.68 |      -5.65 |  1137.00 |   33.95 |        0.86 |        -0.50 |     1.74 |          -11.73 |           2318.51 |    25.33 |         8.00 |                -1.32 |       -39.91 |          0.00 |
| LINK    |        -0.84 |           0.25 |     -0.83 |    -0.49 |      -5.35 |  1145.00 |   35.20 |        0.81 |        -0.48 |     1.69 |           -8.66 |            436.97 |    23.06 |         8.50 |                -1.08 |       -29.66 |          0.00 |
| SUI     |        -0.61 |           0.46 |     -0.49 |    -0.27 |      -3.54 |  1139.00 |   34.94 |        1.09 |        -0.61 |     1.77 |           -6.39 |            231.51 |    24.76 |         8.50 |                -0.90 |       -21.77 |          0.00 |
| XRP     |        -1.52 |          -0.42 |     -1.73 |    -0.84 |      -6.93 |  1144.00 |   32.34 |        0.67 |        -0.39 |     1.72 |          -15.57 |            259.28 |    24.48 |         8.00 |                -2.07 |       -53.31 |          0.00 |
| POOLED  |       -13.05 |          -0.76 |     -2.16 |    -1.45 |     -41.74 |  8243.00 |   33.87 |        0.90 |        -0.53 |     1.69 |          -11.96 |           1358.15 |    25.68 |         8.50 |               -13.82 |      -258.09 |       -135.02 |

## Variants (intraday, as-coded parameters)

- **trail**: the zero-cross exit is replaced by a Chandelier exit (highest high since entry - 3x ATR, on close). The executor still places only its static initial stop.
- **gate**: daily HMM regime gate. Longs need Bull or Chop, shorts need Bear or Chop, using the regime of the last completed daily bar.

| Variant   | Cadence          |   Ann. net % |   Sortino |   Trades |   Win % |   Payoff |   Gross bps |   Net bps |   Stop % |   Med hold h |   Ex-best % |
|:----------|:-----------------|-------------:|----------:|---------:|--------:|---------:|------------:|----------:|---------:|-------------:|------------:|
| as_coded  | full             |        -0.45 |     -0.25 |  2657.00 |   35.83 |     1.75 |        8.26 |     -2.97 |    23.52 |        16.00 |       -0.81 |
| as_coded  | throttled_median |         0.98 |      0.65 |   701.50 |   26.90 |     2.97 |       37.31 |     25.70 |    59.62 |        36.00 |       -0.08 |
| trail     | full             |        -0.87 |     -0.49 |  2519.00 |   30.73 |     2.15 |        5.04 |     -6.13 |    16.91 |        16.00 |       -1.27 |
| trail     | throttled_median |         0.42 |      0.25 |   701.50 |   25.00 |     3.18 |       22.27 |     10.68 |    59.61 |        34.00 |       -0.12 |
| gate      | full             |        -0.42 |     -0.28 |  2170.00 |   36.54 |     1.69 |        7.84 |     -3.40 |    24.93 |        18.00 |       -0.79 |
| gate      | throttled_median |         1.84 |      0.94 |   600.00 |   27.75 |     3.21 |       65.27 |     53.65 |    60.57 |        37.50 |        0.58 |

Neither variant fixes the full-cadence result. The trailing exit is worse (-6.1 bps net per trade). The regime gate is neutral at full cadence (-0.28 vs -0.25 Sortino). Its better throttled result comes from the same missed-exit drift capture as above, not from a better signal.

## Regime attribution (daily HMM regime in force at entry)

| bot              | scenario                 | regime   |   trades |   win_rate_pct |   net_usd |   gross_usd |   avg_net_bps |   pct_stop_exits |   median_hold_h |
|:-----------------|:-------------------------|:---------|---------:|---------------:|----------:|------------:|--------------:|-----------------:|----------------:|
| intraday         | as_coded_full            | Bear     |      992 |          35.69 |    -24.74 |       -2.42 |        -12.47 |            25.30 |           15.00 |
| intraday         | as_coded_full            | Bull     |      848 |          33.49 |     -9.51 |        9.58 |         -5.61 |            25.35 |           17.00 |
| intraday         | as_coded_full            | Chop     |      712 |          38.20 |     19.43 |       35.38 |         13.64 |            19.52 |           16.00 |
| intraday         | as_coded_full            | nan      |      105 |          40.00 |     -0.97 |        1.38 |         -4.63 |            19.05 |           17.00 |
| intraday         | as_coded_throttled_seed0 | Bear     |      264 |          24.62 |    -13.01 |       -6.88 |        -24.65 |            63.64 |           35.50 |
| intraday         | as_coded_throttled_seed0 | Bull     |      225 |          30.67 |     -0.79 |        4.42 |         -1.75 |            56.44 |           40.00 |
| intraday         | as_coded_throttled_seed0 | Chop     |      192 |          31.77 |     -0.01 |        4.43 |         -0.01 |            55.21 |           41.00 |
| intraday         | as_coded_throttled_seed0 | nan      |       31 |          19.35 |    -13.62 |      -12.91 |       -219.70 |            67.74 |           34.00 |
| intraday         | walk_forward_full        | Bear     |      804 |          39.43 |     17.19 |       35.26 |         10.69 |            23.76 |           18.00 |
| intraday         | walk_forward_full        | Bull     |      560 |          32.68 |    -10.44 |        2.17 |         -9.32 |            26.25 |           17.00 |
| intraday         | walk_forward_full        | Chop     |      514 |          41.44 |     36.58 |       48.12 |         35.58 |            21.40 |           17.00 |
| intraday         | walk_forward_full        | nan      |       59 |          33.90 |     -7.07 |       -5.74 |        -59.92 |            28.81 |           16.00 |
| intraday         | variant_gate_full        | Bear     |      394 |          35.03 |    -12.41 |       -3.52 |        -15.75 |            27.41 |           19.00 |
| intraday         | variant_gate_full        | Bull     |      802 |          36.28 |      4.66 |       22.69 |          2.91 |            24.06 |           16.00 |
| intraday         | variant_gate_full        | Chop     |      865 |          37.80 |      5.17 |       24.63 |          2.99 |            24.74 |           18.00 |
| intraday         | variant_gate_full        | nan      |      109 |          33.94 |    -12.20 |       -9.76 |        -55.95 |            23.85 |           16.00 |
| aggressive       | as_coded_full            | Bear     |     3054 |          33.63 |   -181.31 |      -46.21 |        -14.78 |            26.00 |            8.50 |
| aggressive       | as_coded_full            | Bull     |     2568 |          34.54 |    -83.88 |       39.36 |         -7.57 |            26.05 |            8.50 |
| aggressive       | as_coded_full            | Chop     |     2267 |          33.30 |   -115.42 |      -19.51 |        -13.15 |            25.19 |            8.50 |
| aggressive       | as_coded_full            | nan      |      354 |          34.75 |    -12.50 |       -0.61 |        -11.80 |            23.45 |            9.00 |
| aggressive       | as_coded_throttled_seed0 | Bear     |      700 |          19.86 |    -44.11 |      -11.99 |        -22.05 |            74.00 |           19.50 |
| aggressive       | as_coded_throttled_seed0 | Bull     |      566 |          22.44 |     51.00 |       78.79 |         30.61 |            70.32 |           18.75 |
| aggressive       | as_coded_throttled_seed0 | Chop     |      484 |          21.28 |     79.70 |      100.47 |         30.16 |            73.76 |           20.25 |
| aggressive       | as_coded_throttled_seed0 | nan      |       76 |          19.74 |      8.43 |       11.09 |         37.05 |            69.74 |           16.75 |
| aggressive       | walk_forward_full        | Bear     |     2740 |          32.48 |   -129.13 |       -5.77 |        -12.99 |            34.23 |            8.50 |
| aggressive       | walk_forward_full        | Bull     |     1549 |          33.70 |    -95.38 |      -20.00 |        -12.61 |            30.99 |            9.00 |
| aggressive       | walk_forward_full        | Chop     |     1805 |          31.86 |    -46.25 |       31.80 |         -7.80 |            36.95 |            8.00 |
| aggressive       | walk_forward_full        | nan      |      160 |          36.88 |     10.49 |       15.88 |         21.90 |            25.62 |           10.00 |
| daily_standard   | walk_forward_full        | Bull     |      115 |          43.48 |    146.81 |      149.42 |        638.30 |             0.87 |           72.00 |
| daily_aggressive | walk_forward_full        | Bear     |       18 |          38.89 |      0.17 |        0.97 |          2.35 |            16.67 |          300.00 |
| daily_aggressive | walk_forward_full        | Bull     |      111 |          42.34 |    237.81 |      242.85 |        608.29 |             0.90 |           72.00 |
| daily_aggressive | walk_forward_full        | Chop     |       38 |          55.26 |     26.84 |       27.68 |        353.15 |             2.63 |          180.00 |

By side, walk-forward OOS at full cadence:

| bot              | regime   | side   |   trades |   win_rate_pct |   net_usd |   avg_net_bps |   pct_stop_exits |
|:-----------------|:---------|:-------|---------:|---------------:|----------:|--------------:|-----------------:|
| intraday         | Bear     | long   |      655 |          39.24 |     10.31 |          7.87 |            24.27 |
| intraday         | Bear     | short  |      149 |          40.27 |      6.88 |         23.10 |            21.48 |
| intraday         | Bull     | long   |      410 |          32.68 |     -1.86 |         -2.27 |            25.37 |
| intraday         | Bull     | short  |      150 |          32.67 |     -8.58 |        -28.60 |            28.67 |
| intraday         | Chop     | long   |      418 |          41.39 |     27.30 |         32.66 |            21.77 |
| intraday         | Chop     | short  |       96 |          41.67 |      9.28 |         48.31 |            19.79 |
| intraday         | nan      | long   |       59 |          33.90 |     -7.07 |        -59.92 |            28.81 |
| aggressive       | Bear     | long   |     2331 |          32.60 |    -98.22 |        -13.04 |            33.72 |
| aggressive       | Bear     | short  |      409 |          31.78 |    -30.90 |        -12.71 |            37.16 |
| aggressive       | Bull     | long   |     1208 |          34.77 |    -38.24 |         -8.47 |            29.88 |
| aggressive       | Bull     | short  |      341 |          29.91 |    -57.15 |        -27.31 |            34.90 |
| aggressive       | Chop     | long   |     1581 |          32.32 |    -33.07 |         -7.58 |            36.43 |
| aggressive       | Chop     | short  |      224 |          28.57 |    -13.17 |         -9.30 |            40.62 |
| aggressive       | nan      | long   |      160 |          36.88 |     10.49 |         21.90 |            25.62 |
| daily_standard   | Bull     | long   |      115 |          43.48 |    146.81 |        638.30 |             0.87 |
| daily_aggressive | Bear     | short  |       18 |          38.89 |      0.17 |          2.35 |            16.67 |
| daily_aggressive | Bull     | long   |      111 |          42.34 |    237.81 |        608.29 |             0.90 |
| daily_aggressive | Chop     | long   |       34 |          52.94 |     16.38 |        240.86 |             2.94 |
| daily_aggressive | Chop     | short  |        4 |          75.00 |     10.46 |       1307.69 |             0.00 |

What the regime split shows:
- **Daily:** 100% of standard-mode profit is Bull-regime longs, which is by design. Expect roughly zero, not positive, return through a prolonged Bear: the bot sits in cash. The OOS window includes a -53% BTC drawdown, and the daily bot's own max drawdown was about -1% of capital.
- **Intraday:** mean reversion pays in Chop (+35.6 bps/trade) and Bear (+10.7) but loses in Bull (-9.3), where shorts are the worst bucket (-28.6 bps). Even so, gating by regime did not help as coded.
- **Aggressive:** loses in every regime and on both sides.

## Leave-one-asset-out (walk-forward OOS, full cadence)

| scenario                           | excluded   |   ann_net_pct |   sortino |   net_usd |   trades |   ann_net_ex_best_pct |
|:-----------------------------------|:-----------|--------------:|----------:|----------:|---------:|----------------------:|
| intraday_walk_forward_full         | none       |          1.03 |      0.71 |     31.93 |     1937 |                  0.75 |
| intraday_walk_forward_full         | BTC        |          0.78 |      0.56 |     24.12 |     1582 |                  0.50 |
| intraday_walk_forward_full         | ETH        |          0.79 |      0.60 |     24.51 |     1596 |                  0.51 |
| intraday_walk_forward_full         | SOL        |         -0.36 |     -0.24 |    -10.96 |     1677 |                 -0.65 |
| intraday_walk_forward_full         | AVAX       |          1.33 |      1.07 |     41.32 |     1678 |                  1.05 |
| intraday_walk_forward_full         | LINK       |          1.27 |      0.96 |     39.47 |     1709 |                  0.99 |
| intraday_walk_forward_full         | SUI        |          1.75 |      1.41 |     54.69 |     1692 |                  1.47 |
| intraday_walk_forward_full         | XRP        |          0.60 |      0.46 |     18.43 |     1688 |                  0.37 |
| daily_standard_walk_forward_full   | none       |          2.02 |      3.16 |    146.81 |      115 |                  1.03 |
| daily_standard_walk_forward_full   | BTC        |          1.87 |      3.03 |    135.40 |       93 |                  0.87 |
| daily_standard_walk_forward_full   | ETH        |          1.68 |      2.94 |    121.55 |       96 |                  0.68 |
| daily_standard_walk_forward_full   | SOL        |          2.04 |      3.24 |    148.57 |      112 |                  1.05 |
| daily_standard_walk_forward_full   | AVAX       |          1.83 |      3.64 |    132.30 |       97 |                  0.83 |
| daily_standard_walk_forward_full   | LINK       |          1.90 |      3.76 |    137.68 |       85 |                  0.90 |
| daily_standard_walk_forward_full   | SUI        |          2.00 |      3.20 |    145.29 |      109 |                  1.01 |
| daily_standard_walk_forward_full   | XRP        |          0.84 |      1.54 |     60.07 |       98 |                  0.62 |
| daily_aggressive_walk_forward_full | none       |          3.58 |      3.02 |    264.82 |      167 |                  2.13 |
| daily_aggressive_walk_forward_full | BTC        |          3.15 |      2.95 |    232.20 |      129 |                  1.70 |
| daily_aggressive_walk_forward_full | ETH        |          2.76 |      2.94 |    202.52 |      130 |                  1.29 |
| daily_aggressive_walk_forward_full | SOL        |          3.54 |      3.05 |    261.96 |      151 |                  2.10 |
| daily_aggressive_walk_forward_full | AVAX       |          3.29 |      3.25 |    242.78 |      144 |                  1.84 |
| daily_aggressive_walk_forward_full | LINK       |          3.44 |      3.36 |    254.17 |      137 |                  1.99 |
| daily_aggressive_walk_forward_full | SUI        |          3.55 |      3.04 |    262.54 |      161 |                  2.10 |
| daily_aggressive_walk_forward_full | XRP        |          1.83 |      1.73 |    132.76 |      150 |                  1.35 |

## Hyperliquid vs Binance proxy (same window, as coded, full cadence)

Hyperliquid's `candleSnapshot` only serves the latest 5000 candles: 208 days at 1h, 104 days at 30m (verified: requests older than that return `[]`). The multi-year runs use Binance USDT-M perps. On the overlap, return correlation is 0.996-0.999, median basis is 1-4 bps, and Hyperliquid's bar ranges are 2-7% narrower (`results/proxy_validation.csv`), so the proxy slightly over-triggers stops. Strategy results on the two feeds are near-identical:

| bot        | scenario          |   days |   ann_net_pct |   sortino |   trades |   win_rate_pct |   avg_gross_bps |   avg_net_bps |   pct_stop_exits |
|:-----------|:------------------|-------:|--------------:|----------:|---------:|---------------:|----------------:|--------------:|-----------------:|
| intraday   | hl_window_hl      | 202.00 |         -1.97 |     -1.47 |   417.00 |          32.85 |           -1.89 |        -13.16 |            27.10 |
| intraday   | hl_window_binance | 202.00 |         -1.97 |     -1.44 |   411.00 |          33.09 |           -2.08 |        -13.35 |            26.03 |
| aggressive | hl_window_hl      |  98.00 |          2.75 |      0.79 |   589.00 |          32.60 |           13.62 |          2.34 |            27.33 |
| aggressive | hl_window_binance |  98.00 |          4.61 |      1.26 |   584.00 |          33.39 |           13.60 |          2.36 |            23.63 |

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
