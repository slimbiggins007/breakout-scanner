"""
Configuration for breakout scanner.
Edit WATCHLIST to add/remove tickers. Adjust scoring weights and thresholds below.
"""

# ── Watchlist by sector ─────────────────────────────────────────────────────────

WATCHLIST = {
    "Semiconductors": [
        "NVDA", "AVGO", "KLAC", "LRCX", "CDNS", "ADI", "MU", "TSM",
        "MRVL", "AMAT", "ASML", "ON", "MCHP", "QCOM", "AMD", "INTC",
        "TXN", "NXPI", "SWKS", "MPWR", "RMBS", "CRUS", "WOLF", "GFS",
    ],
    "AI Infrastructure": [
        "ANET", "APLD", "DOCN", "VRT", "SMCI", "DELL", "HPE", "CRWV",
        "NBIS", "ORCL", "IBM", "SNOW", "MDB", "PLTR", "AI", "BBAI",
    ],
    "Financials": [
        "GS", "JPM", "MS", "BAC", "C", "SCHW", "BLK", "ICE", "CME",
        "COIN", "HOOD", "V", "MA", "AXP", "PYPL", "XYZ", "FIS", "GPN",
        "MCO", "SPGI", "MSCI",
    ],
    "Healthcare / Biotech": [
        "LLY", "AMGN", "GILD", "VRTX", "REGN", "ISRG", "DXCM", "ARGX",
        "MRNA", "UNH", "ABT", "TMO", "DHR", "SYK", "BSX", "MDT", "EW",
        "ALNY", "BMRN", "NBIX", "INCY", "HALO",
    ],
    "Industrials": [
        "CAT", "DE", "GE", "HON", "UNP", "URI", "EMR", "ETN", "PH",
        "WM", "RSG", "FAST", "ITW", "ROK", "AME", "IR", "DOV", "GWW",
    ],
    "Energy / Utilities": [
        "VST", "CEG", "GEV", "NRG", "NEE", "TLN", "FSLR", "ENPH",
        "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "DVN", "MPC",
        "PSX", "VLO",
    ],
    "Defense": [
        "LMT", "RTX", "NOC", "GD", "KTOS", "RKLB", "LDOS",
        "HII", "LHX", "BAH", "AXON", "TDG", "HWM",
    ],
    "Software / Cloud": [
        "CRM", "NOW", "PANW", "CRWD", "DDOG", "ZS", "NET", "PATH", "HUBS",
        "MSFT", "ADBE", "INTU", "WDAY", "TEAM", "VEEV", "MNDY", "BILL",
        "ESTC", "CFLT", "GTLB", "S", "CYBR", "FTNT", "QLYS",
    ],
    "Consumer / Retail": [
        "LOW", "HD", "WSM", "COST", "DECK", "LULU", "CMG", "WING",
        "AMZN", "WMT", "TGT", "TJX", "ROST", "NKE", "SBUX", "MCD",
        "CAVA", "DPZ", "TXRH", "ELF", "ONON", "BIRD",
    ],
    "Mega Cap Tech": [
        "AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA", "NFLX",
    ],
    "Crypto / Fintech": [
        "COIN", "MSTR", "MARA", "RIOT", "CLSK", "HUT", "BITF",
    ],
    "REITs / Real Estate": [
        "AMT", "PLD", "EQIX", "DLR", "SPG", "O", "WELL", "PSA",
    ],
    "Transportation": [
        "UBER", "LYFT", "DAL", "UAL", "LUV", "FDX", "UPS", "ODFL", "XPO",
    ],
}

# Sectors considered "leading" right now — stocks in these get a sector bonus
LEADING_SECTORS = ["Semiconductors", "AI Infrastructure", "Financials"]

# ── Pre-filters (stocks that fail these are skipped before pattern detection) ──

PRE_FILTERS = {
    "min_price": 3.0,            # Price > $3 — no penny stocks
    "min_market_cap": 300e6,     # Market cap > 300M
    "min_avg_volume_10d": 500_000,  # 10-day avg volume > 500K shares
    "min_adr_pct": 2.0,         # Average Daily Range > 2% — stock moves enough to trade
    "min_change_pct": -2.0,     # Allow slightly red days — catch setups pulling back into support
    "price_above_ema21": True,  # Price must be above 21 EMA
    "price_above_ema50": True,  # Price must be above 50 EMA
}

# ── Data settings ───────────────────────────────────────────────────────────────

DAILY_PERIOD = "6mo"       # yfinance period for daily candles
WEEKLY_PERIOD = "2y"       # yfinance period for weekly candles
CACHE_TTL_HOURS = 4        # How long to cache downloaded data before re-fetching

# ── EMA periods ─────────────────────────────────────────────────────────────────

EMA_FAST = 9
EMA_MID = 21
EMA_SLOW = 50

# ── Pattern detection thresholds ────────────────────────────────────────────────

# Setup 1: Daily Tight Base
TIGHT_BASE = {
    "lookback_range": 20,           # Days to look back for percentile calc
    "tight_window": 5,              # Days to measure tightness
    "tight_percentile": 25,         # Daily range must be in bottom N percentile
    "close_stdev_pct": 1.5,         # Alt: stdev of closes < this % of price
    "vol_decline_ratio": 0.80,      # 5-day avg vol < this * 20-day avg vol
    "macd_hist_percentile": 30,     # MACD histogram in bottom N% of last 20 bars
    "breakout_vol_mult": 1.5,       # Breakout volume must be > this * 20-day avg
    "min_consol_days": 3,           # Minimum consolidation length
    "max_consol_days": 7,           # Maximum consolidation length
}

# Setup 2: Weekly Base / Horizontal Resistance
WEEKLY_BASE = {
    "resistance_lookback_weeks": 20,
    "resistance_cluster_pct": 2.0,  # Highs within this % are clustered
    "min_rejections": 2,            # Minimum touches at resistance
    "proximity_pct": 5.0,           # Price must be within this % of resistance
    "breakout_vol_mult": 1.5,       # Volume multiplier for breakout
}

# Setup 3: Descending Trendline Compression
TRENDLINE = {
    "swing_lookback": 60,           # Days to look back for swing points
    "min_swing_highs": 3,           # Minimum swing highs to fit trendline
    "support_cluster_pct": 3.0,     # Swing lows within this % are support
    "breakout_vol_mult": 1.5,
}

# Setup 4: Undercut & Rally
UNDERCUT = {
    "support_lookback": 30,         # Days to find support level
    "min_support_touches": 2,
    "support_cluster_pct": 2.0,
    "breakdown_window": 5,          # Must have broken below within last N days
    "recovery_candle_pct": 25,      # Close must be in upper N% of daily range
    "recovery_vol_mult": 1.3,
}

# ── Scoring weights ─────────────────────────────────────────────────────────────

SCORING = {
    # Pattern Quality (max 40)
    "tightness_max": 10,
    "consol_days_max": 10,
    "pattern_clean_max": 10,
    "resistance_clarity_max": 10,

    # Trend Alignment (max 30)
    "ema_stack_max": 10,
    "ema_rising_max": 10,
    "price_vs_ema_max": 10,

    # Momentum (max 20)
    "macd_max": 10,
    "volume_max": 10,

    # Sector Bonus (max 10)
    "leading_sector_max": 5,
    "relative_strength_max": 5,
}

# ── Display thresholds ──────────────────────────────────────────────────────────

SCORE_READY = 85
SCORE_WATCH = 70
SCORE_BUILDING = 50    # Below this → don't display

# ── Database ────────────────────────────────────────────────────────────────────

DB_PATH = "breakout_scanner.db"
