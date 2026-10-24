"""
backtest/extra_checks.py — Robustness checks on the main results.

1. Intraday walk-forward vs 200 random-entry seeds (main run used 50).
2. Leave-one-asset-out on the walk-forward OOS results (intraday, daily).
3. Live-window replay: Sept 10 - Oct 14 2026 with the stop multipliers the
   bots ran then (intraday 2.0x, aggressive 1.5x), full vs throttled cadence,
   to check the engine reproduces the live failure pattern.

Run after run_backtests.py:  backtest/.venv/bin/python backtest/extra_checks.py
"""

import os

import numpy as np
import pandas as pd

import run_backtests as rb
from data_fetch import RESULTS_DIR, TICKERS
from metrics import compute_metrics

LIVE_START, LIVE_END = pd.Timestamp("2026-09-10"), pd.Timestamp("2026-10-14 23:59")


def wf_choices(bot):
    f = pd.read_csv(os.path.join(RESULTS_DIR, "intraday_wf_folds.csv"))
    f = f[f.bot == bot]
    return [((None, None, pd.Timestamp(r.oos_start), pd.Timestamp(r.oos_end)), (r.thr, r.stop_mult))
            for r in f.itertuples()]


def leave_one_out(label, inc, trades, cap):
    rows = []
    for t in [None] + TICKERS:
        keep = [c for c in inc.columns if c != t]
        tr = trades[trades.ticker != t] if t else trades
        m = compute_metrics(inc[keep], tr, cap)
        rows.append({"scenario": label, "excluded": t or "none", "ann_net_pct": m["ann_net_pct"],
                     "sortino": m["sortino"], "net_usd": m["net_usd"], "trades": m["trades"],
                     "ann_net_ex_best_pct": m["ann_net_ex_best_pct"]})
    return rows


def main():
    combos = [(t, m) for t in rb.THRESHOLDS for m in rb.STOPS]
    cap = rb.CAPITAL["intraday"]
    choices = wf_choices("intraday")

    # 1 + 2 (intraday): full-cadence strategy and 200 random seeds, stitched with the same fold choices
    full = {(r["job"]["thr"], r["job"]["mult"]): r for r in
            rb.run_all([{"bot": "intraday", "thr": t, "mult": m, "cadence": "full"} for t, m in combos], "intraday full")}
    inc, tr = rb.stitch(full, choices)
    strat = compute_metrics(inc, tr, cap)
    loo = leave_one_out("intraday_walk_forward_full", inc, tr, cap)

    jobs = [{"bot": "intraday", "thr": t, "mult": m, "variant": "random", "rseed": s, "cadence": "full"}
            for t, m in combos for s in range(200)]
    rres = rb.run_all(jobs, "intraday random x200")
    by_seed = {}
    for r in rres:
        by_seed.setdefault(r["job"]["rseed"], {})[(r["job"]["thr"], r["job"]["mult"])] = r
    so = []
    for s in range(200):
        i2, t2 = rb.stitch(by_seed[s], choices)
        so.append(compute_metrics(i2, t2, cap)["sortino"])
    so = np.array(so)
    rand = pd.DataFrame([{"bot": "intraday", "scenario": "walk_forward_full", "seeds": 200,
                          "strategy_sortino": strat["sortino"], "random_median": np.median(so),
                          "random_p95": np.quantile(so, 0.95), "random_p99": np.quantile(so, 0.99),
                          "seeds_beating_strategy": int((so >= strat["sortino"]).sum()),
                          "strategy_pctile": float((so < strat["sortino"]).mean() * 100)}])
    rand.to_csv(os.path.join(RESULTS_DIR, "random_control_200.csv"), index=False)
    print(rand.to_string(index=False))

    # 2 (daily): leave-one-out on the full-cadence walk-forward
    for mode in ("standard", "aggressive"):
        r = rb.run_job({"bot": "daily", "mode": mode, "cadence": "full"})
        loo += leave_one_out(f"daily_{mode}_walk_forward_full", r["inc"], r["trades"], rb.CAPITAL["daily"])
    loo = pd.DataFrame(loo)
    loo.to_csv(os.path.join(RESULTS_DIR, "leave_one_asset_out.csv"), index=False)
    print(loo.to_string(index=False))

    # 3. Live-window replay with the pre-widening stops
    rows = []
    for bot, (thr, mult) in (("intraday", (0.5, 2.0)), ("aggressive", (0.25, 1.5))):
        jobs = [{"bot": bot, "thr": thr, "mult": mult, "cadence": "full", "start": LIVE_START, "end": LIVE_END}]
        jobs += [{"bot": bot, "thr": thr, "mult": mult, "cadence": "throttled", "cseed": s,
                  "start": LIVE_START, "end": LIVE_END} for s in range(rb.N_THROTTLE)]
        res = rb.run_all(jobs, f"{bot} live window")
        for r in res:
            m = compute_metrics(r["inc"], r["trades"], rb.CAPITAL[bot])
            rows.append({"bot": bot, "cadence": r["job"]["cadence"], "seed": r["job"].get("cseed"),
                         "runs": r["runs"], "trades": m["trades"], "net_usd": m["net_usd"],
                         "costs_usd": m["costs_usd"], "win_rate_pct": m["win_rate_pct"],
                         "pct_stop_exits": m["pct_stop_exits"], "median_hold_h": m["median_hold_h"]})
    lw = pd.DataFrame(rows)
    lw.to_csv(os.path.join(RESULTS_DIR, "live_window_replay.csv"), index=False)
    summ = lw.groupby(["bot", "cadence"]).median(numeric_only=True).drop(columns=["seed"])
    print(summ.to_string())

    # 4. Hypothetical state-based exit fix (issue #1), as-coded params, full vs throttled
    rows = []
    for state in (False, True):
        jobs = []
        for bot in ("intraday", "aggressive"):
            thr, mult = rb.CURRENT[bot]
            jobs.append({"bot": bot, "thr": thr, "mult": mult, "cadence": "full", "state_exits": state})
            jobs += [{"bot": bot, "thr": thr, "mult": mult, "cadence": "throttled", "cseed": s,
                      "state_exits": state} for s in range(rb.N_THROTTLE)]
        for mode in ("standard", "aggressive"):
            jobs.append({"bot": "daily", "mode": mode, "cadence": "full", "state_exits": state})
            jobs += [{"bot": "daily", "mode": mode, "cadence": "bernoulli", "p_deliver": p, "cseed": s,
                      "state_exits": state} for p in rb.DAILY_DELIVERY for s in range(rb.N_THROTTLE)]
        for r in rb.run_all(jobs, f"state_exits={state}"):
            j = r["job"]
            m = compute_metrics(r["inc"], r["trades"], rb.CAPITAL[j["bot"]])
            cad = j["cadence"] if j["cadence"] != "bernoulli" else f"delivery_{j['p_deliver']}"
            rows.append({"bot": j["bot"] if j["bot"] != "daily" else f"daily_{j['mode']}", "cadence": cad,
                         "exit_rule": "state_based_fix" if state else "as_coded", "ann_net_pct": m["ann_net_pct"],
                         "sortino": m["sortino"], "trades": m["trades"], "pct_stop_exits": m["pct_stop_exits"],
                         "avg_net_bps": m["avg_net_bps"], "median_hold_h": m["median_hold_h"]})
    fx = pd.DataFrame(rows).groupby(["bot", "exit_rule", "cadence"]).median(numeric_only=True).reset_index()
    fx.to_csv(os.path.join(RESULTS_DIR, "state_exit_fix.csv"), index=False)
    print(fx.to_string(index=False))


if __name__ == "__main__":
    main()
