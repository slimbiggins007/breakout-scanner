"""
Data fetching and caching layer.
Downloads daily/weekly OHLCV data via yfinance, caches to disk to avoid re-downloading.
"""

import os
import time
import hashlib
import pickle
from pathlib import Path

import pandas as pd
import yfinance as yf

import config

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(ticker: str, period: str) -> Path:
    """Return the cache file path for a given ticker + period."""
    key = hashlib.md5(f"{ticker}_{period}".encode()).hexdigest()
    return CACHE_DIR / f"{key}.pkl"


def _is_cache_valid(path: Path) -> bool:
    """Check if a cached file exists and is younger than CACHE_TTL_HOURS."""
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < config.CACHE_TTL_HOURS


def fetch_daily(ticker: str) -> pd.DataFrame | None:
    """
    Fetch daily OHLCV data for a ticker.
    Returns a DataFrame with columns: Open, High, Low, Close, Volume
    or None if the download fails.
    """
    cache = _cache_path(ticker, config.DAILY_PERIOD)
    if _is_cache_valid(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)

    try:
        df = yf.download(ticker, period=config.DAILY_PERIOD, interval="1d", progress=False)
        if df is None or df.empty:
            return None
        # yfinance may return MultiIndex columns for single ticker — flatten
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        # Keep only the columns we need
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(inplace=True)
        with open(cache, "wb") as f:
            pickle.dump(df, f)
        return df
    except Exception as e:
        print(f"  ⚠ Failed to fetch {ticker}: {e}")
        return None


def fetch_weekly(ticker: str) -> pd.DataFrame | None:
    """
    Fetch weekly OHLCV data (resampled from daily via yfinance weekly interval).
    Returns DataFrame with Open, High, Low, Close, Volume or None on failure.
    """
    cache = _cache_path(ticker, config.WEEKLY_PERIOD + "_weekly")
    if _is_cache_valid(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)

    try:
        df = yf.download(ticker, period=config.WEEKLY_PERIOD, interval="1wk", progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(inplace=True)
        with open(cache, "wb") as f:
            pickle.dump(df, f)
        return df
    except Exception as e:
        print(f"  ⚠ Failed to fetch weekly {ticker}: {e}")
        return None


def fetch_spy_daily() -> pd.DataFrame | None:
    """Fetch SPY daily data for relative strength comparison."""
    return fetch_daily("SPY")


def get_all_tickers() -> list[tuple[str, str]]:
    """
    Return a flat list of (ticker, sector) tuples from the watchlist.
    """
    tickers = []
    for sector, symbols in config.WATCHLIST.items():
        for sym in symbols:
            tickers.append((sym, sector))
    return tickers


def fetch_iv_data(ticker: str) -> dict | None:
    """
    Fetch ATM implied volatility from the nearest options expiration.
    Returns dict with iv, expiration, strike, or None on failure.
    Only called for stocks that pass pre-filters (keeps it fast).
    """
    cache = _cache_path(ticker, "iv_data")
    if _is_cache_valid(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)

    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations:
            return None

        # Use the nearest expiration (front month)
        exp = expirations[0]
        chain = tk.option_chain(exp)
        calls = chain.calls

        if calls.empty:
            return None

        # Find the ATM call (strike closest to current price)
        current_price = calls["lastPrice"].iloc[0]  # rough
        try:
            hist = tk.history(period="1d")
            if not hist.empty:
                current_price = hist["Close"].iloc[-1]
        except Exception:
            pass

        calls = calls[calls["impliedVolatility"] > 0].copy()
        if calls.empty:
            return None

        calls["dist"] = (calls["strike"] - current_price).abs()
        atm = calls.loc[calls["dist"].idxmin()]

        result = {
            "iv": round(float(atm["impliedVolatility"]) * 100, 1),  # as percentage
            "strike": float(atm["strike"]),
            "expiration": exp,
            "bid": float(atm.get("bid", 0)),
            "ask": float(atm.get("ask", 0)),
            "volume": int(atm.get("volume", 0)) if pd.notna(atm.get("volume")) else 0,
            "open_interest": int(atm.get("openInterest", 0)) if pd.notna(atm.get("openInterest")) else 0,
        }

        with open(cache, "wb") as f:
            pickle.dump(result, f)
        return result

    except Exception:
        return None


def clear_cache():
    """Remove all cached data files."""
    for f in CACHE_DIR.glob("*.pkl"):
        f.unlink()
    print("Cache cleared.")
