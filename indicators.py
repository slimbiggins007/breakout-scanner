"""
Technical indicator calculations.
Computes EMAs, MACD, ATR, and volume metrics on OHLCV DataFrames.
"""

import pandas as pd
import numpy as np

import config


def add_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA columns (9, 21, 50) to the DataFrame."""
    df[f"EMA_{config.EMA_FAST}"] = df["Close"].ewm(span=config.EMA_FAST, adjust=False).mean()
    df[f"EMA_{config.EMA_MID}"] = df["Close"].ewm(span=config.EMA_MID, adjust=False).mean()
    df[f"EMA_{config.EMA_SLOW}"] = df["Close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    Add MACD line, signal line, and histogram columns.
    MACD = EMA(12) - EMA(26), Signal = EMA(9) of MACD, Histogram = MACD - Signal.
    """
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    df["MACD"] = ema_fast - ema_slow
    df["MACD_Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add Average True Range column."""
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(window=period).mean()
    return df


def add_daily_range(df: pd.DataFrame) -> pd.DataFrame:
    """Add daily candle range as a percentage of close: (High - Low) / Close."""
    df["DailyRange"] = (df["High"] - df["Low"]) / df["Close"]
    return df


def add_volume_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling volume averages for breakout detection."""
    df["Vol_5"] = df["Volume"].rolling(5).mean()
    df["Vol_10"] = df["Volume"].rolling(10).mean()
    df["Vol_20"] = df["Volume"].rolling(20).mean()
    df["Vol_50"] = df["Volume"].rolling(50).mean()
    return df


def add_historical_volatility(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add historical volatility columns (annualized std dev of daily log returns).
    HV20 = 20-day, HV50 = 50-day. Used for IV vs HV comparison.
    """
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    df["HV20"] = log_ret.rolling(20).std() * np.sqrt(252) * 100   # annualized, as %
    df["HV50"] = log_ret.rolling(50).std() * np.sqrt(252) * 100
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all standard indicators to a daily OHLCV DataFrame."""
    df = add_emas(df)
    df = add_macd(df)
    df = add_atr(df)
    df = add_daily_range(df)
    df = add_volume_metrics(df)
    df = add_historical_volatility(df)
    return df


def add_weekly_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add indicators suited for weekly timeframe analysis."""
    df = add_emas(df)
    df = add_macd(df)
    df["Vol_10"] = df["Volume"].rolling(10).mean()
    return df


# ── Helper queries on indicator data ────────────────────────────────────────────

def ema_stacked(df: pd.DataFrame) -> bool:
    """Check if EMAs are properly stacked: Price > EMA9 > EMA21 > EMA50."""
    if len(df) < 1:
        return False
    last = df.iloc[-1]
    return (
        last["Close"] > last[f"EMA_{config.EMA_FAST}"]
        and last[f"EMA_{config.EMA_FAST}"] > last[f"EMA_{config.EMA_MID}"]
        and last[f"EMA_{config.EMA_MID}"] > last[f"EMA_{config.EMA_SLOW}"]
    )


def emas_rising(df: pd.DataFrame, lookback: int = 5) -> dict[str, bool]:
    """Check if each EMA is rising (today's value > N days ago)."""
    if len(df) < lookback + 1:
        return {"fast": False, "mid": False, "slow": False}
    current = df.iloc[-1]
    past = df.iloc[-(lookback + 1)]
    return {
        "fast": current[f"EMA_{config.EMA_FAST}"] > past[f"EMA_{config.EMA_FAST}"],
        "mid": current[f"EMA_{config.EMA_MID}"] > past[f"EMA_{config.EMA_MID}"],
        "slow": current[f"EMA_{config.EMA_SLOW}"] > past[f"EMA_{config.EMA_SLOW}"],
    }


def macd_curling_up(df: pd.DataFrame) -> bool:
    """Check if MACD histogram is turning up (today > yesterday)."""
    if len(df) < 2:
        return False
    return df["MACD_Hist"].iloc[-1] > df["MACD_Hist"].iloc[-2]


def macd_hist_flat(df: pd.DataFrame, lookback: int = 20) -> bool:
    """Check if current MACD histogram is in the bottom 30% of recent values (flattening)."""
    if len(df) < lookback:
        return False
    recent = df["MACD_Hist"].iloc[-lookback:].abs()
    threshold = recent.quantile(config.TIGHT_BASE["macd_hist_percentile"] / 100)
    return abs(df["MACD_Hist"].iloc[-1]) <= threshold


def volume_declining(df: pd.DataFrame) -> bool:
    """Check if 5-day avg volume < 80% of 20-day avg volume (consolidation drying up)."""
    last = df.iloc[-1]
    if pd.isna(last["Vol_5"]) or pd.isna(last["Vol_20"]) or last["Vol_20"] == 0:
        return False
    return last["Vol_5"] < config.TIGHT_BASE["vol_decline_ratio"] * last["Vol_20"]


def volume_surge(df: pd.DataFrame, multiplier: float = 1.5) -> bool:
    """Check if today's volume is a surge relative to the 20-day average."""
    last = df.iloc[-1]
    if pd.isna(last["Vol_20"]) or last["Vol_20"] == 0:
        return False
    return last["Volume"] > multiplier * last["Vol_20"]


def relative_strength_vs_spy(stock_df: pd.DataFrame, spy_df: pd.DataFrame, lookback: int = 20) -> float:
    """
    Calculate relative strength of a stock vs SPY over the last N days.
    Returns the ratio of stock return to SPY return.
    A value > 1.0 means the stock outperformed SPY.
    """
    if len(stock_df) < lookback or len(spy_df) < lookback:
        return 1.0

    stock_ret = (stock_df["Close"].iloc[-1] / stock_df["Close"].iloc[-lookback] - 1) * 100
    spy_ret = (spy_df["Close"].iloc[-1] / spy_df["Close"].iloc[-lookback] - 1) * 100

    # Avoid division by zero
    if abs(spy_ret) < 0.001:
        return 1.0 + stock_ret
    return stock_ret / spy_ret if spy_ret > 0 else 1.0
