from app.strategies.engine import StrategyEngine, StockContext

def test_bullish_breakout():
    x=StockContext(105,1.2,100000,100,90,102,95,100)
    r=StrategyEngine().evaluate(x)
    assert r['state']=='BULLISH'
    assert 'PD-3:25 HIGH BREAK' in r['special_bullish']

def test_bearish_breakdown():
    x=StockContext(85,-1.2,100000,100,90,102,95,100)
    r=StrategyEngine().evaluate(x)
    assert r['state']=='BEARISH'
