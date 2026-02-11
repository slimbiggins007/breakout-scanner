"""
Pattern detection engine.
Detects 4 setup types and returns structured results with criteria pass/fail.
"""

import numpy as np
import pandas as pd

import config
from indicators import (
    ema_stacked,
    emas_rising,
    macd_curling_up,
    macd_hist_flat,
    volume_declining,
    volume_surge,
)


# ── Result structure ────────────────────────────────────────────────────────────

def _empty_result(setup_type: int) -> dict:
    """Return a blank result dict for a given setup type."""
    return {
        "setup_type": setup_type,
        "detected": False,
        "breakout_triggered": False,
        "criteria": {},         # str -> bool for each check
        "details": {},          # Numeric details for scoring
        "note": "",             # Human-readable summary
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SETUP 1: Daily Tight Base Breakout
# ═══════════════════════════════════════════════════════════════════════════════

def detect_tight_base(df: pd.DataFrame) -> dict:
    """
    Detect a daily tight base breakout pattern.

    Looks for:
    - Tight daily ranges (consolidation)
    - EMAs properly stacked and rising
    - Volume declining during base
    - MACD histogram flattening then curling up
    - Breakout: close above consolidation high on volume surge
    """
    result = _empty_result(1)
    cfg = config.TIGHT_BASE

    if len(df) < cfg["lookback_range"] + 10:
        return result

    # ── Tightness check ─────────────────────────────────────────────────────
    # Method 1: Average daily range over last 5 days vs percentile of last 20
    recent_range = df["DailyRange"].iloc[-cfg["tight_window"]:]
    avg_recent_range = recent_range.mean()
    lookback_range = df["DailyRange"].iloc[-cfg["lookback_range"]:]
    percentile_threshold = lookback_range.quantile(cfg["tight_percentile"] / 100)
    tight_by_range = avg_recent_range <= percentile_threshold

    # Method 2: Standard deviation of closes over last 5 days < 1.5% of price
    recent_closes = df["Close"].iloc[-cfg["tight_window"]:]
    close_stdev = recent_closes.std()
    current_price = df["Close"].iloc[-1]
    tight_by_stdev = close_stdev < (cfg["close_stdev_pct"] / 100) * current_price

    is_tight = tight_by_range or tight_by_stdev

    # Calculate tightness score (0-1, lower = tighter)
    if lookback_range.std() > 0:
        tightness_score = 1 - (avg_recent_range / lookback_range.max())
    else:
        tightness_score = 0.5

    # ── Count consolidation days ────────────────────────────────────────────
    # Count consecutive days where daily range is below median
    median_range = lookback_range.median()
    consol_days = 0
    for i in range(1, min(15, len(df))):
        if df["DailyRange"].iloc[-i] <= median_range:
            consol_days += 1
        else:
            break

    # ── EMA stack check ─────────────────────────────────────────────────────
    is_stacked = ema_stacked(df)
    rising = emas_rising(df)
    all_rising = all(rising.values())

    # ── Volume declining check ──────────────────────────────────────────────
    vol_dried = volume_declining(df)

    # Calculate volume decline ratio for scoring
    last = df.iloc[-1]
    if not pd.isna(last["Vol_5"]) and not pd.isna(last["Vol_20"]) and last["Vol_20"] > 0:
        vol_ratio = last["Vol_5"] / last["Vol_20"]
    else:
        vol_ratio = 1.0

    # ── MACD checks ─────────────────────────────────────────────────────────
    macd_flat = macd_hist_flat(df)
    macd_curl = macd_curling_up(df)

    # ── Breakout check ──────────────────────────────────────────────────────
    # Close > highest high of last 5 consolidation days AND volume surge
    consol_window = min(cfg["max_consol_days"], max(cfg["min_consol_days"], consol_days))
    consol_high = df["High"].iloc[-(consol_window + 1):-1].max()
    breakout_price = current_price > consol_high
    breakout_vol = volume_surge(df, cfg["breakout_vol_mult"])
    breakout = breakout_price and breakout_vol

    # ── Assemble result ─────────────────────────────────────────────────────
    result["criteria"] = {
        "tight": is_tight,
        "ema_stacked": is_stacked,
        "ema_rising": all_rising,
        "vol_declining": vol_dried,
        "macd_flat": macd_flat,
        "macd_curl": macd_curl,
        "breakout": breakout,
    }
    result["details"] = {
        "tightness_score": round(tightness_score, 3),
        "consol_days": consol_days,
        "vol_decline_ratio": round(vol_ratio, 3),
        "consol_high": round(consol_high, 2),
        "current_price": round(current_price, 2),
        "tight_by_range": tight_by_range,
        "tight_by_stdev": tight_by_stdev,
    }

    # Pattern detected if base criteria are met (even without breakout)
    core_criteria = [is_tight, is_stacked]
    result["detected"] = sum(result["criteria"].values()) >= 3
    result["breakout_triggered"] = breakout

    # Build human-readable note
    parts = []
    if consol_days >= 3:
        parts.append(f"{consol_days}-day tight base")
    if is_stacked:
        parts.append("above stacked EMAs")
    if macd_curl:
        parts.append("MACD curling")
    if vol_dried:
        parts.append(f"vol dried up {int((1 - vol_ratio) * 100)}%")
    if breakout:
        parts.append(f"BREAKOUT above ${consol_high:.0f}")
    result["note"] = ". ".join(parts) + "." if parts else "Insufficient criteria."

    if breakout:
        result["note"] = f"Pivot: ${consol_high:.0f}. " + result["note"]

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SETUP 2: Weekly Base / Horizontal Resistance Breakout
# ═══════════════════════════════════════════════════════════════════════════════

def _find_resistance_level(highs: pd.Series, cluster_pct: float, min_touches: int) -> float | None:
    """
    Find a horizontal resistance level from a series of highs.
    Groups highs into clusters within cluster_pct of each other.
    Returns the resistance level with the most touches, or None.
    """
    if len(highs) < min_touches:
        return None

    sorted_highs = sorted(highs.values, reverse=True)
    best_level = None
    best_count = 0

    for candidate in sorted_highs:
        # Count how many highs are within cluster_pct of this candidate
        threshold = candidate * (cluster_pct / 100)
        count = sum(1 for h in sorted_highs if abs(h - candidate) <= threshold)
        if count >= min_touches and count > best_count:
            best_count = count
            # Average the clustered highs for a cleaner level
            clustered = [h for h in sorted_highs if abs(h - candidate) <= threshold]
            best_level = np.mean(clustered)

    return best_level


def detect_weekly_base(daily_df: pd.DataFrame, weekly_df: pd.DataFrame) -> dict:
    """
    Detect a weekly base / horizontal resistance breakout.

    Looks for:
    - Clear horizontal resistance from repeated rejections
    - Price approaching that resistance
    - Weekly EMAs converging/crossing
    - Breakout above resistance on volume
    """
    result = _empty_result(2)
    cfg = config.WEEKLY_BASE

    if weekly_df is None or len(weekly_df) < cfg["resistance_lookback_weeks"]:
        return result

    lookback = weekly_df.iloc[-cfg["resistance_lookback_weeks"]:]

    # ── Find horizontal resistance ──────────────────────────────────────────
    resistance = _find_resistance_level(
        lookback["High"],
        cfg["resistance_cluster_pct"],
        cfg["min_rejections"],
    )

    if resistance is None:
        return result

    # ── Proximity check ─────────────────────────────────────────────────────
    current_price = weekly_df["Close"].iloc[-1]
    distance_pct = abs(current_price - resistance) / resistance * 100
    near_resistance = distance_pct <= cfg["proximity_pct"]

    # ── Weekly EMA checks ───────────────────────────────────────────────────
    last_w = weekly_df.iloc[-1]
    ema_f = f"EMA_{config.EMA_FAST}"
    ema_m = f"EMA_{config.EMA_MID}"
    ema_s = f"EMA_{config.EMA_SLOW}"

    weekly_ema_bullish = last_w[ema_f] > last_w[ema_m]

    # Check for EMA cross (9 crossing above 21)
    if len(weekly_df) >= 2:
        prev_w = weekly_df.iloc[-2]
        ema_cross = (prev_w[ema_f] <= prev_w[ema_m]) and (last_w[ema_f] > last_w[ema_m])
    else:
        ema_cross = False

    ema_ok = weekly_ema_bullish or ema_cross

    # 50 EMA rising
    if len(weekly_df) >= 6:
        ema50_rising = last_w[ema_s] > weekly_df.iloc[-6][ema_s]
    else:
        ema50_rising = False

    # ── Breakout check ──────────────────────────────────────────────────────
    breakout_price = current_price > resistance
    vol_10 = last_w.get("Vol_10", 0)
    breakout_vol = last_w["Volume"] > cfg["breakout_vol_mult"] * vol_10 if vol_10 > 0 else False
    breakout = breakout_price and breakout_vol

    # ── Assemble result ─────────────────────────────────────────────────────
    result["criteria"] = {
        "resistance_found": True,
        "near_resistance": near_resistance,
        "weekly_ema_bullish": ema_ok,
        "ema50_rising": ema50_rising,
        "breakout": breakout,
    }
    result["details"] = {
        "resistance_level": round(resistance, 2),
        "distance_pct": round(distance_pct, 2),
        "current_price": round(current_price, 2),
        "ema_cross": ema_cross,
    }
    result["detected"] = near_resistance and ema_ok
    result["breakout_triggered"] = breakout

    parts = []
    parts.append(f"Weekly resistance at ${resistance:.0f}")
    if near_resistance:
        parts.append(f"price within {distance_pct:.1f}%")
    if ema_cross:
        parts.append("weekly 9/21 EMA cross")
    elif weekly_ema_bullish:
        parts.append("weekly EMAs bullish")
    if breakout:
        parts.append("BREAKOUT above resistance")
    result["note"] = ". ".join(parts) + "."

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SETUP 3: Descending Trendline Compression Breakout
# ═══════════════════════════════════════════════════════════════════════════════

def _find_swing_highs(df: pd.DataFrame, order: int = 5) -> list[tuple[int, float]]:
    """
    Find local maxima (swing highs) in the High column.
    A swing high is a point higher than `order` bars on each side.
    Returns list of (index_position, price).
    """
    highs = df["High"].values
    swings = []
    for i in range(order, len(highs) - order):
        if all(highs[i] >= highs[i - j] for j in range(1, order + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, order + 1)):
            swings.append((i, highs[i]))
    return swings


def _find_swing_lows(df: pd.DataFrame, order: int = 5) -> list[tuple[int, float]]:
    """Find local minima (swing lows) in the Low column."""
    lows = df["Low"].values
    swings = []
    for i in range(order, len(lows) - order):
        if all(lows[i] <= lows[i - j] for j in range(1, order + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, order + 1)):
            swings.append((i, lows[i]))
    return swings


def detect_trendline_compression(df: pd.DataFrame) -> dict:
    """
    Detect a descending trendline compression (pennant/wedge) pattern.

    Looks for:
    - Descending swing highs forming a trendline
    - Horizontal or rising support
    - Converging trendline and support
    - Volume trending lower
    - Breakout above the trendline on volume
    """
    result = _empty_result(3)
    cfg = config.TRENDLINE

    lookback = min(cfg["swing_lookback"], len(df))
    if lookback < 30:
        return result

    window = df.iloc[-lookback:]

    # ── Find swing highs and fit descending trendline ───────────────────────
    swing_highs = _find_swing_highs(window, order=3)
    if len(swing_highs) < cfg["min_swing_highs"]:
        return result

    # Fit a line through the swing highs using least squares
    sh_x = np.array([s[0] for s in swing_highs])
    sh_y = np.array([s[1] for s in swing_highs])
    coeffs = np.polyfit(sh_x, sh_y, 1)
    slope, intercept = coeffs[0], coeffs[1]

    # Trendline must be descending
    descending = slope < 0

    # ── Find horizontal support ─────────────────────────────────────────────
    swing_lows = _find_swing_lows(window, order=3)
    if len(swing_lows) < 2:
        return result

    sl_prices = [s[1] for s in swing_lows]
    support_level = np.mean(sl_prices)

    # Check if swing lows are clustered (horizontal support)
    sl_range = (max(sl_prices) - min(sl_prices)) / support_level * 100
    support_horizontal = sl_range <= cfg["support_cluster_pct"]

    # ── Convergence check ───────────────────────────────────────────────────
    # Trendline value at first and last swing high positions
    tl_at_start = slope * sh_x[0] + intercept
    tl_at_end = slope * sh_x[-1] + intercept
    gap_start = tl_at_start - support_level
    gap_end = tl_at_end - support_level
    converging = gap_end < gap_start and gap_end > 0

    # ── Volume trending lower ───────────────────────────────────────────────
    last = df.iloc[-1]
    vol_declining = False
    if not pd.isna(last.get("Vol_20")) and not pd.isna(last.get("Vol_50")):
        vol_declining = last["Vol_20"] < last["Vol_50"]

    # ── EMA convergence check ───────────────────────────────────────────────
    ema_f = f"EMA_{config.EMA_FAST}"
    ema_m = f"EMA_{config.EMA_MID}"
    if ema_f in df.columns and ema_m in df.columns:
        ema_spread = abs(last[ema_f] - last[ema_m]) / last["Close"] * 100
        ema_converging = ema_spread < 2.0
    else:
        ema_converging = False

    # ── Breakout check ──────────────────────────────────────────────────────
    # Current trendline value at the last bar
    tl_now = slope * (lookback - 1) + intercept
    breakout_price = last["Close"] > tl_now
    breakout_vol = volume_surge(df, cfg["breakout_vol_mult"])
    breakout = breakout_price and breakout_vol

    # ── Assemble result ─────────────────────────────────────────────────────
    result["criteria"] = {
        "descending_tl": descending,
        "horizontal_support": support_horizontal,
        "converging": converging,
        "vol_declining": vol_declining,
        "ema_converging": ema_converging,
        "breakout": breakout,
    }
    result["details"] = {
        "tl_slope": round(slope, 4),
        "support_level": round(support_level, 2),
        "tl_value_now": round(tl_now, 2),
        "gap_pct": round(gap_end / support_level * 100, 2) if support_level > 0 else 0,
        "num_swing_highs": len(swing_highs),
        "current_price": round(last["Close"], 2),
    }
    result["detected"] = descending and support_horizontal and converging
    result["breakout_triggered"] = breakout

    parts = []
    if descending:
        parts.append("Descending trendline")
    if converging:
        parts.append(f"converging with support at ${support_level:.0f}")
    if vol_declining:
        parts.append("volume contracting")
    if ema_converging:
        parts.append("EMAs converging")
    if breakout:
        parts.append(f"BREAKOUT above trendline at ${tl_now:.0f}")
    result["note"] = ". ".join(parts) + "." if parts else "Pattern not detected."

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SETUP 4: Undercut & Rally (False Breakdown Recovery)
# ═══════════════════════════════════════════════════════════════════════════════

def _find_support_level(df: pd.DataFrame, lookback: int, cluster_pct: float, min_touches: int) -> float | None:
    """Find a horizontal support level from swing lows."""
    window = df.iloc[-lookback:]
    swing_lows = _find_swing_lows(window, order=3)
    if len(swing_lows) < min_touches:
        # Fallback: use rolling lows
        lows = window["Low"].values
        # Find the most common low region
        if len(lows) < 5:
            return None
        sorted_lows = sorted(lows)
        best_level = None
        best_count = 0
        for candidate in sorted_lows[:10]:
            threshold = candidate * (cluster_pct / 100)
            count = sum(1 for l in sorted_lows if abs(l - candidate) <= threshold)
            if count >= min_touches and count > best_count:
                best_count = count
                clustered = [l for l in sorted_lows if abs(l - candidate) <= threshold]
                best_level = np.mean(clustered)
        return best_level

    sl_prices = [s[1] for s in swing_lows]
    return _find_resistance_level(pd.Series(sl_prices), cluster_pct, min_touches)


def detect_undercut_rally(df: pd.DataFrame) -> dict:
    """
    Detect an undercut & rally (false breakdown recovery).

    Looks for:
    - Horizontal support level with multiple touches
    - Recent close below that support (within last 1-5 days)
    - Price recovered back above support
    - Strong recovery candle (close in upper 25% of range)
    - Recovery volume above average
    - 50 EMA still rising
    """
    result = _empty_result(4)
    cfg = config.UNDERCUT

    if len(df) < cfg["support_lookback"] + 10:
        return result

    # ── Find support level ──────────────────────────────────────────────────
    support = _find_support_level(
        df, cfg["support_lookback"],
        cfg["support_cluster_pct"],
        cfg["min_support_touches"],
    )
    if support is None:
        return result

    # ── Check for recent breakdown below support ────────────────────────────
    had_breakdown = False
    breakdown_day = None
    for i in range(1, cfg["breakdown_window"] + 1):
        if len(df) < i + 1:
            break
        if df["Close"].iloc[-i] < support:
            had_breakdown = True
            breakdown_day = i
            break

    # ── Check recovery ──────────────────────────────────────────────────────
    last = df.iloc[-1]
    recovered_above = last["Close"] > support

    # Recovery candle: close in upper 25% of daily range
    candle_range = last["High"] - last["Low"]
    if candle_range > 0:
        close_position = (last["Close"] - last["Low"]) / candle_range * 100
    else:
        close_position = 50
    strong_candle = close_position >= (100 - cfg["recovery_candle_pct"])

    # Recovery volume
    recovery_vol = volume_surge(df, cfg["recovery_vol_mult"])

    # 50 EMA still rising
    ema_s = f"EMA_{config.EMA_SLOW}"
    if ema_s in df.columns and len(df) >= 6:
        ema50_rising = last[ema_s] > df.iloc[-6][ema_s]
    else:
        ema50_rising = False

    # ── MACD bullish divergence (bonus) ─────────────────────────────────────
    # Price made lower low but MACD made higher low
    macd_divergence = False
    if had_breakdown and "MACD" in df.columns and len(df) >= 20:
        price_recent_low = df["Low"].iloc[-cfg["breakdown_window"]:].min()
        price_prior_low = df["Low"].iloc[-20:-cfg["breakdown_window"]].min()
        macd_recent_low = df["MACD"].iloc[-cfg["breakdown_window"]:].min()
        macd_prior_low = df["MACD"].iloc[-20:-cfg["breakdown_window"]].min()
        if price_recent_low < price_prior_low and macd_recent_low > macd_prior_low:
            macd_divergence = True

    # ── Assemble result ─────────────────────────────────────────────────────
    result["criteria"] = {
        "support_found": True,
        "had_breakdown": had_breakdown,
        "recovered_above": recovered_above,
        "strong_candle": strong_candle,
        "recovery_volume": recovery_vol,
        "ema50_rising": ema50_rising,
        "macd_divergence": macd_divergence,
    }
    result["details"] = {
        "support_level": round(support, 2),
        "breakdown_day": breakdown_day,
        "close_position_pct": round(close_position, 1),
        "current_price": round(last["Close"], 2),
    }
    result["detected"] = had_breakdown and recovered_above
    result["breakout_triggered"] = had_breakdown and recovered_above and strong_candle and recovery_vol

    parts = []
    parts.append(f"Support at ${support:.0f}")
    if had_breakdown:
        parts.append(f"broke below {breakdown_day}d ago")
    if recovered_above:
        parts.append("recovered above support")
    if strong_candle:
        parts.append("strong recovery candle")
    if macd_divergence:
        parts.append("MACD bullish divergence")
    result["note"] = ". ".join(parts) + "." if parts else "Pattern not detected."

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Main detection runner
# ═══════════════════════════════════════════════════════════════════════════════

SETUP_NAMES = {
    1: "Daily Tight Base",
    2: "Weekly Base Breakout",
    3: "Trendline Compression",
    4: "Undercut & Rally",
}


def detect_all_patterns(
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame | None = None,
    setup_types: list[int] | None = None,
) -> list[dict]:
    """
    Run all (or selected) pattern detections on a stock's data.
    Returns a list of result dicts, one per detected pattern.
    Only returns patterns where `detected` is True.
    """
    if setup_types is None:
        setup_types = [1, 2, 3, 4]

    results = []

    if 1 in setup_types:
        r = detect_tight_base(daily_df)
        if r["detected"]:
            results.append(r)

    if 2 in setup_types:
        r = detect_weekly_base(daily_df, weekly_df)
        if r["detected"]:
            results.append(r)

    if 3 in setup_types:
        r = detect_trendline_compression(daily_df)
        if r["detected"]:
            results.append(r)

    if 4 in setup_types:
        r = detect_undercut_rally(daily_df)
        if r["detected"]:
            results.append(r)

    return results
