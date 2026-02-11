# Breakout Scanner

Stock breakout scanner that detects momentum setups across 84 tickers nightly. CLI + web dashboard with candlestick charts.

## Install

```bash
cd ~/breakout-scanner
pip install -r requirements.txt
```

## Run

```bash
# scan everything
python3 scanner.py

# scan one setup type (1=tight base, 2=weekly base, 3=trendline, 4=undercut)
python3 scanner.py --type 1

# scan one sector
python3 scanner.py --sector Semiconductors

# only show scores 70+
python3 scanner.py --min-score 70

# force fresh data (ignores 4hr cache)
python3 scanner.py --clear-cache

# combine flags
python3 scanner.py --type 1 --sector "AI Infrastructure" --min-score 70
```

## Web Dashboard

```bash
python3 -m uvicorn app:app --port 8000
```

Open http://localhost:8000. Click "Chart + Details" on any card to see the candlestick chart with EMA 9/21/50 overlays and volume.

Run `python3 scanner.py` first so there's data to display.

## Automate (optional)

Run after market close every weekday via cron:

```
0 17 * * 1-5 cd ~/breakout-scanner && python3 scanner.py
```

## Configure

Edit `config.py`:

- `WATCHLIST` — add/remove tickers by sector
- `LEADING_SECTORS` — which sectors get bonus scoring
- `SCORE_READY` / `SCORE_WATCH` / `SCORE_BUILDING` — score thresholds
- `TIGHT_BASE`, `WEEKLY_BASE`, `TRENDLINE`, `UNDERCUT` — pattern detection sensitivity
- `SCORING` — point weights for each scoring component

## Setup Types

| # | Name | What it finds |
|---|------|---------------|
| 1 | Daily Tight Base | 3-7 day consolidation near highs, EMAs stacked, volume drying up |
| 2 | Weekly Base Breakout | Multi-week base under horizontal resistance, weekly EMAs crossing |
| 3 | Trendline Compression | Descending highs + horizontal support converging into a wedge |
| 4 | Undercut & Rally | False breakdown below support, then recovery back above on volume |

## Scoring (0-100)

- **Pattern Quality** (40 pts) — tightness, consolidation length, cleanliness, resistance clarity
- **Trend Alignment** (30 pts) — EMA stack order, all rising, price above EMAs
- **Momentum** (20 pts) — MACD histogram curl, volume pattern
- **Sector Bonus** (10 pts) — leading sector, relative strength vs SPY

| Score | Status | Meaning |
|-------|--------|---------|
| 85-100 | READY | All criteria met, breakout imminent or triggered |
| 70-84 | WATCH | Most criteria met, waiting on final trigger |
| 50-69 | BUILDING | Pattern forming, not yet mature |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web dashboard |
| GET | `/api/results` | JSON scan results (optional `?date=YYYY-MM-DD`) |
| GET | `/api/chart/{ticker}` | OHLCV + EMA data for charting |
| GET | `/api/stats` | Aggregate scan stats |
| POST | `/api/scan` | Trigger a new scan |
