"""
backtest/run_backtests.py — Run every scenario and write backtest/results/*.csv.

Prereqs: data_fetch.py (cache) and daily_wf.py (regimes + fold params).
Run:     backtest/.venv/bin/python backtest/run_backtests.py
"""

import functools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from data_fetch import RESULTS_DIR, TICKERS, load_intraday  # noqa: E402
from daily_wf import load_regimes  # noqa: E402
from engine import BotSpec, simulate, full_cadence, throttled_cadence, bernoulli_cadence  # noqa: E402
from signals import base_signals, osc_loop, entry_rate, daily_loop  # noqa: E402
from metrics import compute_metrics, regime_table  # noqa: E402

EVAL_START = pd.Timestamp("2023-04-01")
WF_IS_DAYS, WF_OOS_DAYS = 182, 61
THRESHOLDS = [0.25, 0.5, 1.0]
STOPS = [1.5, 2.0, 3.0, 4.0]
CURRENT = {"intraday": (0.5, 3.0), "aggressive": (0.25, 3.0)}
INTERVAL = {"intraday": "1h", "aggressive": "30m"}
MEAN_GAP_BARS = {"intraday": 5.0, "aggressive": 10.0}   # one run per ~5 h
N_THROTTLE, N_RANDOM = 20, 50
DAILY_DELIVERY = [0.5, 0.125]
CAPITAL = {"daily": 2000.0, "intraday": 1000.0, "aggressive": 1000.0}
WORKERS = 11


# ── Bot specs (built inside workers; lambdas don't pickle) ───────────────────

def make_spec(bot: str, mult: float | None = None) -> BotSpec:
    from backtester import get_asset_profile
    from intraday_data_loader import HL_SYMBOL_MAP
    if bot == "intraday":
        import intraday_executor as ie
        from intraday_strategy import classify_intraday_signal
        return BotSpec("intraday", CAPITAL["intraday"], ie.POSITION_SIZE_PCT, 2,
                       leverage_for=lambda t, s: 2.0,           # intraday_executor main(): fixed 2x
                       stop_mult_for=lambda t: mult,
                       classify=lambda last, prev, info: classify_intraday_signal(last, prev),
                       decide=lambda sg, mp, mx, pyr, cd: ie.decide_trades(sg, mp, mx, cd),
                       hl_map=HL_SYMBOL_MAP)
    if bot == "aggressive":
        import aggressive_executor as ae
        from aggressive_strategy import classify_aggressive_signal
        return BotSpec("aggressive", CAPITAL["aggressive"], ae.POSITION_SIZE_PCT, 4,
                       leverage_for=lambda t, s: min(4.0, get_asset_profile(t)["max_bull_leverage"] * 1.33),
                       stop_mult_for=lambda t: mult,
                       classify=lambda last, prev, info: classify_aggressive_signal(last, prev),
                       decide=lambda sg, mp, mx, pyr, cd: ae.decide_trades(sg, mp, mx, pyr, cd),
                       pyramid_size_pct=ae.PYRAMID_SIZE_PCT, hl_map=HL_SYMBOL_MAP)
    import hyperliquid_executor as he
    from signal_utils import classify_signal
    return BotSpec("daily", CAPITAL["daily"], he.POSITION_SIZE_PCT, 4,
                   leverage_for=lambda t, s: max(1.0, min(s.get("leverage", 1.0), 3.0)),
                   stop_mult_for=lambda t: float(get_asset_profile(t)["atr_mult"]),
                   classify=lambda last, prev, info: classify_signal(last, prev, info["regime"]),
                   decide=lambda sg, mp, mx, pyr, cd: he.decide_trades(sg, mp, mx, cd),
                   hl_map=he.HL_TICKER_MAP)


def with_state_exits(decide, hl_map):
    """Hypothetical fix for code issue #1, backtest-only: also close any open
    position whose current strategy signal no longer matches it, so a missed
    sell_exit/cover_short bar can't orphan the position."""
    def wrapped(sg, mp, mx, pyr, cd):
        trades = decide(sg, mp, mx, pyr, cd)
        closing = {t["hl_coin"] for t in trades if t["action"] == "close"}
        extra = []
        for ticker, info in sg.items():
            coin = hl_map[ticker]
            pos = mp.get(coin)
            if pos and coin not in closing and info["signal"] != (1 if pos["size"] > 0 else -1):
                extra.append({"ticker": ticker, "hl_coin": coin, "action": "close",
                              "side": "long" if pos["size"] > 0 else "short", "reason": "state exit"})
        return extra + trades
    return wrapped


# ── Data + signal caches (per process) ───────────────────────────────────────

@functools.lru_cache(maxsize=None)
def bars(source: str, ticker: str, interval: str) -> pd.DataFrame:
    return load_intraday(source, ticker, interval)


@functools.lru_cache(maxsize=None)
def daily_regime_on_bars(ticker: str, interval: str, source: str) -> np.ndarray:
    """Daily HMM regime known at each intraday bar: regime of day D applies
    from D+1 00:00 UTC (after the daily bar has closed)."""
    reg = load_regimes(ticker)["Regime"].copy()
    reg.index = reg.index + pd.Timedelta(days=1)
    b = bars(source, ticker, interval)
    r = reg.reindex(reg.index.union(b.index)).ffill().reindex(b.index)
    return r.to_numpy(dtype=object)


@functools.lru_cache(maxsize=None)
def base_frame(bot, ticker, thr, mult, source="binance"):
    from backtester import get_asset_profile
    return base_signals(bot, bars(source, ticker, INTERVAL[bot]), get_asset_profile(ticker)["allow_short"], thr, mult)


def strat_frames(bot, thr, mult, variant="base", rseed=0, source="binance"):
    from backtester import get_asset_profile
    out = {}
    for t in TICKERS:
        b = base_frame(bot, t, thr, mult, source)
        if variant == "base":
            out[t] = b
            continue
        allow_short = get_asset_profile(t)["allow_short"]
        kw = dict(allow_short=allow_short, osc_lower=-thr, osc_upper=thr, atr_stop_mult=mult,
                  pyramid=(bot == "aggressive"))
        if variant == "random":
            ev = b.index >= EVAL_START
            out[t] = osc_loop(b, entry="random", p_entry=entry_rate(b["Signal"][ev]),
                              seed=rseed * 1000 + TICKERS.index(t), **kw)
        elif variant == "trail":
            out[t] = osc_loop(b, exit_mode="trail", trail_mult=3.0, **kw)
        elif variant == "gate":
            out[t] = osc_loop(b, gate=daily_regime_on_bars(t, INTERVAL[bot], source), **kw)
    return out


def union_len(frames, start, end=None):
    idx = None
    for df in frames.values():
        idx = df.index if idx is None else idx.union(df.index)
    return len(idx), idx


def to_daily(res):
    """Per-ticker daily PnL increments from the per-bar cumulative MTM."""
    d = res.pnl_net.resample("D").last().ffill().fillna(0.0)
    inc = d.diff()
    inc.iloc[0] = d.iloc[0]
    return inc


# ── Daily frames (walk_forward fold params, regenerated per OOS window) ──────

@functools.lru_cache(maxsize=None)
def daily_folds():
    with open(os.path.join(RESULTS_DIR, "daily_wf_folds.json")) as f:
        return json.load(f)


def daily_frames(mode: str, random_seed: int | None = None, p_map: dict | None = None):
    from backtester import get_asset_profile
    aggressive = mode == "aggressive"
    out = {}
    for t in TICKERS:
        df = load_regimes(t)
        prof = get_asset_profile(t)
        bull_lev = min(3.0, prof["max_bull_leverage"]) if aggressive else 3.0
        parts = []
        for k, fold in enumerate(daily_folds()[f"{t}|{mode}"]):
            sl = df.iloc[fold["iloc_start"]:fold["iloc_end"]]
            kw = dict(aggressive=aggressive, bull_leverage=bull_lev, allow_short=prof["allow_short"],
                      atr_mult=prof["atr_mult"], **fold["params"])
            if random_seed is None:
                from strategy import generate_signals  # the bot's own code
                s = generate_signals(sl, sl["Regime"], bull_probs=sl["Bull_Prob"], bear_probs=sl["Bear_Prob"], **kw)
            else:
                s = daily_loop(sl, sl["Regime"], sl["Bull_Prob"], sl["Bear_Prob"], random_p=p_map[t],
                               seed=random_seed * 10_000 + TICKERS.index(t) * 100 + k, **kw)
            parts.append(s)
        sig = pd.concat(parts)
        f = df.loc[sig.index, ["Open", "High", "Low", "Close", "ATR", "TwoPole_Osc", "Regime", "Bull_Prob", "Bear_Prob"]].copy()
        f["Signal"] = sig["Signal"]
        f["Leverage"] = sig["Leverage"]
        out[t] = f
    return out


def daily_entry_rates(mode: str) -> dict:
    """Entries per regime-eligible flat bar in the strategy's own OOS signals."""
    rates = {}
    from backtester import get_asset_profile
    for t, f in daily_frames(mode).items():
        f = f[f.index >= EVAL_START]
        s, reg = f["Signal"].to_numpy(), f["Regime"].to_numpy()
        allow_short = get_asset_profile(t)["allow_short"]
        elig_regs = {"Bull", "Chop"} | ({"Bear"} if mode == "aggressive" and allow_short else set())
        flat_elig = sum(1 for i in range(1, len(s)) if s[i - 1] == 0 and reg[i] in elig_regs)
        entries = int(((s[1:] != 0) & (s[:-1] == 0)).sum())
        rates[t] = entries / flat_elig if flat_elig else 0.0
    return rates


# ── Job runner ───────────────────────────────────────────────────────────────

def run_job(job: dict) -> dict:
    bot = job["bot"]
    if bot == "daily":
        frames = (daily_frames(job["mode"]) if job.get("rseed") is None
                  else daily_frames(job["mode"], job["rseed"], job["p_map"]))
        spec = make_spec("daily")
        if job.get("state_exits"):
            spec.decide = with_state_exits(spec.decide, spec.hl_map)
    else:
        frames = strat_frames(bot, job["thr"], job["mult"], job.get("variant", "base"),
                              job.get("rseed", 0), job.get("source", "binance"))
        spec = make_spec(bot, job["mult"])
    if job.get("state_exits"):
        spec.decide = with_state_exits(spec.decide, spec.hl_map)
    n, idx = union_len(frames, None)
    if job["cadence"] == "full":
        mask = full_cadence(n)
    elif job["cadence"] == "throttled":
        mask = throttled_cadence(n, MEAN_GAP_BARS[bot], job["cseed"])
    else:  # daily slot delivery probability
        mask = bernoulli_cadence(n, job["p_deliver"], job["cseed"])
    res = simulate(spec, frames, mask, start=job.get("start", EVAL_START), end=job.get("end"))
    return {"job": {k: v for k, v in job.items() if k != "p_map"}, "inc": to_daily(res),
            "trades": res.trades, "rejected": res.rejected, "runs": res.runs}


def run_all(jobs, label):
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        out = list(ex.map(run_job, jobs, chunksize=4))
    print(f"[{label}] {len(jobs)} sims in {time.time() - t0:.0f}s", flush=True)
    return out


# ── Walk-forward stitching ───────────────────────────────────────────────────

def wf_windows(end: pd.Timestamp):
    wins, s = [], EVAL_START
    while s + pd.Timedelta(days=WF_IS_DAYS + WF_OOS_DAYS) <= end + pd.Timedelta(days=WF_OOS_DAYS):
        is_s, is_e = s, s + pd.Timedelta(days=WF_IS_DAYS)
        oos_e = min(is_e + pd.Timedelta(days=WF_OOS_DAYS), end)
        if is_e >= end:
            break
        wins.append((is_s, is_e, is_e, oos_e))
        s += pd.Timedelta(days=WF_OOS_DAYS)
    return wins


def slice_result(r, s, e):
    inc = r["inc"][(r["inc"].index >= s) & (r["inc"].index < e)]
    tr = r["trades"]
    tr = tr[(tr["entry_time"] >= s) & (tr["entry_time"] < e)] if len(tr) else tr
    return inc, tr


def stitch(results_by_combo, choices):
    incs, trs = [], []
    for (_, _, oos_s, oos_e), combo in choices:
        inc, tr = slice_result(results_by_combo[combo], oos_s, oos_e)
        incs.append(inc)
        trs.append(tr)
    return pd.concat(incs), pd.concat([t for t in trs if len(t)], ignore_index=True)


def is_sortino(inc, capital):
    pnl = inc.sum(axis=1)
    eq = capital + pnl.cumsum()
    r = eq.pct_change().fillna(pnl.iloc[0] / capital)
    dd = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
    return float(r.mean() / dd * np.sqrt(365)) if dd > 0 else 0.0


# ── Main ─────────────────────────────────────────────────────────────────────

def summarize_seeds(rows: list[dict], keys=("ann_net_pct", "sortino", "sharpe", "trades", "pct_stop_exits",
                                            "max_dd_pct", "win_rate_pct")) -> dict:
    df = pd.DataFrame(rows)
    out = {}
    for k in keys:
        out[f"{k}_p10"] = df[k].quantile(0.1)
        out[f"{k}_median"] = df[k].median()
        out[f"{k}_p90"] = df[k].quantile(0.9)
    return out


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    from signals import parity_check
    for msg in parity_check(bars("binance", "BTC-USD", "1h"), bars("binance", "SOL-USD", "30m"), load_regimes("ETH-USD")):
        print("parity:", msg, flush=True)
    W = lambda name, df: df.to_csv(os.path.join(RESULTS_DIR, name), index=False)  # noqa: E731
    combos = [(thr, m) for thr in THRESHOLDS for m in STOPS]
    end = min(bars("binance", t, "1h").index[-1] for t in TICKERS).normalize()

    all_rows, seed_rows, rand_rows, regime_rows, fold_rows, var_rows = [], [], [], [], [], []

    def add_regimes(label, bot, trades):
        if len(trades):
            regime_rows.extend(regime_table(trades, bot, label))

    for bot in ("intraday", "aggressive"):
        cap = CAPITAL[bot]
        # 1. Grid, full cadence + throttled
        jobs = [{"bot": bot, "thr": t, "mult": m, "cadence": "full"} for t, m in combos]
        jobs += [{"bot": bot, "thr": t, "mult": m, "cadence": "throttled", "cseed": s}
                 for t, m in combos for s in range(N_THROTTLE)]
        res = run_all(jobs, f"{bot} grid")
        full = {(r["job"]["thr"], r["job"]["mult"]): r for r in res if r["job"]["cadence"] == "full"}
        thr_ = {}
        for r in res:
            if r["job"]["cadence"] == "throttled":
                thr_.setdefault((r["job"]["thr"], r["job"]["mult"]), []).append(r)

        for c in combos:
            m = compute_metrics(full[c]["inc"], full[c]["trades"], cap)
            all_rows.append({"bot": bot, "scenario": "grid_full_history", "thr": c[0], "stop_mult": c[1],
                             "cadence": "full", "asset": "POOLED", "rejected_orders": full[c]["rejected"], **m})
            seeds = [compute_metrics(r["inc"], r["trades"], cap) for r in thr_[c]]
            all_rows.append({"bot": bot, "scenario": "grid_full_history", "thr": c[0], "stop_mult": c[1],
                             "cadence": "throttled_median", "asset": "POOLED",
                             **{k: float(np.median([s[k] for s in seeds])) for k in seeds[0]}})
        cur = CURRENT[bot]
        for t in TICKERS:
            m = compute_metrics(full[cur]["inc"], full[cur]["trades"], cap, ticker=t)
            all_rows.append({"bot": bot, "scenario": "as_coded_full_history", "thr": cur[0], "stop_mult": cur[1],
                             "cadence": "full", "asset": t, **m})
        all_rows.append({"bot": bot, "scenario": "as_coded_full_history", "thr": cur[0], "stop_mult": cur[1],
                         "cadence": "full", "asset": "POOLED",
                         "rejected_orders": full[cur]["rejected"], **compute_metrics(full[cur]["inc"], full[cur]["trades"], cap)})
        for i, r in enumerate(thr_[cur]):
            seed_rows.append({"bot": bot, "scenario": "as_coded_full_history", "seed": i,
                              "runs": r["runs"], **compute_metrics(r["inc"], r["trades"], cap)})
        full[cur]["trades"].to_csv(os.path.join(RESULTS_DIR, f"trades_{bot}_as_coded_full.csv"), index=False)
        add_regimes("as_coded_full", bot, full[cur]["trades"])
        add_regimes("as_coded_throttled_seed0", bot, thr_[cur][0]["trades"])

        # 2. Walk-forward: choose (thr, mult) by IS Sortino at full cadence
        wins = wf_windows(end)
        choices = []
        for w in wins:
            scores = {c: is_sortino(full[c]["inc"][(full[c]["inc"].index >= w[0]) & (full[c]["inc"].index < w[1])], cap)
                      for c in combos}
            best = max(combos, key=lambda c: scores[c])
            choices.append((w, best))
            fold_rows.append({"bot": bot, "is_start": w[0].date(), "is_end": w[1].date(), "oos_start": w[2].date(),
                              "oos_end": w[3].date(), "thr": best[0], "stop_mult": best[1],
                              "is_sortino": round(scores[best], 3)})
        wf_inc, wf_tr = stitch(full, choices)
        wf_m = compute_metrics(wf_inc, wf_tr, cap)
        all_rows.append({"bot": bot, "scenario": "walk_forward_oos", "cadence": "full", "asset": "POOLED", **wf_m})
        for t in TICKERS:
            all_rows.append({"bot": bot, "scenario": "walk_forward_oos", "cadence": "full", "asset": t,
                             **compute_metrics(wf_inc, wf_tr, cap, ticker=t)})
        wf_tr.to_csv(os.path.join(RESULTS_DIR, f"trades_{bot}_walk_forward_full.csv"), index=False)
        add_regimes("walk_forward_full", bot, wf_tr)
        wf_seed = []
        for s in range(N_THROTTLE):
            by = {c: thr_[c][s] for c in combos}
            inc, tr = stitch(by, choices)
            mm = compute_metrics(inc, tr, cap)
            wf_seed.append(mm)
            seed_rows.append({"bot": bot, "scenario": "walk_forward_oos", "seed": s, **mm})
        all_rows.append({"bot": bot, "scenario": "walk_forward_oos", "cadence": "throttled_median", "asset": "POOLED",
                         **{k: float(np.median([x[k] for x in wf_seed])) for k in wf_seed[0]}})

        # 3. Random-entry control (same exits, coin-flip entries at matched rate)
        jobs = [{"bot": bot, "thr": t, "mult": m, "variant": "random", "rseed": s, "cadence": "full"}
                for t, m in combos for s in range(N_RANDOM)]
        jobs += [{"bot": bot, "thr": cur[0], "mult": cur[1], "variant": "random", "rseed": s,
                  "cadence": "throttled", "cseed": s} for s in range(N_RANDOM)]
        rres = run_all(jobs, f"{bot} random")
        rfull = {}
        for r in rres:
            if r["job"]["cadence"] == "full":
                rfull.setdefault((r["job"]["thr"], r["job"]["mult"]), {})[r["job"]["rseed"]] = r
        rthr = [r for r in rres if r["job"]["cadence"] == "throttled"]

        def rand_summary(label, strat_m, rand_ms):
            so = np.array([x["sortino"] for x in rand_ms])
            nr = np.array([x["ann_net_pct"] for x in rand_ms])
            rand_rows.append({"bot": bot, "scenario": label, "strategy_sortino": strat_m["sortino"],
                              "random_sortino_p05": np.quantile(so, 0.05), "random_sortino_median": np.median(so),
                              "random_sortino_p95": np.quantile(so, 0.95),
                              "strategy_pctile_vs_random": float((so < strat_m["sortino"]).mean() * 100),
                              "strategy_ann_net_pct": strat_m["ann_net_pct"],
                              "random_ann_net_median": np.median(nr),
                              "strategy_trades": strat_m["trades"],
                              "random_trades_median": np.median([x["trades"] for x in rand_ms])})

        rand_summary("as_coded_full", compute_metrics(full[cur]["inc"], full[cur]["trades"], cap),
                     [compute_metrics(r["inc"], r["trades"], cap) for r in rfull[cur].values()])
        rand_summary("as_coded_throttled", float_median(seed_rows, bot, "as_coded_full_history"),
                     [compute_metrics(r["inc"], r["trades"], cap) for r in rthr])
        wf_rand = []
        for s in range(N_RANDOM):
            inc, tr = stitch({c: rfull[c][s] for c in combos}, choices)
            wf_rand.append(compute_metrics(inc, tr, cap))
        rand_summary("walk_forward_full", wf_m, wf_rand)

        # 4. Variants (as-coded params): trailing exit, HMM regime gate
        if bot == "intraday":
            jobs = []
            for v in ("trail", "gate"):
                jobs.append({"bot": bot, "thr": cur[0], "mult": cur[1], "variant": v, "cadence": "full"})
                jobs += [{"bot": bot, "thr": cur[0], "mult": cur[1], "variant": v, "cadence": "throttled", "cseed": s}
                         for s in range(N_THROTTLE)]
            vres = run_all(jobs, "intraday variants")
            for v in ("trail", "gate"):
                f = [r for r in vres if r["job"]["variant"] == v and r["job"]["cadence"] == "full"][0]
                th = [r for r in vres if r["job"]["variant"] == v and r["job"]["cadence"] == "throttled"]
                fm = compute_metrics(f["inc"], f["trades"], cap)
                ths = [compute_metrics(r["inc"], r["trades"], cap) for r in th]
                var_rows.append({"bot": bot, "variant": v, "cadence": "full", "asset": "POOLED", **fm})
                var_rows.append({"bot": bot, "variant": v, "cadence": "throttled_median", "asset": "POOLED",
                                 **{k: float(np.median([x[k] for x in ths])) for k in ths[0]}})
                for t in TICKERS:
                    var_rows.append({"bot": bot, "variant": v, "cadence": "full", "asset": t,
                                     **compute_metrics(f["inc"], f["trades"], cap, ticker=t)})
                add_regimes(f"variant_{v}_full", bot, f["trades"])
                f["trades"].to_csv(os.path.join(RESULTS_DIR, f"trades_intraday_{v}_full.csv"), index=False)

        # 5. Hyperliquid cross-check on the window HL actually serves
        hl_start = max(bars("hl", t, INTERVAL[bot]).index[0] for t in TICKERS) + pd.Timedelta(days=7)
        cj = [{"bot": bot, "thr": cur[0], "mult": cur[1], "cadence": "full", "source": src, "start": hl_start}
              for src in ("hl", "binance")]
        for r in run_all(cj, f"{bot} hl-crosscheck"):
            all_rows.append({"bot": bot, "scenario": f"hl_window_{r['job']['source']}", "thr": cur[0],
                             "stop_mult": cur[1], "cadence": "full", "asset": "POOLED",
                             **compute_metrics(r["inc"], r["trades"], cap)})

    # ── Daily bot ──
    cap = CAPITAL["daily"]
    for mode in ("standard", "aggressive"):
        jobs = [{"bot": "daily", "mode": mode, "cadence": "full"}]
        jobs += [{"bot": "daily", "mode": mode, "cadence": "bernoulli", "p_deliver": p, "cseed": s}
                 for p in DAILY_DELIVERY for s in range(N_THROTTLE)]
        p_map = daily_entry_rates(mode)
        jobs += [{"bot": "daily", "mode": mode, "cadence": "full", "rseed": s, "p_map": p_map} for s in range(N_RANDOM)]
        dres = run_all(jobs, f"daily {mode}")
        f = [r for r in dres if r["job"]["cadence"] == "full" and r["job"].get("rseed") is None][0]
        fm = compute_metrics(f["inc"], f["trades"], cap)
        all_rows.append({"bot": f"daily_{mode}", "scenario": "walk_forward_oos", "cadence": "full",
                         "asset": "POOLED", "rejected_orders": f["rejected"], **fm})
        for t in TICKERS:
            all_rows.append({"bot": f"daily_{mode}", "scenario": "walk_forward_oos", "cadence": "full", "asset": t,
                             **compute_metrics(f["inc"], f["trades"], cap, ticker=t)})
        for p in DAILY_DELIVERY:
            th = [compute_metrics(r["inc"], r["trades"], cap) for r in dres
                  if r["job"]["cadence"] == "bernoulli" and r["job"]["p_deliver"] == p]
            all_rows.append({"bot": f"daily_{mode}", "scenario": "walk_forward_oos",
                             "cadence": f"delivery_{p}_median", "asset": "POOLED",
                             **{k: float(np.median([x[k] for x in th])) for k in th[0]}})
            for i, x in enumerate(th):
                seed_rows.append({"bot": f"daily_{mode}", "scenario": f"walk_forward_oos_delivery_{p}", "seed": i, **x})
        rm = [compute_metrics(r["inc"], r["trades"], cap) for r in dres if r["job"].get("rseed") is not None]
        bot = f"daily_{mode}"
        so = np.array([x["sortino"] for x in rm])
        rand_rows.append({"bot": bot, "scenario": "walk_forward_full", "strategy_sortino": fm["sortino"],
                          "random_sortino_p05": np.quantile(so, 0.05), "random_sortino_median": np.median(so),
                          "random_sortino_p95": np.quantile(so, 0.95),
                          "strategy_pctile_vs_random": float((so < fm["sortino"]).mean() * 100),
                          "strategy_ann_net_pct": fm["ann_net_pct"],
                          "random_ann_net_median": np.median([x["ann_net_pct"] for x in rm]),
                          "strategy_trades": fm["trades"], "random_trades_median": np.median([x["trades"] for x in rm])})
        f["trades"].to_csv(os.path.join(RESULTS_DIR, f"trades_daily_{mode}_walk_forward_full.csv"), index=False)
        add_regimes("walk_forward_full", bot, f["trades"])

    W("baselines.csv", baselines(end, wf_windows(end)[0][2]))
    W("scenarios.csv", pd.DataFrame(all_rows))
    W("throttled_seeds.csv", pd.DataFrame(seed_rows))
    W("random_control.csv", pd.DataFrame(rand_rows))
    W("regime_attribution.csv", pd.DataFrame(regime_rows))
    W("intraday_wf_folds.csv", pd.DataFrame(fold_rows))
    W("variants.csv", pd.DataFrame(var_rows))
    print("done")


def baselines(end, wf_oos_start) -> pd.DataFrame:
    """Buy-and-hold BTC and a daily-rebalanced equal-weight basket (yfinance closes)."""
    from data_fetch import load_daily
    closes = pd.DataFrame({t: df["Close"] for t, df in load_daily().items()})
    rows = []
    for label, s in (("full_history", EVAL_START), ("walk_forward_oos", wf_oos_start)):
        c = closes[(closes.index >= s) & (closes.index <= end)]
        rets = {"buy_hold_BTC": c["BTC-USD"].pct_change(), "equal_weight_7": c.pct_change().mean(axis=1)}
        for name, r in rets.items():
            r = r.fillna(0.0)
            r.iloc[0] -= TAKER_FEE_BH
            eq = (1 + r).cumprod()
            yrs = len(r) / 365.0
            dd = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
            rows.append({"window": label, "start": c.index[0].date(), "end": c.index[-1].date(), "baseline": name,
                         "ann_net_pct": (eq.iloc[-1] ** (1 / yrs) - 1) * 100,
                         "sharpe": r.mean() / r.std() * np.sqrt(365), "sortino": r.mean() / dd * np.sqrt(365),
                         "max_dd_pct": ((eq / eq.cummax()) - 1).min() * 100, "total_return_pct": (eq.iloc[-1] - 1) * 100})
    return pd.DataFrame(rows)


TAKER_FEE_BH = 0.00045 + 0.0001


def float_median(seed_rows, bot, scenario):
    rows = [r for r in seed_rows if r["bot"] == bot and r["scenario"] == scenario]
    keys = [k for k in rows[0] if k not in ("bot", "scenario", "seed", "runs")]
    return {k: float(np.median([r[k] for r in rows])) for k in keys}


if __name__ == "__main__":
    main()
