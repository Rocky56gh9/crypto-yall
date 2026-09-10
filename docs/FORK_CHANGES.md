# Fork changes: operational hardening

This fork adds five behaviors on top of the upstream bots. Defaults are
unchanged: with the same secrets and variables, the bots trade exactly as
before, plus the protections below.

## 1. Exchange-side stop-loss orders

Every entry (and every pyramid add) now places a reduce-only stop-market
trigger order on Hyperliquid at the strategy's ATR stop:

| Bot | Stop distance |
|-----|---------------|
| Daily | fill ± asset profile `atr_mult` × ATR(14) (3.0 large cap, 4.0 mid cap) |
| Intraday | fill ± 2.0 × ATR(14) on 1h bars |
| Aggressive | fill ± 1.5 × ATR(14) on 30m bars |

The bot's own stop logic still runs on every scheduled pass. The exchange
order is a backstop for the time between runs. Stops are cancelled when
the bot closes the position, and replaced after a pyramid add so they
always cover the full size.

If the exchange stop fires between runs, the bot notices the position is
gone, puts that coin in **cooldown**, and will not re-enter on a
"sync to hold" signal. It re-enters only on a fresh `buy` / `enter_short`.

## 2. Close-only mode instead of freeze

Previously a drawdown halt or a kill switch set to `OFF` exited before
any trade decisions, leaving open positions unmanaged. Now:

| Setting | Behavior |
|---------|----------|
| Kill switch `ON` | Normal trading |
| Kill switch `OFF` | Exits still managed, no new entries or pyramid adds |
| Kill switch `HALT` | Do nothing at all (old `OFF` behavior) |
| Drawdown halt hit | Close-only for the rest of the UTC day |

Applies to `KILL_SWITCH`, `INTRADAY_KILL_SWITCH`, `AGGRESSIVE_KILL_SWITCH`.

## 3. Optional sub-account per bot

All three bots trade the same coins, and Hyperliquid nets positions per
coin per account. One bot's `market_close` closes the whole net position,
including another bot's trade. To isolate them, give each bot its own
Hyperliquid sub-account and set the matching secret:

| Secret | Used by |
|--------|---------|
| `DAILY_ACCOUNT_ADDRESS` | Execute Trades |
| `INTRADAY_ACCOUNT_ADDRESS` | Execute Intraday |
| `AGGRESSIVE_ACCOUNT_ADDRESS` | Execute Aggressive |

Any secret left unset falls back to `HL_ACCOUNT_ADDRESS`. The same API
wallet key is used for all of them. Fund each sub-account on the Perps
side, in Manual account mode, and run the bot once by hand to confirm.

## 4. Stable intraday candle window

The 1h and 30m candle fetch used to start exactly `lookback_hours` before
"now", so the first bar drifted on every run. The strategies replay a
simulated position from the first bar, which meant two runs on the same
market could disagree about the current position. The window start is
now snapped to a weekly boundary (Thursday 00:00 UTC).

## 5. Failure alerts

If a run crashes for any reason (data provider outage, API error,
unexpected exception), the bot sends an email and Telegram message with
the error before exiting non-zero. Previously you only got GitHub's
generic "workflow failed" email.

## Sizing reminder

Hyperliquid rejects orders under $10 notional. Order notional is
`capital × size% × leverage`. With small capital variables, some orders
never place:

| Bot | Order | Notional at capital = 300 / 500 / 1000 |
|-----|-------|-----------------------------------------|
| Aggressive | pyramid add (0.5% × ~4x) | $6 / $10 / $20 |
| Aggressive | mid-cap entry (1.5% × 2x) | $9 / $15 / $30 |
| Intraday | any entry (1% × 2x) | $6 / $10 / $20 |
| Daily | entry at 1x (1% × 1x) | $3 / $5 / $10 |

Set each capital variable to at least 1000 so every order clears the
minimum with margin for size rounding.
