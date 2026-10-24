"""
backtest/verify_exit_fix.py — Check the state-based exit change in the executors.

1. Scenario checks on each executor's decide_trades.
2. Replay the (now modified) executors through the backtest engine and
   compare against the backtest-only wrapper results in state_exit_fix.csv.

Run:  backtest/.venv/bin/python backtest/verify_exit_fix.py
"""

import os

import numpy as np
import pandas as pd

import run_backtests as rb
from data_fetch import RESULTS_DIR
from metrics import compute_metrics


def scenario_checks():
    import aggressive_executor as ae
    import hyperliquid_executor as he
    import intraday_executor as ie

    def sig(signal, action, **kw):
        return {"signal": signal, "action": action, "osc": 0.0, "atr": 1.0, "price": 100.0,
                "bull_conf": 0.5, "bear_conf": 0.5, "regime": "Chop", "pyramid": 0, "pyramid_added": False, **kw}

    deciders = {
        "intraday": lambda s, p, cd=None: ie.decide_trades(s, p, 2, cd),
        "aggressive": lambda s, p, cd=None: ae.decide_trades(s, p, 4, {}, cd),
        "daily": lambda s, p, cd=None: he.decide_trades(s, p, 4, cd),
    }
    long_pos = {"BTC": {"size": 0.001}}
    short_pos = {"BTC": {"size": -0.001}}
    for name, d in deciders.items():
        closes = lambda tr: [t for t in tr if t["action"] == "close"]  # noqa: E731
        # Missed exit: strategy went flat bars ago, run sees "flat" -> must close (was the bug)
        tr = closes(d({"BTC-USD": sig(0, "flat")}, long_pos))
        assert len(tr) == 1 and "missed" in tr[0]["reason"].lower(), (name, tr)
        tr = closes(d({"BTC-USD": sig(0, "flat")}, short_pos))
        assert len(tr) == 1, (name, "short flat", tr)
        # Missed flip: long held, strategy now holding short -> close
        assert len(closes(d({"BTC-USD": sig(-1, "hold_short")}, long_pos))) == 1, name
        # Transition actions still close with their original reasons
        tr = closes(d({"BTC-USD": sig(0, "sell_exit")}, long_pos))
        assert len(tr) == 1 and "missed" not in tr[0]["reason"].lower(), (name, tr)
        # Holding the right side -> no close
        assert closes(d({"BTC-USD": sig(1, "hold_long")}, long_pos)) == [], name
        assert closes(d({"BTC-USD": sig(-1, "hold_short")}, short_pos)) == [], name
        # No position -> no close
        assert closes(d({"BTC-USD": sig(0, "flat")}, {})) == [], name
        print(f"scenario checks passed: {name}")
    # Daily Bear liquidation still labelled as before
    tr = he.decide_trades({"BTC-USD": sig(0, "liquidate", regime="Bear")}, long_pos, 4)
    assert tr[0]["reason"] == "LIQUIDATE TO CASH signal"


def replay_matches_wrapper():
    ref = pd.read_csv(os.path.join(RESULTS_DIR, "state_exit_fix.csv"))
    ref = ref[ref.exit_rule == "state_based_fix"].set_index(["bot", "cadence"])
    jobs = []
    for bot in ("intraday", "aggressive"):
        thr, mult = rb.CURRENT[bot]
        jobs.append({"bot": bot, "thr": thr, "mult": mult, "cadence": "full"})
        jobs += [{"bot": bot, "thr": thr, "mult": mult, "cadence": "throttled", "cseed": s} for s in range(rb.N_THROTTLE)]
    for mode in ("standard", "aggressive"):
        jobs.append({"bot": "daily", "mode": mode, "cadence": "full"})
        jobs += [{"bot": "daily", "mode": mode, "cadence": "bernoulli", "p_deliver": p, "cseed": s}
                 for p in rb.DAILY_DELIVERY for s in range(rb.N_THROTTLE)]
    rows = []
    for r in rb.run_all(jobs, "modified executors"):
        j = r["job"]
        m = compute_metrics(r["inc"], r["trades"], rb.CAPITAL[j["bot"]])
        rows.append({"bot": j["bot"] if j["bot"] != "daily" else f"daily_{j['mode']}",
                     "cadence": j["cadence"] if j["cadence"] != "bernoulli" else f"delivery_{j['p_deliver']}",
                     "ann_net_pct": m["ann_net_pct"], "sortino": m["sortino"], "trades": m["trades"],
                     "pct_stop_exits": m["pct_stop_exits"]})
    got = pd.DataFrame(rows).groupby(["bot", "cadence"]).median(numeric_only=True)
    cols = ["ann_net_pct", "sortino", "trades", "pct_stop_exits"]
    cmp = got[cols].join(ref[cols].add_suffix("_wrapper"))
    print(cmp.round(3).to_string())
    # Full cadence never misses a transition, so the change must be a no-op there.
    full = cmp[cmp.index.get_level_values("cadence") == "full"]
    for c in cols:
        assert np.allclose(full[c], full[f"{c}_wrapper"], atol=1e-9), c
    print("full cadence: modified executors == pre-change behavior (exact)")
    # Throttled rows differ slightly from the wrapper by design: the wrapper added
    # closes after decide_trades counted slots, while the real change closes inside
    # it, freeing the slot and allowing the existing sync-to-hold re-entry.


if __name__ == "__main__":
    scenario_checks()
    replay_matches_wrapper()
