#!/usr/bin/env python3
"""
Breakout Scanner — CLI entry point.
Scans the watchlist for momentum breakout setups and prints formatted results.

Usage:
    python scanner.py                         # Scan all tickers, all setups
    python scanner.py --type 1                # Only Setup Type 1 (Daily Tight Base)
    python scanner.py --sector Semiconductors # Only scan one sector
    python scanner.py --min-score 70          # Only show scores >= 70
    python scanner.py --clear-cache           # Clear data cache and re-download
"""

import argparse
import time
from datetime import datetime

import pandas as pd

import data
import config
from indicators import add_all_indicators, add_weekly_indicators
from patterns import detect_all_patterns, SETUP_NAMES
from scoring import compute_total_score
from db import init_db, clear_today, save_scan_result


# ── Market cap cache (fetched once per scan run) ────────────────────────────
_mcap_cache: dict[str, float] = {}


def _get_market_cap(ticker: str) -> float:
    """Fetch market cap for a ticker via yfinance. Returns 0 on failure."""
    if ticker in _mcap_cache:
        return _mcap_cache[ticker]
    try:
        info = yf.Ticker(ticker).info
        cap = info.get("marketCap", 0) or 0
    except Exception:
        cap = 0
    _mcap_cache[ticker] = cap
    return cap


def passes_pre_filters(ticker: str, daily: pd.DataFrame) -> tuple[bool, str]:
    """
    Run pre-filters on a stock before pattern detection.
    Returns (passed: bool, reason: str).
    If passed is False, reason explains why it was skipped.
    """
    pf = config.PRE_FILTERS
    last = daily.iloc[-1]
    price = last["Close"]

    # Price > min
    if price < pf["min_price"]:
        return False, f"price ${price:.2f} < ${pf['min_price']}"

    # Daily change > min
    if len(daily) >= 2:
        prev = daily["Close"].iloc[-2]
        change_pct = (price - prev) / prev * 100
        if change_pct < pf["min_change_pct"]:
            return False, f"change {change_pct:+.2f}% < {pf['min_change_pct']}%"

    # 10-day avg volume > min
    vol_10 = last.get("Vol_10")
    if pd.notna(vol_10) and vol_10 < pf["min_avg_volume_10d"]:
        return False, f"avg vol {vol_10:,.0f} < {pf['min_avg_volume_10d']:,.0f}"

    # ADR (Average Daily Range) > min
    if "DailyRange" in daily.columns:
        adr = daily["DailyRange"].iloc[-10:].mean() * 100  # as percentage
        if adr < pf["min_adr_pct"]:
            return False, f"ADR {adr:.1f}% < {pf['min_adr_pct']}%"

    # Price above EMA 21
    ema21 = last.get(f"EMA_{config.EMA_MID}")
    if pf["price_above_ema21"] and pd.notna(ema21) and price < ema21:
        return False, f"price below EMA 21"

    # Price above EMA 50
    ema50 = last.get(f"EMA_{config.EMA_SLOW}")
    if pf["price_above_ema50"] and pd.notna(ema50) and price < ema50:
        return False, f"price below EMA 50"

    # Market cap > min
    if pf["min_market_cap"] > 0:
        mcap = _get_market_cap(ticker)
        if 0 < mcap < pf["min_market_cap"]:
            return False, f"mkt cap ${mcap/1e6:.0f}M < ${pf['min_market_cap']/1e6:.0f}M"

    return True, ""


def scan_ticker(
    ticker: str,
    sector: str,
    spy_df,
    setup_types: list[int] | None = None,
) -> list[dict]:
    """
    Scan a single ticker for breakout patterns.
    Returns a list of scored results (one per detected pattern).
    """
    daily = data.fetch_daily(ticker)
    if daily is None or len(daily) < 60:
        return []

    daily = add_all_indicators(daily)

    # Run pre-filters
    passed, reason = passes_pre_filters(ticker, daily)
    if not passed:
        return []

    # Fetch weekly data for Setup 2
    weekly = None
    if setup_types is None or 2 in setup_types:
        weekly = data.fetch_weekly(ticker)
        if weekly is not None and len(weekly) >= 20:
            weekly = add_weekly_indicators(weekly)
        else:
            weekly = None

    # Detect patterns
    patterns = detect_all_patterns(daily, weekly, setup_types)
    if not patterns:
        return []

    # Fetch IV data (only for stocks that passed pre-filters)
    iv_data = data.fetch_iv_data(ticker)

    # Build IV summary
    last = daily.iloc[-1]
    hv20 = round(float(last["HV20"]), 1) if pd.notna(last.get("HV20")) else None
    hv50 = round(float(last["HV50"]), 1) if pd.notna(last.get("HV50")) else None

    iv_info = {}
    if iv_data:
        iv = iv_data["iv"]
        iv_info["iv"] = iv
        iv_info["hv20"] = hv20
        iv_info["hv50"] = hv50
        iv_info["expiration"] = iv_data["expiration"]
        iv_info["strike"] = iv_data["strike"]
        iv_info["bid"] = iv_data["bid"]
        iv_info["ask"] = iv_data["ask"]
        iv_info["oi"] = iv_data["open_interest"]

        # IV vs HV ratio — below 1.0 means options are cheap relative to actual movement
        if hv20 and hv20 > 0:
            iv_info["iv_hv_ratio"] = round(iv / hv20, 2)
        else:
            iv_info["iv_hv_ratio"] = None

        # HV compression — HV20 < HV50 means vol contracting (good for buying before breakout)
        if hv20 and hv50:
            iv_info["hv_compressing"] = hv20 < hv50

        # IV label
        if iv_info.get("iv_hv_ratio") is not None:
            ratio = iv_info["iv_hv_ratio"]
            if ratio < 0.8:
                iv_info["iv_label"] = "CHEAP"
            elif ratio < 1.1:
                iv_info["iv_label"] = "FAIR"
            else:
                iv_info["iv_label"] = "EXPENSIVE"
        else:
            iv_info["iv_label"] = "N/A"
    else:
        iv_info = {"iv": None, "hv20": hv20, "hv50": hv50, "iv_label": "N/A"}

    # Score each detected pattern
    results = []
    for pat in patterns:
        score_data = compute_total_score(daily, pat, sector, spy_df)
        if score_data["status"] is None:
            continue  # Below display threshold

        # Get price info
        prev_close = daily["Close"].iloc[-2] if len(daily) >= 2 else last["Close"]
        change_pct = (last["Close"] - prev_close) / prev_close * 100

        results.append({
            "ticker": ticker,
            "sector": sector,
            "setup_type": pat["setup_type"],
            "setup_name": SETUP_NAMES[pat["setup_type"]],
            "score": score_data["total"],
            "status": score_data["status"],
            "criteria_summary": score_data["criteria_summary"],
            "note": pat["note"],
            "price": round(last["Close"], 2),
            "change_pct": round(change_pct, 2),
            "breakout_triggered": pat["breakout_triggered"],
            "breakdown": score_data["breakdown"],
            "iv_info": iv_info,
        })

    return results


def run_scan(
    setup_types: list[int] | None = None,
    sector_filter: str | None = None,
    min_score: int = 50,
) -> list[dict]:
    """
    Run the full scan across the watchlist.
    Returns all scored results sorted by score descending.
    """
    # Initialize DB and clear any previous results for today
    init_db()
    clear_today()

    # Get SPY data for relative strength
    print("  Fetching SPY reference data...")
    spy_df = data.fetch_spy_daily()
    if spy_df is not None:
        spy_df = add_all_indicators(spy_df)

    # Build ticker list
    tickers = data.get_all_tickers()
    if sector_filter:
        tickers = [(t, s) for t, s in tickers if s == sector_filter]

    all_results = []
    total = len(tickers)
    filtered_count = 0

    print(f"  Scanning {total} tickers (pre-filtering enabled)...\n")

    for i, (ticker, sector) in enumerate(tickers, 1):
        print(f"\r  [{i}/{total}] {ticker:<6}", end="", flush=True)
        results = scan_ticker(ticker, sector, spy_df, setup_types)
        if not results:
            filtered_count += 1
        for r in results:
            if r["score"] >= min_score:
                all_results.append(r)
                # Save to DB
                save_scan_result(r)

    print("\r" + " " * 40 + "\r", end="")  # Clear progress line
    passed_count = total - filtered_count
    print(f"  Pre-filter: {passed_count}/{total} passed, {filtered_count} skipped\n")

    # Deduplicate: keep only the highest-scoring result per ticker
    best_by_ticker = {}
    for r in all_results:
        t = r["ticker"]
        if t not in best_by_ticker or r["score"] > best_by_ticker[t]["score"]:
            best_by_ticker[t] = r
    all_results = list(best_by_ticker.values())

    # Sort by score descending
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Output Formatting
# ═══════════════════════════════════════════════════════════════════════════════

def _check(val: bool) -> str:
    return "✓" if val else "✗"


def _format_criteria(criteria: dict) -> str:
    parts = []
    for key, val in criteria.items():
        parts.append(f"{_check(val)} {key}")
    return "  ".join(parts)


def print_results(results: list[dict], elapsed: float):
    """Print formatted CLI output."""
    now = datetime.now()
    date_str = now.strftime("%A, %b %d, %Y")

    # Group by status
    ready = [r for r in results if r["status"] == "READY"]
    watch = [r for r in results if r["status"] == "WATCH"]
    building = [r for r in results if r["status"] == "BUILDING"]

    # Determine leading sectors from results
    sector_counts = {}
    for r in results:
        sector_counts[r["sector"]] = sector_counts.get(r["sector"], 0) + 1
    leading = sorted(sector_counts, key=sector_counts.get, reverse=True)[:3]

    # Header
    print()
    print("══════════════════════════════════════════════════════════════")
    print(f"  BREAKOUT SCANNER — {date_str}")
    if leading:
        print(f"  Sectors Leading: {' | '.join(leading)}")
    print("══════════════════════════════════════════════════════════════")

    def print_group(title: str, emoji: str, items: list[dict]):
        if not items:
            return
        print(f"\n{emoji} {title}")
        print("──────────────────────────────────────────────────────────────")
        for r in items:
            sector_short = r["sector"].split("/")[0].split(" ")[0][:10]
            print(
                f"{r['ticker']:<6}| {sector_short:<12}| {r['score']:>3} "
                f"| Type {r['setup_type']}: {r['setup_name']}"
            )
            print(f"  → {r['note']}")
            print(f"  {_format_criteria(r['criteria_summary'])}")

            # IV line
            iv = r.get("iv_info", {})
            iv_parts = [f"Price: ${r['price']:.2f} ({r['change_pct']:+.1f}%)"]
            if iv.get("iv") is not None:
                label = iv.get("iv_label", "")
                iv_parts.append(f"IV: {iv['iv']:.0f}%")
                if iv.get("hv20"):
                    iv_parts.append(f"HV20: {iv['hv20']:.0f}%")
                if iv.get("iv_hv_ratio") is not None:
                    iv_parts.append(f"IV/HV: {iv['iv_hv_ratio']:.2f}")
                if label in ("CHEAP", "FAIR"):
                    iv_parts.append(f"[{label}]")
                elif label == "EXPENSIVE":
                    iv_parts.append(f"[{label}]")
            print(f"  {' | '.join(iv_parts)}")
            print()

    print_group("READY (Score 85+)", "🟢", ready)
    print_group("WATCH (Score 70-84)", "🟡", watch)
    print_group("BUILDING (Score 50-69)", "⏳", building)

    if not results:
        print("\n  No setups detected above the score threshold today.")

    # Footer
    total_tickers = sum(len(v) for v in config.WATCHLIST.values())
    print("══════════════════════════════════════════════════════════════")
    print(
        f"  Scanned {total_tickers} tickers in {elapsed:.0f}s | "
        f"{len(ready)} READY | {len(watch)} WATCH | {len(building)} BUILDING"
    )
    print("══════════════════════════════════════════════════════════════")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Breakout Scanner — find momentum breakout setups")
    parser.add_argument("--type", type=int, choices=[1, 2, 3, 4], help="Only run a specific setup type")
    parser.add_argument("--sector", type=str, help="Only scan a specific sector")
    parser.add_argument("--min-score", type=int, default=config.SCORE_BUILDING, help="Minimum score to display")
    parser.add_argument("--clear-cache", action="store_true", help="Clear cached data before scanning")
    args = parser.parse_args()

    if args.clear_cache:
        data.clear_cache()

    setup_types = [args.type] if args.type else None

    print("\n  Starting breakout scan...")
    start = time.time()
    results = run_scan(setup_types=setup_types, sector_filter=args.sector, min_score=args.min_score)
    elapsed = time.time() - start

    print_results(results, elapsed)


if __name__ == "__main__":
    main()
