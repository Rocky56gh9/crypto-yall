# Crypto Y'all — Regime-Adaptive Trading System

A multi-strategy algorithmic trading system for crypto perpetual futures on Hyperliquid DEX. Combines HMM-based regime detection, 2-pole Butterworth oscillator signals, and three independent trading bots running on different timeframes.

**Live dashboard:** https://crypto-yall-8s3evlspcczux5ztdmat9e.streamlit.app/
**GitHub repo:** https://github.com/aicodepathways/crypto-yall

---

## Quick Links by Role

### If you're **Josh** (or a non-technical operator)

Start here. These are written in plain English with click-by-click instructions.

| Guide | When to read |
|-------|--------------|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Daily operations: checking on bots, pausing them, understanding alerts |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | When something looks wrong and you need to figure out what to do |
| [docs/ADDING_COMMUNITY_USERS.md](docs/ADDING_COMMUNITY_USERS.md) | **Important**: honest explanation of what's possible (and not) for community rollout |
| [docs/USER_SETUP_GUIDE.md](docs/USER_SETUP_GUIDE.md) | Full setup guide for a community member to run their own personal bot (Option B from above) |
| [docs/AI_ASSISTED_SETUP.md](docs/AI_ASSISTED_SETUP.md) | Skip the manual reading — paste a prompt into ChatGPT/Claude and let AI walk you through setup |
| [docs/MAINNET_LAUNCH.md](docs/MAINNET_LAUNCH.md) | Step-by-step for going from testnet to real money |
| [docs/FORK_CHANGES.md](docs/FORK_CHANGES.md) | What this fork adds: exchange-side stops, close-only pause, per-bot sub-accounts, failure alerts |

### If you're a **developer or technical operator**

The rest of this README is the deep technical reference. Read on.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [The Three Bots](#2-the-three-bots)
3. [Performance to Date](#3-performance-to-date)
4. [Architecture](#4-architecture)
5. [File Reference](#5-file-reference)
6. [Dashboard](#6-dashboard)
7. [Notifications](#7-notifications)
8. [Operating the System](#8-operating-the-system)
9. [Making Changes](#9-making-changes)
10. [Risk Controls](#10-risk-controls)
11. [Failure Modes & Troubleshooting](#11-failure-modes--troubleshooting)
12. [Going to Mainnet](#12-going-to-mainnet)
13. [Credentials & Access](#13-credentials--access)

---

## 1. System Overview

### What it does

Three trading bots run independently on the same Hyperliquid account. Each bot:
- Pulls market data (yfinance for daily, Hyperliquid candles for intraday)
- Computes technical signals (2-pole Butterworth oscillator + HMM regime classifier for the daily bot)
- Compares its current positions to what the strategy says they should be
- Places market orders to reconcile
- Logs every fill to a private GitHub Gist
- Sends email + Telegram alerts on every execution

### What it trades

Seven perpetual futures pairs on Hyperliquid:
- **Large caps** (3x max leverage, shorting allowed): BTC, ETH
- **Mid caps** (1.5x max leverage, no shorting): SOL, AVAX, LINK, SUI, XRP

> **Note:** LINK and XRP are not listed on Hyperliquid **testnet**. Both will be available on mainnet. The bots automatically skip unavailable assets.

### Strategy types

- **Mean reversion** with regime gate (Daily bot)
- **Mean reversion** pure oscillator (Intraday Standard bot)
- **Mean reversion** with pyramiding + tighter thresholds (Aggressive bot)

All three use the same core 2-pole Butterworth low-pass filter and z-score normalized oscillator — but with different parameters and timeframes.

---

## 2. The Three Bots

### Bot 1: Daily (Conservative)

**File:** `hyperliquid_executor.py`
**Workflow:** `.github/workflows/execute-trades.yml`
**Schedule:** Daily at 00:15 UTC (often delayed 30-60min by GitHub Actions free tier)
**State Gist:** `d35732f9c123e95a4dc13a51855d21de` (`TRADING_GIST_ID`)

**Strategy:**
- Pulls daily OHLCV from yfinance (anchored to 2022-03-01 start date for fold stability)
- Computes HMM regimes (Bull / Bear / Chop)
- Generates signals based on regime + 2-pole oscillator + volatility-scaled momentum + ATR Chandelier exit
- Aggressive mode active by default (probabilistic leverage, pyramiding, shorting)

**Risk Controls:**
- Capital: $10,000 mock (testnet) / configurable on mainnet
- Position size: 1% of capital per trade
- Max positions: 4 concurrent
- Daily drawdown halt: 5%
- Kill switch: `KILL_SWITCH` GitHub variable (ON / OFF)

**When it fires:**
- Once per day, ~00:15 UTC
- Only places trades when signals change (open / close / sync) or when bot state is out of sync with strategy state

---

### Bot 2: Intraday Standard

**File:** `intraday_executor.py`
**Workflow:** `.github/workflows/execute-intraday.yml`
**Schedule:** Every hour at :05 UTC
**State Gist:** `02cbe06fb1c4eb8afb5fad321aa3a251` (`INTRADAY_GIST_ID`)

**Strategy:**
- Pulls 1-hour candles directly from Hyperliquid (no auth needed)
- Pure 2-pole oscillator, no HMM regime filter
- Z-score normalized oscillator with ±0.5 thresholds
- Long when oscillator crosses up through -0.5
- Short when oscillator crosses down through +0.5 (only large caps)
- Exit on zero crossing OR 2x ATR stop

**Risk Controls:**
- Capital: $5,000 mock
- Position size: 1% of capital per trade
- Leverage: 2x fixed
- Max positions: 2 concurrent
- Daily drawdown halt: 5%
- Kill switch: `INTRADAY_KILL_SWITCH` GitHub variable

**When it fires:**
- Every hour
- Aimed at Josh's manual approach with his members — active mean reversion on 1h timeframe

---

### Bot 3: Aggressive

**File:** `aggressive_executor.py`
**Workflow:** `.github/workflows/execute-aggressive.yml`
**Schedule:** Every 30 minutes
**State Gist:** `0917280713a7781dc72a984147eef295` (`AGGRESSIVE_GIST_ID`)

**Strategy:**
- Same z-score 2-pole oscillator but on 30-minute candles
- Tighter ±0.25 entry thresholds (vs ±0.5 standard) → more entries
- **Pyramiding**: can add up to 2 extra positions on existing winners when oscillator re-tests entry zone
- 1.5x ATR stop loss (tighter than standard's 2x)
- Fires ~3x more signals than standard intraday

**Risk Controls:**
- Capital: $3,000 mock
- Position size: 1.5% per trade + 0.5% per pyramid add (max 2 adds = 2.5% total per asset)
- Leverage: 4x large caps (capped at 3x by Hyperliquid), 2x mid caps
- Max positions: 4 concurrent
- Daily drawdown halt: 3% (tighter than other bots to control extra risk)
- Kill switch: `AGGRESSIVE_KILL_SWITCH` GitHub variable

**When it fires:**
- Every 30 minutes
- Built for traders who want high activity

---

## 3. Performance to Date

**As of June 11, 2026 (50 days on testnet):**

| Bot | Starting | Current | Net P&L | Open Positions |
|-----|----------|---------|---------|----------------|
| Daily | $999.00 | **$1,027.29** | **+2.83%** | BTC short @ $66,109 |
| Intraday | $999.00 | **$1,026.06** | **+2.71%** | SOL long, AVAX long |
| Aggressive | $999.00 | **$1,024.88** | **+2.59%** | BTC, ETH, SOL, SUI longs |

### Market context

- **BTC: -25% over the same period** ($77,500 → ~$63,500)
- **ETH: -25%**
- All three bots produced **positive returns in a sharply declining market**

### Trade counts

| Bot | Total trades | Trades/week |
|-----|--------------|-------------|
| Daily | 18 | ~3 |
| Intraday | 81 | ~12 |
| Aggressive | 42 (in 13 days) | ~22 |

### Aggressive bot historical backtest

If the aggressive bot had run since inception (Apr 22), backtest shows:
- Final equity: $979.62
- Net: -1.94% over 7 weeks
- 258 hypothetical trades, 30.6% win rate, avg win +$0.75 / avg loss -$0.44

The losses concentrated in April / mid-May choppy markets. Performance accelerated once directional moves started in late May.

### What this validates

1. **Capital preservation works in chop** — early period was ~flat
2. **Trend capture works in directional moves** — late period produced strong positive returns
3. **Risk controls fire correctly** — intraday halted on Apr 27 (-5.15% DD), resumed next day
4. **Strategies are complementary** — daily catches slow trends, intraday catches swings, aggressive captures small moves

---

## 4. Architecture

```
                     ┌────────────────────┐
                     │  GitHub Actions    │
                     │  (3 cron jobs)     │
                     └─────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
        ┌────────────┐  ┌────────────┐  ┌────────────┐
        │   Daily    │  │  Intraday  │  │ Aggressive │
        │  Executor  │  │  Executor  │  │  Executor  │
        └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
              │               │               │
              │       ┌───────┴───────┐       │
              │       │               │       │
              ▼       ▼               ▼       ▼
       ┌─────────┐ ┌─────────┐    ┌────────────┐
       │yfinance │ │HL candle│    │Hyperliquid │
       │(daily)  │ │ (1h/30m)│    │ Exchange   │
       └─────────┘ └─────────┘    └────────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │  Trade fills         │
                            └─────────┬────────────┘
                                      │
                ┌─────────────────────┼─────────────────────┐
                ▼                     ▼                     ▼
       ┌────────────┐         ┌────────────┐        ┌──────────────┐
       │ Gmail SMTP │         │ Telegram   │        │ GitHub Gists │
       │ (alerts)   │         │ Bot (alerts│        │ (state)      │
       └────────────┘         └────────────┘        └──────┬───────┘
                                                           │
                                                           ▼
                                                ┌────────────────────┐
                                                │ Streamlit Cloud    │
                                                │ Dashboard (read)   │
                                                └────────────────────┘
```

### Data flow

1. **GitHub Actions** triggers each bot on its schedule
2. Each bot **fetches market data** (yfinance for daily, Hyperliquid for intraday/30m)
3. Computes **signals** using its strategy module
4. Loads **prior state** from its private GitHub Gist (owned positions, drawdown tracking)
5. Calls **Hyperliquid API** to read current account state + place market orders
6. Sends **email + Telegram notifications** on fills
7. Writes **updated state** back to its Gist
8. **Streamlit dashboard** reads the Gists in real-time to display positions, P&L, trade history

### Why GitHub Gists for state

- Free, private, version-controlled
- No database needed
- Survives container restarts (Streamlit Cloud, GitHub Actions)
- Each bot has its own Gist for clean separation

### Why GitHub Actions for execution

- Free CI/CD with cron support
- Runs on Azure cloud (non-US, helps with Hyperliquid US restriction concerns)
- Built-in secret management
- Logs every run for debugging

### Shared Hyperliquid account model

All three bots use the **same Hyperliquid account** but each tracks its own positions via `owned_coins` in its Gist. Two side effects:

1. **Positions can net on the exchange** — if Daily opens ETH long and Aggressive opens ETH short, Hyperliquid sees the net.
2. **Margin is shared** — total margin usage is summed across all three bots.

**Note on sub-accounts:** Hyperliquid sub-accounts would give each bot its own segregated margin account and eliminate netting. However, they require $100,000+ in mainnet trading volume to unlock, so they're unavailable to most users. The shared-account model works fine with the built-in ownership tracking — netting is a minor efficiency issue, not a safety one.

---

## 5. File Reference

### Trading logic

| File | Purpose |
|------|---------|
| `data_loader.py` | yfinance daily OHLCV loader. Anchored start date `2022-03-01`. |
| `intraday_data_loader.py` | Hyperliquid candle fetcher for 1h / 30m / any timeframe |
| `indicators.py` | Butterworth filter, 2-pole oscillator, ATR, volatility-scaled momentum |
| `hmm_engine.py` | Causal HMM regime detection (Bull / Bear / Chop) |
| `strategy.py` | Daily bot signal generation logic |
| `intraday_strategy.py` | 1-hour 2-pole oscillator signals (z-score normalized) |
| `aggressive_strategy.py` | 30-min 2-pole oscillator with pyramiding |
| `backtester.py` | Walk-forward backtest engine + asset profile definitions |
| `signal_utils.py` | Maps raw signals to action types (buy, sell, hold, etc.) |

### Execution

| File | Purpose |
|------|---------|
| `hyperliquid_executor.py` | Daily bot trade execution + email/Telegram senders |
| `intraday_executor.py` | Intraday bot trade execution |
| `aggressive_executor.py` | Aggressive bot trade execution with pyramid logic |
| `test_trade.py` | Standalone connection test — places + closes a $10 BTC trade |

### Notification

| File | Purpose |
|------|---------|
| `notifier.py` | Signal-change alerts (separate from execution alerts) |

### Dashboard

| File | Purpose |
|------|---------|
| `app.py` | Streamlit dashboard (live trading sections, charts, optional backtest) |
| `trading_state.py` | Reads state Gists for the dashboard |

### Config

| File | Purpose |
|------|---------|
| `requirements.txt` | Python dependencies |
| `runtime.txt` | Python version pin (`python-3.12.0`) |
| `.streamlit/config.toml` | Dark theme + page settings |

### Workflows (`.github/workflows/`)

| File | Schedule | Purpose |
|------|----------|---------|
| `signal-check.yml` | Every 6 hours | Standalone signal change alerts (notifier.py) |
| `execute-trades.yml` | Daily 00:15 UTC | Daily bot execution |
| `execute-intraday.yml` | Hourly :05 | Intraday standard bot execution |
| `execute-aggressive.yml` | Every 30 min | Aggressive bot execution |
| `test-trade.yml` | Manual only | Connection test |

---

## 6. Dashboard

**URL:** https://crypto-yall-8s3evlspcczux5ztdmat9e.streamlit.app/

### Sections (top to bottom)

1. **Sidebar**
   - Asset selector (7 assets)
   - Strategy mode toggle (Standard / Smart Aggressive)
   - Capital + leverage simulator
   - Profile info (effective leverage, shorting, ATR mult)

2. **Live Market Status** — 5 cards
   - Current Price
   - Current Regime (Bull / Bear / Chop)
   - Active Strategy
   - Current Signal (BUY / HOLD LONG / SELL / etc.)
   - Bull or Bear Confidence

3. **Live Trading (Hyperliquid)** — Daily bot
   - Bot status (ACTIVE / PAUSED)
   - Account equity
   - Open positions table
   - Recent trades table

4. **Intraday Trading (1h)** — Intraday Standard bot
   - Status, equity, positions, current 1h signals per asset, recent trades

5. **Aggressive Trading (30m)** — Aggressive bot
   - Status, equity, positions, pyramid counts, current 30m signals, recent trades

6. **Price & Butterworth Filter with HMM Regimes** — main chart
   - Candlestick + Butterworth filter overlay
   - 2-pole oscillator subchart
   - Regime bands (Bull green / Bear red / Chop gray)

7. **Regime Distribution** — Pie chart of regime percentages

8. **Walk-Forward Backtest Analysis** — *hidden behind a checkbox* (takes 30-60s to compute)
   - OOS performance metric cards
   - Equity curve (standard vs aggressive)
   - Side-by-side comparison
   - Fold parameter expandable table

### Streamlit Secrets needed

Set at https://share.streamlit.io > app settings > Secrets:

```toml
GIST_TOKEN = "ghp_..."
TRADING_GIST_ID = "d35732f9c123e95a4dc13a51855d21de"
INTRADAY_GIST_ID = "02cbe06fb1c4eb8afb5fad321aa3a251"
AGGRESSIVE_GIST_ID = "0917280713a7781dc72a984147eef295"
```

---

## 7. Notifications

### Email (Gmail SMTP)

- **Sender:** `nocodepathways@gmail.com` (configured via app password)
- **Recipients:** Set in `NOTIFY_EMAILS` secret (comma-separated)
- Currently sends to: `nocodepathways@gmail.com,josh@cryptoyall.co`
- Light theme HTML (readable in all clients)

### Telegram

- **Bot:** `@Crypto_yall_bot`
- **Direct link:** https://t.me/Crypto_yall_bot
- **Chat IDs:** Set in `TELEGRAM_CHAT_ID` secret (comma-separated)
- Currently sends to: Brendan's chat + Josh's chat

### When notifications fire

| Event | Signal Alert | Execution Alert |
|-------|--------------|-----------------|
| Signal transition (notifier.py every 6h) | ✓ | — |
| Daily bot trade | — | ✓ |
| Intraday bot trade (when fills > 0) | — | ✓ |
| Aggressive bot trade (when fills > 0) | — | ✓ |
| Drawdown halt triggered | — | ✓ (urgent) |
| Client init failure | — | ✓ (error) |

### Adding new alert recipients

**Email:** Update `NOTIFY_EMAILS` secret:
```bash
gh secret set NOTIFY_EMAILS -b "you@example.com,josh@cryptoyall.co,new@person.com"
```

**Telegram:**
1. New person installs Telegram, messages `@Crypto_yall_bot` with `/start`
2. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find their chat ID
3. Update `TELEGRAM_CHAT_ID` secret:
```bash
gh secret set TELEGRAM_CHAT_ID -b "8438419459,5038092102,NEW_CHAT_ID"
```

---

## 8. Operating the System

### Trigger a manual run

```bash
gh workflow run execute-trades.yml      # Daily bot
gh workflow run execute-intraday.yml    # Intraday Standard bot
gh workflow run execute-aggressive.yml  # Aggressive bot
gh workflow run signal-check.yml        # Signal alert checker
gh workflow run test-trade.yml          # Connection test
```

### Watch a workflow run

```bash
gh run view <RUN_ID> --log | grep -E "(executor|filled|Error)"
gh run list --workflow=execute-aggressive.yml --limit 5
```

### Check current bot state

```bash
# Daily
gh gist view d35732f9c123e95a4dc13a51855d21de -f trading_state.json | jq '.last_equity, .open_positions, .owned_coins'

# Intraday
gh gist view 02cbe06fb1c4eb8afb5fad321aa3a251 -f intraday_state.json | jq '.last_equity, .open_positions'

# Aggressive
gh gist view 0917280713a7781dc72a984147eef295 -f aggressive_state.json | jq '.last_equity, .open_positions, .pyramid_state'
```

### Pause a single bot (kill switch)

```bash
gh variable set KILL_SWITCH -b "OFF"             # halts Daily bot
gh variable set INTRADAY_KILL_SWITCH -b "OFF"    # halts Intraday Standard
gh variable set AGGRESSIVE_KILL_SWITCH -b "OFF"  # halts Aggressive

# Resume
gh variable set KILL_SWITCH -b "ON"
```

### Pause ALL bots

```bash
gh variable set KILL_SWITCH -b "OFF"
gh variable set INTRADAY_KILL_SWITCH -b "OFF"
gh variable set AGGRESSIVE_KILL_SWITCH -b "OFF"
```

> **Note:** Kill switch only prevents new orders. Existing positions stay open. To close everything, disable kill switches, then manually close positions on Hyperliquid UI, then re-enable.

### Reset signal state (force re-alert)

```bash
gh gist edit ad73d92e1fa245c2725e06f60d68d13b -f signal_state.json - <<< '{}'
gh workflow run signal-check.yml
```

### Reset a bot's owned-coins tracking (caution)

If a bot's `owned_coins` gets out of sync with actual Hyperliquid positions:

```bash
# Edit the Gist directly, set "owned_coins" to actual coins held
# Or wipe entirely:
gh gist edit d35732f9c123e95a4dc13a51855d21de -f trading_state.json - <<< '{}'
```

The bot will rebuild state on its next run. Note: trade history will be lost.

---

## 9. Making Changes

### Change capital allocation

| Variable | Current | What it controls |
|----------|---------|------------------|
| `SEGREGATED_CAPITAL` | `10000` | Daily bot capital |
| `INTRADAY_CAPITAL` | `5000` | Intraday Standard capital |
| `AGGRESSIVE_CAPITAL` | `3000` | Aggressive bot capital |

```bash
gh variable set AGGRESSIVE_CAPITAL -b "5000"
```

### Change drawdown halt thresholds

| Variable | Current | What it controls |
|----------|---------|------------------|
| `DAILY_DD_PCT` | `5` | Daily bot daily DD halt |
| `INTRADAY_DD_PCT` | `5` | Intraday Standard daily DD halt |
| `AGGRESSIVE_DD_PCT` | `3` | Aggressive bot daily DD halt |

### Change max concurrent positions

| Variable | Current | What it controls |
|----------|---------|------------------|
| `MAX_POSITIONS` | `4` | Daily bot max positions |
| `INTRADAY_MAX_POSITIONS` | `2` | Intraday Standard max |
| `AGGRESSIVE_MAX_POSITIONS` | `4` | Aggressive bot max |

### Change strategy thresholds (requires code change)

**Intraday Standard** — edit `intraday_strategy.py`:
```python
OSC_UPPER = 0.5          # ↓ for more entries, ↑ for fewer
OSC_LOWER = -0.5
ATR_STOP_MULT = 2.0      # ↓ for tighter stops
```

**Aggressive** — edit `aggressive_strategy.py`:
```python
OSC_UPPER = 0.25         # current — tighter than standard
OSC_LOWER = -0.25
ATR_STOP_MULT = 1.5      # current — tighter
BW_CUTOFF_30M = 0.1      # filter aggressiveness
SMA_PERIOD_30M = 20      # smoothing window
```

After editing:
```bash
git add intraday_strategy.py && git commit -m "Tune intraday thresholds" && git push
```

Changes take effect on the next scheduled run.

### Change position sizing

**Edit the executor's constants:**

`hyperliquid_executor.py` line ~65:
```python
POSITION_SIZE_PCT = 0.01  # 1% per trade
```

`aggressive_executor.py` line ~44-45:
```python
POSITION_SIZE_PCT = 0.015  # 1.5% per trade
PYRAMID_SIZE_PCT = 0.005   # 0.5% per pyramid add
```

### Change leverage

**Daily bot:** edit `backtester.py` `ASSET_PROFILES` dict — change `max_bull_leverage`

**Intraday Standard:** edit `intraday_executor.py` line ~277:
```python
leverage = 2.0  # Fixed 2x
```

**Aggressive:** edit `aggressive_executor.py` line ~258:
```python
leverage = min(4.0, profile["max_bull_leverage"] * 1.33)
```

### Change cron schedules

Edit the `.github/workflows/*.yml` files:

```yaml
on:
  schedule:
    - cron: '*/30 * * * *'    # Every 30 min
    - cron: '15 0 * * *'      # Daily 00:15 UTC
    - cron: '5 * * * *'       # Every hour at :05
```

> **GitHub Actions free tier note:** Cron schedules are best-effort. Expect 30-60min delays. Critical timing requires paid tier or self-hosted runners.

### Add a new asset

1. Add to `ASSETS` dict in `hyperliquid_executor.py`, `intraday_executor.py`, `aggressive_executor.py`, `notifier.py`, `app.py`, `data_loader.py`
2. Add Hyperliquid symbol mapping to `HL_TICKER_MAP` / `HL_SYMBOL_MAP`
3. Add to `ASSET_PROFILES` in `backtester.py` (decides leverage + shorting allowed)
4. Verify the symbol exists on Hyperliquid:
```bash
python3 -c "from hyperliquid.info import Info; from hyperliquid.utils import constants; print(list(Info(constants.MAINNET_API_URL, skip_ws=True).all_mids().keys())[:30])"
```

### Switch between testnet and mainnet

```bash
gh variable set HL_TESTNET -b "false"   # mainnet
gh variable set HL_TESTNET -b "true"    # testnet
```

**Before flipping to mainnet:**
1. Verify mainnet wallet has USDC bridged
2. Authorize API wallet on **mainnet** (separate from testnet) at https://app.hyperliquid.xyz/API
3. Lower capital amounts to safe values for first week
4. Tighten DD thresholds if desired
5. Reset trading state Gists (`{}`) so bots start fresh

---

## 10. Risk Controls

### Stack of safety nets (innermost to outermost)

1. **Position-level ATR stop loss**
   - Long: stop at `entry - ATR_STOP_MULT × ATR`
   - Short: stop at `entry + ATR_STOP_MULT × ATR`
   - Currently 2.0x ATR for intraday standard, 1.5x for aggressive

2. **Per-trade position size cap**
   - 1% for daily / standard intraday, 1.5% + pyramids for aggressive
   - Hardcoded in executor, not env-controlled

3. **Max concurrent positions per bot**
   - Daily: 4, Intraday: 2, Aggressive: 4
   - Env-controlled

4. **Daily drawdown halt**
   - Bot auto-pauses for the day if equity drops below threshold from day-start
   - Daily/Intraday: 5%, Aggressive: 3%
   - Resumes next calendar day at 00:00 UTC

5. **Per-bot kill switch**
   - `gh variable set <BOT>_KILL_SWITCH -b "OFF"` halts new orders
   - Manual control

6. **Ownership tracking with stale reconciliation**
   - Each bot only manages positions it opened
   - If another bot or manual action closed a position, ownership state self-cleans on next run

### Drawdown halt mechanics

- Each bot records `day_start_<date>` at first run of the day
- On each subsequent run, computes `(current_equity - day_start) / day_start`
- If ≤ -threshold, sets `halted_today` = today's date and exits
- Subsequent runs same day skip immediately
- Next day, `day_start_<new_date>` is set and trading resumes

### How to override a halt

```bash
# Edit the relevant Gist, remove the "halted_today" key
gh gist view 0917280713a7781dc72a984147eef295 -f aggressive_state.json > /tmp/state.json
# Edit /tmp/state.json, remove "halted_today" and "halt_reason" keys
gh gist edit 0917280713a7781dc72a984147eef295 -f aggressive_state.json < /tmp/state.json
```

---

## 11. Failure Modes & Troubleshooting

### "0 trades executed this cycle" emails

**Cause:** Bot ran but no signal transitions to act on. Normal in choppy markets.

**Fix:** None needed. Will resolve when a signal transitions.

### Workflow fails with `KeyError: 'XRP'` or similar

**Cause:** Asset not listed on current Hyperliquid environment (e.g., XRP/LINK on testnet).

**Fix:** Already handled — the executor filters unavailable assets and skips them. If you see this in older runs, pull the latest code.

### Workflow fails with `Yahoo API requires curl_cffi session`

**Cause:** Stale yfinance/hyperliquid SDK version mismatch.

**Fix:** Already handled — we removed our custom `requests.Session` since yfinance now uses curl_cffi natively.

### Workflow fails with `cannot reshape array of size 0`

**Cause:** yfinance returned empty data, usually rate-limited.

**Fix:** Already handled — data_loader.py retries 3 times with exponential backoff.

### `User or API Wallet does not exist`

**Cause:** API wallet authorized on mainnet but not testnet (or vice versa).

**Fix:** Visit https://app.hyperliquid-testnet.xyz/API or https://app.hyperliquid.xyz/API and authorize the API wallet on the correct environment.

### Dashboard shows old data

**Cause:** Streamlit's `@st.cache_data(ttl=60)` caches for 60 seconds. Or Streamlit Cloud put the app to sleep.

**Fix:**
1. Refresh the browser
2. If still stale, click the ⋮ menu → Reboot app

### Telegram alerts not delivered

**Possible causes:**
- Bot blocked by user
- Chat ID wrong
- Bot token revoked

**Fix:** Verify with:
```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getMe"
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"
```

### Email alerts not delivered

**Possible causes:**
- Gmail app password expired or revoked
- Recipient marked emails as spam
- SMTP blocked

**Fix:**
1. Check the workflow logs — look for `Email sent to [...]` line
2. If `Email send failed: ...`, regenerate Gmail app password at https://myaccount.google.com/apppasswords
3. Update secret: `gh secret set GMAIL_APP_PASSWORD -b "new password"`

### Bot opened a position but Hyperliquid shows nothing

**Cause:** Position got netted out by another bot opening opposite direction.

**Fix:** This is the shared-account limitation. Sub-accounts require $100k+ volume so aren't a realistic fix for most users. The code-level ownership tracking already handles safety — this is an efficiency issue, not a bug.

### Bot won't trade — keeps saying "0 trades, own 0 positions"

**Cause:** Either (a) no signal transitions, (b) signal says hold_long/hold_short but bot owns no positions and the sync-to-state logic isn't firing.

**Fix:** Check the executor code — the `decide_trades` function should treat `hold_long` / `hold_short` with no position as a sync-open. If not, pull latest code.

---

## 12. Going to Mainnet

### Pre-flight checklist

- [ ] **API wallet authorized on mainnet** (separate auth from testnet)
- [ ] **USDC bridged to Hyperliquid mainnet** in starting amount: $1,000-$2,000 total for all three bots combined
- [ ] **GitHub variables updated:**
  ```bash
  gh variable set HL_TESTNET -b "false"
  gh variable set SEGREGATED_CAPITAL -b "1000"
  gh variable set INTRADAY_CAPITAL -b "500"
  gh variable set AGGRESSIVE_CAPITAL -b "300"
  ```
- [ ] **Reset state Gists to fresh** (otherwise bots think they own testnet positions):
  ```bash
  gh gist edit d35732f9c123e95a4dc13a51855d21de -f trading_state.json - <<< '{}'
  gh gist edit 02cbe06fb1c4eb8afb5fad321aa3a251 -f intraday_state.json - <<< '{}'
  gh gist edit 0917280713a7781dc72a984147eef295 -f aggressive_state.json - <<< '{}'
  ```
- [ ] **Tighten drawdown thresholds for real money:**
  ```bash
  gh variable set DAILY_DD_PCT -b "3"        # 5% → 3%
  gh variable set INTRADAY_DD_PCT -b "3"     # 5% → 3%
  gh variable set AGGRESSIVE_DD_PCT -b "2"   # 3% → 2%
  ```
- [ ] **Run `test_trade.py` workflow on mainnet** to confirm fills work
- [ ] **Watch first 5-10 runs manually** before letting it run unattended

### Optional: Sub-account setup

Only relevant if you've cleared $100,000+ in mainnet trading volume on Hyperliquid (the platform requirement to unlock sub-accounts). Most users skip this section entirely.

If you qualify:

1. Visit https://app.hyperliquid.xyz/subAccounts
2. Create 3 sub-accounts:
   - `Crypto Yall Daily`
   - `Crypto Yall Intraday`
   - `Crypto Yall Aggressive`
3. For each, click into the sub-account, then go to https://app.hyperliquid.xyz/API
4. Generate an API wallet authorized for that sub-account
5. Send Brendan: sub-account address + API wallet private key for each

Brendan will do a one-time refactor to point each bot at its own sub-account key (adds `HL_DAILY_KEY`, `HL_INTRADAY_KEY`, `HL_AGGRESSIVE_KEY` env vars and updates the workflow YAMLs). Estimated time: 30-60 minutes of code work.

**Note:** This is a one-time change for the master repo. Community members who fork the repo do NOT need this — their forks work fine with a single Hyperliquid account each.

### Mainnet operational discipline

- **Week 1:** Watch every fill, verify execution, confirm notifications fire
- **Week 2-4:** Light-touch monitoring, daily glance at dashboard
- **Month 2+:** Scale up capital if PnL is positive and risk metrics are healthy
- **Always:** Kill switches at the ready, emergency procedures documented

---

## 13. Credentials & Access

### Repository

- **GitHub repo:** https://github.com/aicodepathways/crypto-yall (public)
- **Owner:** aicodepathways

### Hyperliquid

- **Account address (Josh's wallet):** `0x66aFE2E1242590F7edD7a4e20Ca3fBcbf770E765`
- **API wallet address (current single shared):** `0x3C7768FbE23b63Fa49f874245cbC136C89118De7`
- **API wallet private key:** stored in `HL_PRIVATE_KEY` secret
- **Testnet faucet:** https://app.hyperliquid-testnet.xyz/drip (requires $5+ mainnet deposit first)

### Telegram bot

- **Bot name:** `@Crypto_yall_bot`
- **Direct link:** https://t.me/Crypto_yall_bot
- **Bot token:** stored in `TELEGRAM_BOT_TOKEN` secret
- **Chat IDs:**
  - Brendan: `8438419459`
  - Josh: `5038092102`

### Email

- **Sender Gmail:** `nocodepathways@gmail.com`
- **App password:** stored in `GMAIL_APP_PASSWORD` secret
- **Recipients (current):** `nocodepathways@gmail.com,josh@cryptoyall.co`

### GitHub Gists (state storage)

| Gist ID | Filename | Purpose |
|---------|----------|---------|
| `ad73d92e1fa245c2725e06f60d68d13b` | `signal_state.json` | Last seen signals (for notifier) |
| `d35732f9c123e95a4dc13a51855d21de` | `trading_state.json` | Daily bot state |
| `02cbe06fb1c4eb8afb5fad321aa3a251` | `intraday_state.json` | Intraday Standard bot state |
| `0917280713a7781dc72a984147eef295` | `aggressive_state.json` | Aggressive bot state |

### GitHub PAT for Gist access

- **Token name:** "Crypto Yall Notifier"
- **Scope:** `gist` only
- **Stored in:** `GIST_TOKEN` secret (used by all 3 bots + dashboard)

### Streamlit Cloud

- **Dashboard URL:** https://crypto-yall-8s3evlspcczux5ztdmat9e.streamlit.app/
- **Admin URL:** https://share.streamlit.io
- **Secrets configured:** `GIST_TOKEN`, `TRADING_GIST_ID`, `INTRADAY_GIST_ID`, `AGGRESSIVE_GIST_ID`

### Full secrets list (`gh secret list`)

| Secret | Purpose |
|--------|---------|
| `HL_PRIVATE_KEY` | Hyperliquid API wallet private key |
| `HL_ACCOUNT_ADDRESS` | Hyperliquid main wallet address |
| `GIST_TOKEN` | GitHub PAT for Gist read/write |
| `GIST_ID` | Signal state Gist ID (notifier.py) |
| `TRADING_GIST_ID` | Daily bot state Gist ID |
| `INTRADAY_GIST_ID` | Intraday Standard bot state Gist ID |
| `AGGRESSIVE_GIST_ID` | Aggressive bot state Gist ID |
| `GMAIL_USER` | Sender Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail app password (16 chars) |
| `NOTIFY_EMAILS` | Comma-separated recipient list |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token |
| `TELEGRAM_CHAT_ID` | Comma-separated recipient chat IDs |

### Full variables list (`gh variable list`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `HL_TESTNET` | `true` | Use testnet (true) or mainnet (false) |
| `KILL_SWITCH` | `ON` | Daily bot enable / `OFF` to halt |
| `INTRADAY_KILL_SWITCH` | `ON` | Intraday Standard enable / `OFF` |
| `AGGRESSIVE_KILL_SWITCH` | `ON` | Aggressive enable / `OFF` |
| `SEGREGATED_CAPITAL` | `10000` | Daily bot capital pool |
| `INTRADAY_CAPITAL` | `5000` | Intraday Standard capital pool |
| `AGGRESSIVE_CAPITAL` | `3000` | Aggressive bot capital pool |
| `DAILY_DD_PCT` | `5` | Daily bot DD halt threshold |
| `INTRADAY_DD_PCT` | `5` | Intraday Standard DD halt |
| `AGGRESSIVE_DD_PCT` | `3` | Aggressive bot DD halt |
| `MAX_POSITIONS` | `4` | Daily bot max concurrent |
| `INTRADAY_MAX_POSITIONS` | `2` | Intraday Standard max concurrent |
| `AGGRESSIVE_MAX_POSITIONS` | `4` | Aggressive bot max concurrent |

---

## Quick Reference: Common Operations

### Inspect what each bot did today

```bash
for gist in d35732f9c123e95a4dc13a51855d21de 02cbe06fb1c4eb8afb5fad321aa3a251 0917280713a7781dc72a984147eef295; do
  echo "=== Gist $gist ==="
  gh gist view $gist --files | head -1 | xargs -I {} gh gist view $gist -f {} | jq '.last_run, .last_equity, .open_positions'
  echo ""
done
```

### Emergency halt all trading

```bash
gh variable set KILL_SWITCH -b "OFF" && \
gh variable set INTRADAY_KILL_SWITCH -b "OFF" && \
gh variable set AGGRESSIVE_KILL_SWITCH -b "OFF"
```

### Flip to mainnet (one-line)

```bash
gh variable set HL_TESTNET -b "false"
```

### View the most recent workflow runs

```bash
gh run list --limit 10
gh run view <RUN_ID> --log
```

---

## Contact

- **System builder:** Brendan Li (`nocodepathways@gmail.com`)
- **Client:** Josh Rhodes — Crypto Y'all (`josh@cryptoyall.co`)

---

*Last updated: handoff version, June 2026*
