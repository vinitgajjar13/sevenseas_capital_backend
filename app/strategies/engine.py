from dataclasses import dataclass
from typing import Optional


@dataclass
class StockContext:
    current: Optional[float] = None
    change_pct: Optional[float] = None
    volume: Optional[int] = 0
    pd_high: Optional[float] = None       # PD-3:25-HIGH
    pd_low: Optional[float] = None        # PD-3:25-LOW
    open_915: Optional[float] = None      # 9:15- OPEN
    high_915: Optional[float] = None      # 9:15- HIGH
    low_915: Optional[float] = None       # 9:15-LOW
    close_915: Optional[float] = None     # 9:15-CLOSE
    symbol: Optional[str] = ""
    prev_close: Optional[float] = None    # Previous session close for comparison


class StrategyEngine:
    """Workbook-facing strategy layer implementing exact formulas from

    'F&O LIVE STOCK SHEET.xlsx' (Sheet1, INTRADAY RADAR, and LIVE MARKET TEACHER).
    Deterministic, auditable, and isolated from external network calls.
    """

    def evaluate(self, x: StockContext) -> dict:
        current_price = x.current
        vol = x.volume or 0

        # Percentage change relative to 9:15 AM Open:
        # Excel Sheet1 Col L: =(K2 - G2)/G2 * 100 = (CURRENT - 9:15-OPEN) / 9:15-OPEN * 100
        change_pct_915 = None
        if current_price is not None and x.open_915 is not None and x.open_915 > 0:
            change_pct_915 = round((current_price - x.open_915) / x.open_915 * 100.0, 4)

        # Fallback to provided change_pct if 9:15 open is unavailable
        effective_pct = change_pct_915 if change_pct_915 is not None else x.change_pct

        # Check availability of reference levels
        has_ref = (
            x.pd_high is not None
            and x.pd_low is not None
            and x.open_915 is not None
            and x.close_915 is not None
        )

        # 1. Exact Bullish WATCH (Sheet1 Col O):
        # =IF(AND(G2<F2, J2>=E2*(1-0.001)), "🟢 WATCH", "")
        # G2: 9:15-OPEN, F2: PD-3:25-LOW, J2: 9:15-CLOSE, E2: PD-3:25-HIGH
        bullish_watch = False
        if has_ref:
            bullish_watch = bool(
                x.open_915 < x.pd_low
                and x.close_915 >= round(x.pd_high * (1.0 - 0.001), 6)
            )

        # 2. Exact Bearish WATCH (Sheet1 Col P):
        # =IF(AND(G2>E2, J2<=F2*(1+0.001)), "🔴 WATCH", "")
        # G2: 9:15-OPEN, E2: PD-3:25-HIGH, J2: 9:15-CLOSE, F2: PD-3:25-LOW
        bearish_watch = False
        if has_ref:
            bearish_watch = bool(
                x.open_915 > x.pd_high
                and x.close_915 <= round(x.pd_low * (1.0 + 0.001), 6)
            )

        watch_status = None
        if bullish_watch:
            watch_status = "🟢 WATCH"
        elif bearish_watch:
            watch_status = "🔴 WATCH"

        # 3. Exact Intraday SPIKE / DUMP (INTRADAY RADAR Col J):
        # SPIKE: CURRENT > HIGH_915 AND CURRENT > PD_HIGH AND PERCENT_CHANGE > 0
        # DUMP:  CURRENT < LOW_915 AND CURRENT < PD_LOW AND PERCENT_CHANGE < 0
        signal = None
        has_spike_dump_inputs = (
            current_price is not None
            and effective_pct is not None
            and x.high_915 is not None
            and x.low_915 is not None
            and x.pd_high is not None
            and x.pd_low is not None
        )

        if has_spike_dump_inputs:
            if current_price > x.high_915 and current_price > x.pd_high and effective_pct > 0:
                signal = "🔥 SPIKE"
            elif current_price < x.low_915 and current_price < x.pd_low and effective_pct < 0:
                signal = "🚨 DUMP"
            else:
                signal = "-"

        # 4. Live Market Teacher Action (LIVE MARKET TEACHER Col N):
        # IF vol < 100000 -> "🟠 LOW VOLUME / AVOID"
        # IF BULL SIDE AND %chg > 0 AND price > 9:15-CLOSE -> "🟢 BULL ALIGNED"
        # IF BEAR SIDE AND %chg < 0 AND price < 9:15-CLOSE -> "🔴 BEAR ALIGNED"
        # IF BULL SIDE -> "⚠️ BULL SIDE CONFLICT"
        # IF BEAR SIDE -> "⚠️ BEAR SIDE CONFLICT"
        # ELSE -> "⚪ WATCH / WAIT"
        action = None
        if current_price is not None:
            if vol < 100000:
                action = "🟠 LOW VOLUME / AVOID"
            else:
                is_bull_side = bullish_watch or signal == "🔥 SPIKE" or (effective_pct is not None and effective_pct > 0)
                is_bear_side = bearish_watch or signal == "🚨 DUMP" or (effective_pct is not None and effective_pct < 0)

                close_ref = x.close_915

                if is_bull_side:
                    if (
                        effective_pct is not None
                        and effective_pct > 0
                        and close_ref is not None
                        and current_price > close_ref
                    ):
                        action = "🟢 BULL ALIGNED"
                    else:
                        action = "⚠️ BULL SIDE CONFLICT"
                elif is_bear_side:
                    if (
                        effective_pct is not None
                        and effective_pct < 0
                        and close_ref is not None
                        and current_price < close_ref
                    ):
                        action = "🔴 BEAR ALIGNED"
                    else:
                        action = "⚠️ BEAR SIDE CONFLICT"
                else:
                    action = "⚪ WATCH / WAIT"

        # Direction State
        if bullish_watch or signal == "🔥 SPIKE":
            state = "BULLISH"
        elif bearish_watch or signal == "🚨 DUMP":
            state = "BEARISH"
        elif effective_pct is not None and effective_pct > 0:
            state = "BULLISH"
        elif effective_pct is not None and effective_pct < 0:
            state = "BEARISH"
        else:
            state = "NEUTRAL"

        # Special setup labels
        special_bullish = []
        if bullish_watch:
            special_bullish.append("BULLISH WATCH")
        if signal == "🔥 SPIKE":
            special_bullish.append("INTRADAY SPIKE")

        special_bearish = []
        if bearish_watch:
            special_bearish.append("BEARISH WATCH")
        if signal == "🚨 DUMP":
            special_bearish.append("INTRADAY DUMP")

        score = None
        if effective_pct is not None:
            score = round(
                max(0.0, min(100.0, 50.0 + (effective_pct * 10.0) + (10.0 * len(special_bullish)) - (10.0 * len(special_bearish)))),
                2,
            )

        return {
            "symbol": x.symbol or "",
            "state": state,
            "current_price": current_price,
            "change_pct_915": change_pct_915,
            "effective_change_pct": effective_pct,
            "volume": vol,
            "bullish_watch": bullish_watch,
            "bearish_watch": bearish_watch,
            "watch_status": watch_status,
            "signal": signal,
            "action": action,
            "special_bullish": " | ".join(special_bullish) or None,
            "special_bearish": " | ".join(special_bearish) or None,
            "score": score,
            "has_reference_data": bool(has_ref),
        }

