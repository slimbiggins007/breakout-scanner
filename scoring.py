"""
Scoring engine.
Takes pattern detection results and produces a score 0-100 with category breakdown.
"""

import pandas as pd

import config
from indicators import ema_stacked, emas_rising, relative_strength_vs_spy


def score_pattern_quality(pattern: dict) -> dict[str, float]:
    """
    Score the pattern quality component (max 40 points).
    Returns individual sub-scores.
    """
    scores = {}
    criteria = pattern["criteria"]
    details = pattern["details"]
    setup = pattern["setup_type"]
    cfg = config.SCORING

    # ── Tightness (0-10) ────────────────────────────────────────────────────
    if setup == 1:
        # Daily tight base: use tightness_score (0-1, higher = tighter)
        tightness = details.get("tightness_score", 0)
        scores["tightness"] = min(tightness * cfg["tightness_max"], cfg["tightness_max"])
    elif setup == 3:
        # Trendline compression: use gap convergence
        gap_pct = details.get("gap_pct", 10)
        scores["tightness"] = max(0, cfg["tightness_max"] * (1 - gap_pct / 10))
    else:
        # For other setups, give partial credit if criteria pass
        scores["tightness"] = cfg["tightness_max"] * 0.6 if pattern["detected"] else 0

    # ── Consolidation days (0-10) ───────────────────────────────────────────
    if setup == 1:
        days = details.get("consol_days", 0)
        if days >= 5:
            scores["consol_days"] = cfg["consol_days_max"]
        elif days >= 3:
            scores["consol_days"] = cfg["consol_days_max"] * 0.5
        else:
            scores["consol_days"] = 0
    else:
        scores["consol_days"] = cfg["consol_days_max"] * 0.6 if pattern["detected"] else 0

    # ── Pattern cleanliness (0-10) ──────────────────────────────────────────
    # Based on how many criteria pass
    total_criteria = len(criteria)
    passing = sum(1 for v in criteria.values() if v)
    if total_criteria > 0:
        ratio = passing / total_criteria
        scores["pattern_clean"] = ratio * cfg["pattern_clean_max"]
    else:
        scores["pattern_clean"] = 0

    # ── Resistance / trendline clarity (0-10) ───────────────────────────────
    if setup == 2:
        # Weekly base: clarity from proximity to resistance
        dist = details.get("distance_pct", 10)
        scores["resistance_clarity"] = max(0, cfg["resistance_clarity_max"] * (1 - dist / 10))
    elif setup == 3:
        # Trendline: clarity from number of swing highs
        n = details.get("num_swing_highs", 0)
        scores["resistance_clarity"] = min(n / 5, 1.0) * cfg["resistance_clarity_max"]
    elif setup == 4:
        # Undercut: support clarity
        scores["resistance_clarity"] = cfg["resistance_clarity_max"] * 0.7 if criteria.get("support_found") else 0
    else:
        scores["resistance_clarity"] = cfg["resistance_clarity_max"] * 0.5 if pattern["detected"] else 0

    return scores


def score_trend_alignment(df: pd.DataFrame, pattern: dict) -> dict[str, float]:
    """
    Score the trend alignment component (max 30 points).
    """
    cfg = config.SCORING
    scores = {}

    # ── EMA stack order (0-10) ──────────────────────────────────────────────
    stacked = ema_stacked(df)
    scores["ema_stack"] = cfg["ema_stack_max"] if stacked else 0

    # ── All EMAs rising (0-10) ──────────────────────────────────────────────
    rising = emas_rising(df)
    rising_count = sum(1 for v in rising.values() if v)
    scores["ema_rising"] = (rising_count / 3) * cfg["ema_rising_max"]

    # ── Price position relative to EMAs (0-10) ─────────────────────────────
    if len(df) > 0:
        last = df.iloc[-1]
        above_fast = last["Close"] > last.get(f"EMA_{config.EMA_FAST}", 0)
        above_mid = last["Close"] > last.get(f"EMA_{config.EMA_MID}", 0)
        above_slow = last["Close"] > last.get(f"EMA_{config.EMA_SLOW}", 0)
        count = sum([above_fast, above_mid, above_slow])
        scores["price_vs_ema"] = (count / 3) * cfg["price_vs_ema_max"]
    else:
        scores["price_vs_ema"] = 0

    return scores


def score_momentum(df: pd.DataFrame, pattern: dict) -> dict[str, float]:
    """
    Score momentum signals (max 20 points).
    """
    cfg = config.SCORING
    criteria = pattern["criteria"]
    scores = {}

    # ── MACD histogram position and curl (0-10) ────────────────────────────
    macd_points = 0
    if criteria.get("macd_curl", False):
        macd_points += 5
    if criteria.get("macd_flat", False):
        macd_points += 3
    # Bonus if MACD line is above signal
    if len(df) > 0 and "MACD" in df.columns:
        if df["MACD"].iloc[-1] > df["MACD_Signal"].iloc[-1]:
            macd_points += 2
    scores["macd"] = min(macd_points, cfg["macd_max"])

    # ── Volume pattern (0-10) ───────────────────────────────────────────────
    vol_points = 0
    if criteria.get("vol_declining", False):
        vol_points += 5
    if criteria.get("breakout", False):
        vol_points += 5
    elif criteria.get("recovery_volume", False):
        vol_points += 5
    scores["volume"] = min(vol_points, cfg["volume_max"])

    return scores


def score_sector_bonus(sector: str, df: pd.DataFrame, spy_df: pd.DataFrame | None) -> dict[str, float]:
    """
    Score sector bonus (max 10 points).
    """
    cfg = config.SCORING
    scores = {}

    # ── Leading sector (0-5) ────────────────────────────────────────────────
    scores["leading_sector"] = cfg["leading_sector_max"] if sector in config.LEADING_SECTORS else 0

    # ── Relative strength vs SPY (0-5) ──────────────────────────────────────
    if spy_df is not None:
        rs = relative_strength_vs_spy(df, spy_df)
        if rs > 1.5:
            scores["relative_strength"] = cfg["relative_strength_max"]
        elif rs > 1.0:
            scores["relative_strength"] = cfg["relative_strength_max"] * 0.6
        else:
            scores["relative_strength"] = 0
    else:
        scores["relative_strength"] = 0

    return scores


def compute_total_score(
    df: pd.DataFrame,
    pattern: dict,
    sector: str,
    spy_df: pd.DataFrame | None = None,
) -> dict:
    """
    Compute the full score for a stock + pattern combination.

    Returns:
        {
            "total": int (0-100),
            "status": "READY" | "WATCH" | "BUILDING" | None,
            "breakdown": { category: { sub_score_name: value, ... }, ... },
            "criteria_summary": { "Tight": bool, "EMA": bool, "MACD": bool, "Volume": bool },
        }
    """
    pq = score_pattern_quality(pattern)
    ta = score_trend_alignment(df, pattern)
    mo = score_momentum(df, pattern)
    sb = score_sector_bonus(sector, df, spy_df)

    total = round(sum(pq.values()) + sum(ta.values()) + sum(mo.values()) + sum(sb.values()))
    total = min(total, 100)

    # Determine status
    if total >= config.SCORE_READY:
        status = "READY"
    elif total >= config.SCORE_WATCH:
        status = "WATCH"
    elif total >= config.SCORE_BUILDING:
        status = "BUILDING"
    else:
        status = None

    # Build the 4-criteria summary for the display dots
    criteria = pattern["criteria"]
    criteria_summary = {
        "Tight": bool(criteria.get("tight", False) or criteria.get("descending_tl", False) or criteria.get("near_resistance", False)),
        "EMA": bool(criteria.get("ema_stacked", False) or criteria.get("weekly_ema_bullish", False) or criteria.get("ema50_rising", False)),
        "MACD": bool(criteria.get("macd_curl", False) or criteria.get("macd_flat", False) or criteria.get("macd_divergence", False)),
        "Volume": bool(criteria.get("vol_declining", False) or criteria.get("breakout", False) or criteria.get("recovery_volume", False)),
    }

    return {
        "total": total,
        "status": status,
        "breakdown": {
            "pattern_quality": pq,
            "trend_alignment": ta,
            "momentum": mo,
            "sector_bonus": sb,
        },
        "criteria_summary": criteria_summary,
    }
