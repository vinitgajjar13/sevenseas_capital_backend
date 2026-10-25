from typing import Any, Dict, List, Optional


def calculate_sector_snapshot(rows: List[Dict[str, Any]], sector_name: str = "") -> Dict[str, Any]:
    """Calculate deterministic sector breadth, volume metrics, and strategy score

    implementing the exact formulas from 'Sector Dashboard' of F&O LIVE STOCK SHEET.xlsx.
    """
    n = len(rows)
    if not n:
        return {
            "sector": sector_name,
            "total_stocks": 0,
            "total": 0,
            "advances": 0,
            "declines": 0,
            "unchanged": 0,
            "positive_stocks": 0,
            "negative_stocks": 0,
            "avg_change": 0.0,
            "average_change_percent": 0.0,
            "bullish_pct": 0.0,
            "bearish_pct": 0.0,
            "live_volume": 0,
            "volume_per_stock": 0.0,
            "bullish_volume": 0,
            "bearish_volume": 0,
            "bullish_volume_pct": 0.0,
            "bearish_volume_pct": 0.0,
            "direction": "⚪ NEUTRAL",
            "score": 0.0,
            "bullish_rank": None,
            "bearish_rank": None,
            "top_bullish_stocks": [],
            "top_bearish_stocks": [],
        }

    # Extract change percentages
    pos = sum(1 for r in rows if r.get("change_pct") is not None and float(r["change_pct"]) > 0)
    neg = sum(1 for r in rows if r.get("change_pct") is not None and float(r["change_pct"]) < 0)
    unchanged = sum(1 for r in rows if r.get("change_pct") is not None and float(r["change_pct"]) == 0)

    valid_changes = [float(r["change_pct"]) for r in rows if r.get("change_pct") is not None]
    avg = round(sum(valid_changes) / len(valid_changes), 4) if valid_changes else 0.0

    # Sector Dashboard Col F & G:
    # Bullish % = pos / total * 100
    # Bearish % = neg / total * 100
    bullish_pct = round(pos / n * 100.0, 2)
    bearish_pct = round(neg / n * 100.0, 2)

    # Sector Dashboard Col H, J, K, L, M:
    # Bullish Volume: sum of volume where change_pct > 0
    # Bearish Volume: sum of volume where change_pct < 0
    total_vol = sum(int(r.get("volume") or 0) for r in rows)
    vol_per_stock = round(total_vol / n, 2)
    bull_vol = sum(int(r.get("volume") or 0) for r in rows if r.get("change_pct") is not None and float(r["change_pct"]) > 0)
    bear_vol = sum(int(r.get("volume") or 0) for r in rows if r.get("change_pct") is not None and float(r["change_pct"]) < 0)

    bullish_v = round(bull_vol / total_vol * 100.0, 2) if total_vol > 0 else 0.0
    bearish_v = round(bear_vol / total_vol * 100.0, 2) if total_vol > 0 else 0.0

    # Sector Dashboard Col O (Sector Score):
    # =ROUND((C2*20) + ((F2-G2)*0.4) + ((L2-M2)*0.4), 2)
    # Inputs: C2 (avg_change), F2 (bullish_pct 0-100), G2 (bearish_pct 0-100), L2 (bull_vol_pct 0-100), M2 (bear_vol_pct 0-100)
    score = round(
        (avg * 20.0) + ((bullish_pct - bearish_pct) * 0.4) + ((bullish_v - bearish_v) * 0.4),
        2,
    )

    # Sector Dashboard Col N (Sector Direction):
    # =IF(AND(C2>0, F2>=60, L2>=60), "🟢 BULLISH", IF(AND(C2<0, G2>=60, M2>=60), "🔴 BEARISH", "⚪ NEUTRAL"))
    if avg > 0 and bullish_pct >= 60.0 and bullish_v >= 60.0:
        direction = "🟢 BULLISH"
    elif avg < 0 and bearish_pct >= 60.0 and bearish_v >= 60.0:
        direction = "🔴 BEARISH"
    else:
        direction = "⚪ NEUTRAL"

    # Stock Contribution Scores (Sector Dashboard Col AG & AZ) and UP1/UP2, DOWN1/DOWN2 Selection:
    # Bullish: (change_pct / max_pos_change * 70) + (volume / max_pos_volume * 30)
    # Bearish: (abs(change_pct) / max_neg_change * 70) + (volume / max_neg_volume * 30)
    pos_stocks = [r for r in rows if r.get("change_pct") is not None and float(r["change_pct"]) > 0]
    top_bullish = []
    if pos_stocks:
        max_pos_chg = max((float(r["change_pct"]) for r in pos_stocks), default=0.0)
        max_pos_vol = max((int(r.get("volume") or 0) for r in pos_stocks), default=0)
        scored_pos = []
        for r in pos_stocks:
            chg_val = float(r["change_pct"])
            vol_val = int(r.get("volume") or 0)
            chg_part = (chg_val / max_pos_chg * 70.0) if max_pos_chg > 0 else 0.0
            vol_part = (vol_val / max_pos_vol * 30.0) if max_pos_vol > 0 else 0.0
            contrib = round(chg_part + vol_part, 2)
            scored_pos.append({
                "symbol": r.get("symbol"),
                "price": r.get("current_price") or r.get("ltp"),
                "change_pct": chg_val,
                "volume": vol_val,
                "contribution_score": contrib,
            })
        scored_pos.sort(key=lambda s: s["contribution_score"], reverse=True)
        top_bullish = scored_pos[:2]

    neg_stocks = [r for r in rows if r.get("change_pct") is not None and float(r["change_pct"]) < 0]
    top_bearish = []
    if neg_stocks:
        max_neg_chg = max((abs(float(r["change_pct"])) for r in neg_stocks), default=0.0)
        max_neg_vol = max((int(r.get("volume") or 0) for r in neg_stocks), default=0)
        scored_neg = []
        for r in neg_stocks:
            chg_val = float(r["change_pct"])
            vol_val = int(r.get("volume") or 0)
            chg_part = (abs(chg_val) / max_neg_chg * 70.0) if max_neg_chg > 0 else 0.0
            vol_part = (vol_val / max_neg_vol * 30.0) if max_neg_vol > 0 else 0.0
            contrib = round(chg_part + vol_part, 2)
            scored_neg.append({
                "symbol": r.get("symbol"),
                "price": r.get("current_price") or r.get("ltp"),
                "change_pct": chg_val,
                "volume": vol_val,
                "contribution_score": contrib,
            })
        scored_neg.sort(key=lambda s: s["contribution_score"], reverse=True)
        top_bearish = scored_neg[:2]

    return {
        "sector": sector_name,
        "total_stocks": n,
        "total": n,
        "advances": pos,
        "declines": neg,
        "unchanged": unchanged,
        "positive_stocks": pos,
        "negative_stocks": neg,
        "avg_change": avg,
        "average_change_percent": avg,
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "live_volume": total_vol,
        "volume_per_stock": vol_per_stock,
        "bullish_volume": bull_vol,
        "bearish_volume": bear_vol,
        "bullish_volume_pct": bullish_v,
        "bearish_volume_pct": bearish_v,
        "direction": direction,
        "score": score,
        "bullish_rank": None,
        "bearish_rank": None,
        "top_bullish_stocks": top_bullish,
        "top_bearish_stocks": top_bearish,
    }


def assign_sector_ranks(sector_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign Bullish Rank and Bearish Rank following Excel Sector Dashboard logic:

    - Bullish Rank (Col P): Rank of Sector Score among sectors with score > 0 (highest score = 1).
    - Bearish Rank (Col Q): Rank of abs(Sector Score) among sectors with score < 0 (most negative = 1).
    """
    for s in sector_list:
        s["bullish_rank"] = None
        s["bearish_rank"] = None

    # 1. Bullish Ranks (score > 0, sorted descending)
    bullish_sectors = [s for s in sector_list if s.get("score", 0.0) > 0]
    bullish_sectors.sort(key=lambda s: s.get("score", 0.0), reverse=True)
    for rank_idx, s in enumerate(bullish_sectors, start=1):
        s["bullish_rank"] = rank_idx

    # 2. Bearish Ranks (score < 0, sorted by abs(score) descending / score ascending)
    bearish_sectors = [s for s in sector_list if s.get("score", 0.0) < 0]
    bearish_sectors.sort(key=lambda s: abs(s.get("score", 0.0)), reverse=True)
    for rank_idx, s in enumerate(bearish_sectors, start=1):
        s["bearish_rank"] = rank_idx

    # Default sort for UI: positive scores descending first, then negative scores
    sector_list.sort(
        key=lambda s: (s.get("score") is not None, s.get("score", 0.0)),
        reverse=True,
    )
    return sector_list


# Backward compatibility alias
sector_snapshot = calculate_sector_snapshot

