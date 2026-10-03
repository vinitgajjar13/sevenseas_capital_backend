from dataclasses import dataclass

@dataclass
class StockContext:
    current: float
    change_pct: float
    volume: int
    pd_high: float | None
    pd_low: float | None
    high_915: float | None
    low_915: float | None
    close_915: float | None

class StrategyEngine:
    """Workbook-facing strategy layer.

    Keep this module deterministic. Each Excel formula should map to a named function here.
    Do not hide broker/network calls inside strategy calculations.
    """
    def evaluate(self, x: StockContext):
        bullish=[]; bearish=[]
        if x.pd_high is not None and x.current > x.pd_high: bullish.append("PD-3:25 HIGH BREAK")
        if x.pd_low is not None and x.current < x.pd_low: bearish.append("PD-3:25 LOW BREAK")
        if x.high_915 is not None and x.current > x.high_915: bullish.append("9:15 HIGH BREAK")
        if x.low_915 is not None and x.current < x.low_915: bearish.append("9:15 LOW BREAK")
        if x.change_pct >= 0.40: bullish.append("POSITIVE MOMENTUM")
        elif x.change_pct <= -0.40: bearish.append("NEGATIVE MOMENTUM")
        if bullish and not bearish: state="BULLISH"
        elif bearish and not bullish: state="BEARISH"
        else: state="NEUTRAL"
        score=max(0,min(100,50 + x.change_pct*10 + 10*len(bullish) - 10*len(bearish)))
        return {"state":state,"special_bullish":" | ".join(bullish) or None,"special_bearish":" | ".join(bearish) or None,"score":round(score,2)}
