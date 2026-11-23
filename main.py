"""Tidewalker: a two-stage trend rider for the cbBTC 24h race.

Idea, in one paragraph: Bitcoin's 1-minute moves are mostly noise (about
8 bps of standard deviation per minute) while a full round trip costs about
26 bps in fees, slippage and pool impact, so trading often is a guaranteed
loss. The only edge available is the slow drift: ride a genuine multi-hour
uptrend, sit in cash otherwise. The bot therefore enters in two stages --
half the cash on a short-horizon momentum trigger (30-minute return above
+0.2% with price above its 60-minute EMA and that EMA rising), the other
half only once the 120-minute return confirms the trend is real -- and it
exits everything on the first sign of a real reversal (60-minute return
below -2%, a 2.5% trailing stop from the peak, or a 3% stop below the
entry). It trades at most a few times per day, so fees stay tiny, and in a
falling market it stays mostly in cash instead of bleeding on bounces.

Everything here is a deterministic function of the closes the harness has
sent: no clock, no network, no randomness, no files. The same bars always
produce the same orders.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- strategy constants (tuned on the published dev window; see README) ---
ENTRY_R30 = 0.002        # 30-minute log return that arms the first tranche
CONFIRM_R120 = 0.0       # 120-minute log return that confirms the trend
EXIT_R60 = -0.02         # 60-minute log return that exits the position
TRAIL = 0.025            # trailing stop, fraction below the peak close
STOP = 0.03              # hard stop, fraction below the entry close
FIRST_FRACTION = 0.5     # share of cash in the first tranche
EMA_SPAN = 60            # slow EMA span, in bars
EMA_SLOPE_BARS = 30      # bars over which the slow EMA must be rising
MAX_SLIPPAGE_BPS = 200   # 2%: far above the ~13 bps a full-size fill moves
MIN_NOTIONAL = 1_000_000  # 1 USDC, in quote units


class Tidewalker:
    """Keeps the close history and the entry/peak bookkeeping."""

    def __init__(self):
        self.closes = []        # raw close prices (price_scale 5), one per bar
        self.ema = []           # slow EMA of the closes, same indexing
        self.last_bar_t = None  # t of the last CBBTC bar folded in
        self.entry_close = 0    # close of the bar the position was opened on
        self.peak_close = 0     # highest close seen while holding

    def _ema_alpha(self):
        return 2.0 / (EMA_SPAN + 1)

    def observe(self, state):
        """Fold this batch's CBBTC bar into the history, if it is a new one."""
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return
        t = bar["t"]
        if t == self.last_bar_t:
            return
        self.last_bar_t = t
        close = int(bar["c"])
        self.closes.append(close)
        if not self.ema:
            self.ema.append(float(close))
        else:
            alpha = self._ema_alpha()
            self.ema.append(self.ema[-1] + alpha * (close - self.ema[-1]))

    def _ret(self, bars_back):
        """Log return of the latest close over `bars_back` bars, or None."""
        if len(self.closes) <= bars_back:
            return None
        return math.log(self.closes[-1] / self.closes[-1 - bars_back])

    def _position_qty(self, state):
        holding = state.positions.get(SYMBOL)
        return 0 if holding is None else holding.qty

    def _stage(self, state):
        """0 = flat, 1 = half in, 2 = (nearly) full in, from the real position.

        Derived from the position's value, not from what was intended, so a
        rejected order can never leave the bookkeeping ahead of the market.
        """
        qty = self._position_qty(state)
        if qty <= 0:
            return 0
        value = state.value(SYMBOL, qty)
        if state.equity <= 0:
            return 2
        return 1 if value * 10 < state.equity * 6 else 2

    def decide(self, state):
        if state.warming_up:
            return []
        close = state.close(SYMBOL)
        if close is None or len(self.closes) < 30:
            return []
        stage = self._stage(state)
        r30 = self._ret(30)
        r60 = self._ret(60)
        r120 = self._ret(120)
        ema_now = self.ema[-1]
        ema_slope = (
            ema_now - self.ema[-1 - EMA_SLOPE_BARS]
            if len(self.ema) > EMA_SLOPE_BARS
            else 0.0
        )
        orders = []
        if stage == 0:
            if r30 is not None and r30 > ENTRY_R30 and close > ema_now and ema_slope > 0:
                amount = state.cash * FIRST_FRACTION // 1
                if amount >= MIN_NOTIONAL:
                    orders.append(
                        {
                            "side": "buy",
                            "symbol": SYMBOL,
                            "notional_quote_units": int(amount),
                            "max_slippage_bps": MAX_SLIPPAGE_BPS,
                        }
                    )
                    self.entry_close = close
                    self.peak_close = close
        elif stage == 1:
            if close > self.peak_close:
                self.peak_close = close
            if (
                (r60 is not None and r60 < EXIT_R60)
                or close < self.peak_close * (1 - TRAIL)
                or close < self.entry_close * (1 - STOP)
            ):
                orders.append(
                    {
                        "side": "sell",
                        "symbol": SYMBOL,
                        "qty": self._position_qty(state),
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                )
                self.entry_close = 0
                self.peak_close = 0
            elif (
                r120 is not None
                and r120 > CONFIRM_R120
                and close > ema_now
                and state.cash >= MIN_NOTIONAL
            ):
                orders.append(
                    {
                        "side": "buy",
                        "symbol": SYMBOL,
                        "notional_quote_units": int(state.cash),
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                )
        else:  # stage == 2
            if close > self.peak_close:
                self.peak_close = close
            if (
                (r60 is not None and r60 < EXIT_R60)
                or close < self.peak_close * (1 - TRAIL)
                or close < self.entry_close * (1 - STOP)
            ):
                orders.append(
                    {
                        "side": "sell",
                        "symbol": SYMBOL,
                        "qty": self._position_qty(state),
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                )
                self.entry_close = 0
                self.peak_close = 0
        return orders


BOT = Tidewalker()


def on_batch(state, batch):
    BOT.observe(state)
    return BOT.decide(state)


makefun_bars.run(on_batch)
