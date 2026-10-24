"""
backtest/report_tables.py — Build the markdown tables REPORT.md embeds.

Run:  backtest/.venv/bin/python backtest/report_tables.py  > backtest/results/tables.md
"""

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
COIN = {"BTC-USD": "BTC", "ETH-USD": "ETH", "SOL-USD": "SOL", "AVAX-USD": "AVAX", "LINK-USD": "LINK",
        "SUI20947-USD": "SUI", "XRP-USD": "XRP", "POOLED": "POOLED"}


def load(name):
    return pd.read_csv(os.path.join(R, name))


def md(df, floatfmt=".2f"):
    return df.to_markdown(index=False, floatfmt=floatfmt)


def verdict_table():
    sc, rc = load("scenarios.csv"), load("random_control.csv")
    rows = []
    for bot in ("intraday", "aggressive", "daily_standard", "daily_aggressive"):
        f = sc[(sc.bot == bot) & (sc.scenario == "walk_forward_oos") & (sc.cadence == "full") & (sc.asset == "POOLED")].iloc[0]
        r = rc[(rc.bot == bot) & (rc.scenario == "walk_forward_full")].iloc[0]
        pctile, rand_txt, seeds = r.strategy_pctile_vs_random, f"{r.random_sortino_median:.2f} / {r.random_sortino_p95:.2f}", 50
        r200 = os.path.join(R, "random_control_200.csv")
        if bot == "intraday" and os.path.exists(r200):
            x = pd.read_csv(r200).iloc[0]
            pctile, rand_txt, seeds = x.strategy_pctile, f"{x.random_median:.2f} / {x.random_p95:.2f}", 200
        sortino_ok = f.sortino > 0
        random_ok = pctile >= 95
        fragile_ok = f.ann_net_ex_best_pct > 0
        rows.append({
            "Bot": bot, "OOS Sortino (full cadence)": f.sortino, "Ann. net %": f.ann_net_pct,
            "Pctile vs random": pctile, "Random seeds": seeds, "Random Sortino p50 / p95": rand_txt,
            "Ann. net ex best trade %": f.ann_net_ex_best_pct, "Trades": int(f.trades),
            "Sortino > 0": "yes" if sortino_ok else "NO", "Beats random (>=p95)": "yes" if random_ok else "NO",
            "Survives best-trade removal": "yes" if fragile_ok else "NO",
            "Earns infrastructure": "YES" if (sortino_ok and random_ok and fragile_ok) else "NO",
        })
    return md(pd.DataFrame(rows))


def cadence_table():
    sc = load("scenarios.csv")
    rows = []
    for bot in ("intraday", "aggressive", "daily_standard", "daily_aggressive"):
        sub = sc[(sc.bot == bot) & (sc.scenario == "walk_forward_oos") & (sc.asset == "POOLED")]
        for _, x in sub.iterrows():
            rows.append({"Bot": bot, "Cadence": x.cadence, "Ann. net %": x.ann_net_pct, "Ann. gross %": x.ann_gross_pct,
                         "Sortino": x.sortino, "Sharpe": x.sharpe, "Max DD %": x.max_dd_pct, "Trades": x.trades,
                         "Win %": x.win_rate_pct, "Payoff": x.payoff, "Gross bps/trade": x.avg_gross_bps,
                         "Net bps/trade": x.avg_net_bps, "Cost % of gross": x.cost_drag_pct_of_gross,
                         "Stop exits %": x.pct_stop_exits, "Median hold h": x.median_hold_h,
                         "Mean hold h": x.mean_hold_h})
    return md(pd.DataFrame(rows))


def seed_spread():
    s = load("throttled_seeds.csv")
    rows = []
    for (bot, scen), g in s.groupby(["bot", "scenario"]):
        rows.append({"Bot": bot, "Scenario": scen, "Seeds": len(g),
                     "Ann. net % p10 / p50 / p90": f"{g.ann_net_pct.quantile(.1):.2f} / {g.ann_net_pct.median():.2f} / {g.ann_net_pct.quantile(.9):.2f}",
                     "Sortino p10 / p50 / p90": f"{g.sortino.quantile(.1):.2f} / {g.sortino.median():.2f} / {g.sortino.quantile(.9):.2f}",
                     "Stop exits % p50": g.pct_stop_exits.median(), "Trades p50": g.trades.median(),
                     "Net bps/trade p50": g.avg_net_bps.median()})
    return md(pd.DataFrame(rows))


def per_asset(bot, scenario="walk_forward_oos"):
    sc = load("scenarios.csv")
    sub = sc[(sc.bot == bot) & (sc.scenario == scenario) & (sc.cadence == "full")].copy()
    sub["asset"] = sub["asset"].map(COIN)
    cols = {"asset": "Asset", "ann_net_pct": "Ann. net %", "ann_gross_pct": "Ann. gross %", "sortino": "Sortino",
            "sharpe": "Sharpe", "max_dd_pct": "Max DD %", "trades": "Trades", "win_rate_pct": "Win %",
            "avg_win_usd": "Avg win $", "avg_loss_usd": "Avg loss $", "payoff": "Payoff",
            "avg_net_bps": "Net bps/trade", "cost_drag_pct_of_gross": "Cost % of gross",
            "pct_stop_exits": "Stop %", "median_hold_h": "Med hold h", "ann_net_ex_best_pct": "Ann. net ex-best %",
            "long_net_usd": "Long net $", "short_net_usd": "Short net $"}
    return md(sub[list(cols)].rename(columns=cols))


def grid(bot, metric="sortino", cadence="full"):
    sc = load("scenarios.csv")
    sub = sc[(sc.bot == bot) & (sc.scenario == "grid_full_history") & (sc.cadence == cadence)]
    p = sub.pivot(index="thr", columns="stop_mult", values=metric)
    p.columns = [f"stop {c}x" for c in p.columns]
    p.index = [f"+/-{i}" for i in p.index]
    return p.reset_index().rename(columns={"index": "threshold"}).to_markdown(index=False, floatfmt=".2f")


def grid_long(bot):
    sc = load("scenarios.csv")
    sub = sc[(sc.bot == bot) & (sc.scenario == "grid_full_history") & (sc.cadence == "full")]
    cols = {"thr": "Thr", "stop_mult": "Stop", "ann_net_pct": "Ann. net %", "ann_gross_pct": "Ann. gross %",
            "sortino": "Sortino", "trades": "Trades", "win_rate_pct": "Win %", "avg_gross_bps": "Gross bps",
            "avg_net_bps": "Net bps", "pct_stop_exits": "Stop %", "median_hold_h": "Med hold h"}
    return md(sub[list(cols)].rename(columns=cols))


def folds(bot):
    f = load("intraday_wf_folds.csv")
    f = f[f.bot == bot]
    return md(f[["oos_start", "oos_end", "thr", "stop_mult", "is_sortino"]])


def random_table():
    rc = load("random_control.csv")
    return md(rc)


def variants():
    v = load("variants.csv")
    sc = load("scenarios.csv")
    base = sc[(sc.bot == "intraday") & (sc.scenario == "as_coded_full_history") & (sc.asset == "POOLED")].copy()
    base["variant"] = "as_coded"
    seeds = load("throttled_seeds.csv")
    s = seeds[(seeds.bot == "intraday") & (seeds.scenario == "as_coded_full_history")]
    thr_row = {"variant": "as_coded", "cadence": "throttled_median", **s.drop(columns=["bot", "scenario", "seed", "runs"]).median().to_dict()}
    allv = pd.concat([base, pd.DataFrame([thr_row]), v[v.asset == "POOLED"]], ignore_index=True)
    cols = {"variant": "Variant", "cadence": "Cadence", "ann_net_pct": "Ann. net %", "sortino": "Sortino",
            "trades": "Trades", "win_rate_pct": "Win %", "payoff": "Payoff", "avg_gross_bps": "Gross bps",
            "avg_net_bps": "Net bps", "pct_stop_exits": "Stop %", "median_hold_h": "Med hold h",
            "ann_net_ex_best_pct": "Ex-best %"}
    return md(allv[list(cols)].rename(columns=cols))


def regimes(scenarios=("walk_forward_full", "as_coded_full", "as_coded_throttled_seed0", "variant_gate_full")):
    r = load("regime_attribution.csv")
    r = r[r.scenario.isin(scenarios) & (r.side == "all")]
    cols = ["bot", "scenario", "regime", "trades", "win_rate_pct", "net_usd", "gross_usd", "avg_net_bps",
            "pct_stop_exits", "median_hold_h"]
    return md(r[cols])


def regimes_side(scenario="walk_forward_full"):
    r = load("regime_attribution.csv")
    r = r[(r.scenario == scenario) & (r.side != "all")]
    return md(r[["bot", "regime", "side", "trades", "win_rate_pct", "net_usd", "avg_net_bps", "pct_stop_exits"]])


def baselines():
    return md(load("baselines.csv"))


def hl_check():
    sc = load("scenarios.csv")
    sub = sc[sc.scenario.str.startswith("hl_window")]
    return md(sub[["bot", "scenario", "days", "ann_net_pct", "sortino", "trades", "win_rate_pct", "avg_gross_bps",
                   "avg_net_bps", "pct_stop_exits"]])


def daily_feefree():
    return md(load("daily_walkforward_feefree.csv"))


def loo():
    d = load("leave_one_asset_out.csv")
    d["excluded"] = d["excluded"].map(lambda x: COIN.get(x, x))
    return md(d)


def live_replay():
    d = load("live_window_replay.csv")
    g = d.groupby(["bot", "cadence"]).median(numeric_only=True).drop(columns=["seed"]).reset_index()
    return md(g)


def random200():
    return md(load("random_control_200.csv"))


def state_fix():
    d = load("state_exit_fix.csv")
    d = d[["bot", "cadence", "exit_rule", "ann_net_pct", "sortino", "trades", "pct_stop_exits", "avg_net_bps", "median_hold_h"]]
    return md(d.sort_values(["bot", "cadence", "exit_rule"]))


SECTIONS = {
    "STATE_FIX": state_fix, "LOO": loo, "LIVE": live_replay, "RANDOM200": random200,
    "VERDICT": verdict_table, "CADENCE": cadence_table, "SEEDS": seed_spread, "BASELINES": baselines,
    "RANDOM": random_table, "VARIANTS": variants, "REGIMES": regimes, "REGIMES_SIDE": regimes_side,
    "HL": hl_check, "DAILY_FEEFREE": daily_feefree,
    "ASSET_INTRADAY": lambda: per_asset("intraday"), "ASSET_AGGRESSIVE": lambda: per_asset("aggressive"),
    "ASSET_DAILY_STD": lambda: per_asset("daily_standard"), "ASSET_DAILY_AGG": lambda: per_asset("daily_aggressive"),
    "ASSET_INTRADAY_ASCODED": lambda: per_asset("intraday", "as_coded_full_history"),
    "ASSET_AGGRESSIVE_ASCODED": lambda: per_asset("aggressive", "as_coded_full_history"),
    "GRID_INTRADAY": lambda: grid_long("intraday"), "GRID_AGGRESSIVE": lambda: grid_long("aggressive"),
    "GRID_INTRADAY_SORTINO_THR": lambda: grid("intraday", "sortino", "throttled_median"),
    "GRID_AGGRESSIVE_SORTINO_THR": lambda: grid("aggressive", "sortino", "throttled_median"),
    "FOLDS_INTRADAY": lambda: folds("intraday"), "FOLDS_AGGRESSIVE": lambda: folds("aggressive"),
}


def render(template_path, out_path):
    """Replace {{SECTION}} markers in a template with generated tables."""
    with open(template_path) as f:
        text = f.read()
    for k, fn in SECTIONS.items():
        marker = "{{" + k + "}}"
        if marker in text:
            text = text.replace(marker, fn())
    with open(out_path, "w") as f:
        f.write(text)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        render(sys.argv[1], sys.argv[2])
    else:
        for k, fn in SECTIONS.items():
            print(f"\n### {k}\n")
            print(fn())
