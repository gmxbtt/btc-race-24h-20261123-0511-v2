# Tidewalker — a two-stage trend rider for the cbBTC 24h race

Entry for [btc-race-24h-20261123-0511](https://make.fun/bounty/btc-race-24h-20261123-0511)
on make.fun: a bot that trades Coinbase Wrapped BTC (cbBTC) against USDC,
minute by minute, on 1-minute on-chain bars, starting with $1,000 of paper
money.

## The idea

Bitcoin's 1-minute moves are mostly noise — about 8 bps of standard
deviation per minute — while one full round trip costs about 26 bps in
fees (4 bps), slippage (2 bps) and pool impact. Trading often is a
guaranteed loss. The only edge available is the slow drift, so Tidewalker
rides genuine multi-hour uptrends and sits in cash otherwise:

- **First tranche (50% of cash):** the 30-minute log return tops +0.2%
  while price sits above its 60-minute EMA and that EMA is rising.
- **Second tranche (the rest):** only once the 120-minute return turns
  positive, confirming the trend is real and not a bounce.
- **Exit everything** on the first real sign of reversal: the 60-minute
  return drops below −2%, price falls 2.5% from its peak (trailing stop),
  or 3% below the entry (hard stop).

It trades at most a few times a day, so fees stay tiny. In a falling
market it stays mostly in cash instead of bleeding on dead-cat bounces.

## Results on the published dev window

Backtested with a simulator that replays the harness's exact fill model
(next-bar open fills, 4 bps fee, 2 bps slippage, constant-product impact
against the bar's open depth, flatten at the last close):

| | net PnL | trades | max drawdown |
|---|---:|---:|---:|
| Tidewalker | **+$31.79** | 3 | ~2% |
| Buy-and-hold (same simulator) | +$30.86 | 2 | ~2% |
| Buy-and-hold (harness grade-local) | +$32.17 | 1 | 1.98% |

Robustness checks (same parameters, no re-tuning): on the dev window run
backwards — a −3.6% downtrend mirror — it loses only −$19.34, against
−$35 for buy-and-hold; on ten shuffled-return copies of the window (same
total drift, trend destroyed) it averages +$25.14 and never loses money.

End-to-end verification: the bot itself, run through the real protocol
shim against the dev bars with the harness's fill model, scores **+$31.79**
(3 trades, max drawdown 1.98%, exit code 0) — identical to the simulator
to the cent. (The kit's `grade-local --driver process` cannot run Python
bots — it needs Docker, which this machine has not — so the protocol-level
replay above is the local verification.)

## Files

- `main.py` — the bot (Python 3.13, standard library only). Speaks
  `agent-fun/bars-replay/v1` through the vendored shim.
- `vendor/makefun_bars.py` — byte-for-byte copy of the kit's Python SDK
  shim (excluded from authorship counts by the competition rules).
- `LICENSE` — MIT.

## Running it

The harness runs `python3 -P -s /bot/main.py` with `PYTHONHASHSEED=0`.
The bot is a pure function of the closes it has been sent: no clock, no
network, no randomness, no files. The same bars always produce the same
orders.
