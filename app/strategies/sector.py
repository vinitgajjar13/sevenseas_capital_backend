def sector_snapshot(rows):
    n=len(rows)
    if not n: return {"total_stocks":0,"direction":"NEUTRAL","score":0}
    changes=[float(r.get("change_pct") or 0) for r in rows]
    pos=sum(c>0 for c in changes); neg=sum(c<0 for c in changes)
    bull_vol=sum(int(r.get("volume") or 0) for r in rows if (r.get("state")=="BULLISH"))
    bear_vol=sum(int(r.get("volume") or 0) for r in rows if (r.get("state")=="BEARISH"))
    total=sum(int(r.get("volume") or 0) for r in rows)
    avg=sum(changes)/n
    bullish_pct=pos/n*100; bearish_pct=neg/n*100
    bullish_v=bull_vol/total*100 if total else 0; bearish_v=bear_vol/total*100 if total else 0
    score=round((avg*10)+(bullish_pct-bearish_pct)*0.5+(bullish_v-bearish_v)*0.25,2)
    direction="BULLISH" if score>10 else "BEARISH" if score < -10 else "NEUTRAL"
    return {"total_stocks":n,"avg_change":round(avg,4),"positive_stocks":pos,"negative_stocks":neg,"bullish_pct":round(bullish_pct,2),"bearish_pct":round(bearish_pct,2),"live_volume":total,"volume_per_stock":total/n,"bullish_volume":bull_vol,"bearish_volume":bear_vol,"bullish_volume_pct":round(bullish_v,2),"bearish_volume_pct":round(bearish_v,2),"direction":direction,"score":score}
