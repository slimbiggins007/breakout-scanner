"""
Web dashboard — FastAPI app serving the breakout scanner results.
Run: uvicorn app:app --reload --port 8000
"""

import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import data as data_mod
from indicators import add_all_indicators
from db import init_db, get_latest_scan, get_scan_by_date, get_scan_dates, get_stats
from scanner import run_scan

app = FastAPI(title="Breakout Scanner")

BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

# Initialize DB on startup
init_db()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, date: str | None = None):
    """Render the main dashboard page."""
    if date:
        results = get_scan_by_date(date)
    else:
        results = get_latest_scan()

    stats = get_stats()
    scan_dates = get_scan_dates()

    # Get unique sectors and setup types for filters
    sectors = sorted(set(r["sector"] for r in results))
    setup_types = sorted(set(r["setup_type"] for r in results))

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "results": results,
        "stats": stats,
        "scan_dates": scan_dates,
        "selected_date": date or (scan_dates[0] if scan_dates else ""),
        "sectors": sectors,
        "setup_types": setup_types,
        "config": config,
        "now": datetime.now(),
    })


@app.get("/api/results")
async def api_results(date: str | None = None):
    """JSON API endpoint for scan results."""
    if date:
        results = get_scan_by_date(date)
    else:
        results = get_latest_scan()
    return JSONResponse(content=results)


@app.get("/api/stats")
async def api_stats():
    """JSON API endpoint for scan stats."""
    return JSONResponse(content=get_stats())


@app.get("/api/chart/{ticker}")
async def api_chart(ticker: str):
    """
    Return OHLCV + EMA data for a ticker as JSON arrays
    for the lightweight-charts candlestick view.
    """
    df = data_mod.fetch_daily(ticker)
    if df is None or df.empty:
        return JSONResponse(content={"error": "No data"}, status_code=404)

    df = add_all_indicators(df)

    # Build candlestick series — lightweight-charts expects {time, open, high, low, close}
    candles = []
    volume_bars = []
    ema9 = []
    ema21 = []
    ema50 = []

    for ts, row in df.iterrows():
        t = ts.strftime("%Y-%m-%d")
        candles.append({
            "time": t,
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
        })
        # Volume bar color: green if close >= open, red otherwise
        color = "rgba(0,255,135,0.3)" if row["Close"] >= row["Open"] else "rgba(255,107,107,0.3)"
        volume_bars.append({
            "time": t,
            "value": int(row["Volume"]),
            "color": color,
        })
        if not pd.isna(row.get(f"EMA_{config.EMA_FAST}")):
            ema9.append({"time": t, "value": round(float(row[f"EMA_{config.EMA_FAST}"]), 2)})
        if not pd.isna(row.get(f"EMA_{config.EMA_MID}")):
            ema21.append({"time": t, "value": round(float(row[f"EMA_{config.EMA_MID}"]), 2)})
        if not pd.isna(row.get(f"EMA_{config.EMA_SLOW}")):
            ema50.append({"time": t, "value": round(float(row[f"EMA_{config.EMA_SLOW}"]), 2)})

    return JSONResponse(content={
        "candles": candles,
        "volume": volume_bars,
        "ema9": ema9,
        "ema21": ema21,
        "ema50": ema50,
    })


@app.post("/api/scan")
async def api_run_scan(
    setup_type: int | None = Query(None),
    sector: str | None = Query(None),
    min_score: int = Query(config.SCORE_BUILDING),
):
    """Trigger a new scan and return results."""
    setup_types = [setup_type] if setup_type else None
    start = time.time()
    results = run_scan(setup_types=setup_types, sector_filter=sector, min_score=min_score)
    elapsed = time.time() - start
    return JSONResponse(content={
        "results": results,
        "elapsed": round(elapsed, 1),
        "count": len(results),
    })
