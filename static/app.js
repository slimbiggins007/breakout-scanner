/**
 * Breakout Scanner — Dashboard interactivity
 * Handles filtering, sorting, card expansion, and candlestick chart rendering.
 */

// ── Chart cache (don't re-fetch if already loaded) ─────────────────────────
const loadedCharts = new Set();

// ── Toggle card expand + load chart on first open ──────────────────────────
function toggleCard(el) {
    const card = el.closest(".card");
    const wasExpanded = card.classList.contains("expanded");
    card.classList.toggle("expanded");

    if (!wasExpanded) {
        const chartEl = card.querySelector(".chart-container");
        if (chartEl && !loadedCharts.has(chartEl.id)) {
            loadChart(card.dataset.ticker, chartEl);
            loadedCharts.add(chartEl.id);
        }
    }
}

// ── Helper: add a series (works with both v4 and v5 API) ───────────────────
function addSeries(chart, type, options) {
    // v5 API: chart.addSeries(LightweightCharts.CandlestickSeries, opts)
    // v4 API: chart.addCandlestickSeries(opts)
    const typeMap = {
        candlestick: "CandlestickSeries",
        histogram: "HistogramSeries",
        line: "LineSeries",
    };
    const v4Method = {
        candlestick: "addCandlestickSeries",
        histogram: "addHistogramSeries",
        line: "addLineSeries",
    };

    // Try v5 first
    if (typeof chart.addSeries === "function" && LightweightCharts[typeMap[type]]) {
        return chart.addSeries(LightweightCharts[typeMap[type]], options || {});
    }
    // Fall back to v4
    if (typeof chart[v4Method[type]] === "function") {
        return chart[v4Method[type]](options || {});
    }
    throw new Error("Cannot add series: " + type);
}

// ── Render candlestick chart with EMAs + volume ────────────────────────────
async function loadChart(ticker, container) {
    container.innerHTML = '<div class="chart-loading">Loading chart...</div>';

    try {
        if (typeof LightweightCharts === "undefined") {
            throw new Error("Chart library not loaded — check internet connection");
        }

        const resp = await fetch("/api/chart/" + encodeURIComponent(ticker));
        if (!resp.ok) throw new Error("API returned " + resp.status);
        const data = await resp.json();
        if (data.error) throw new Error(data.error);

        container.innerHTML = "";

        const chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 300,
            layout: {
                background: { color: "#06060c" },
                textColor: "#555570",
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 10,
            },
            grid: {
                vertLines: { color: "#0e0e1c" },
                horzLines: { color: "#0e0e1c" },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode
                    ? LightweightCharts.CrosshairMode.Normal
                    : 0,
                vertLine: { color: "#333350", width: 1, style: 2 },
                horzLine: { color: "#333350", width: 1, style: 2 },
            },
            rightPriceScale: {
                borderColor: "#1a1a2e",
                scaleMargins: { top: 0.05, bottom: 0.25 },
            },
            timeScale: {
                borderColor: "#1a1a2e",
                timeVisible: false,
            },
            handleScroll: true,
            handleScale: true,
        });

        // Candlestick series
        const candleSeries = addSeries(chart, "candlestick", {
            upColor: "#00ff87",
            downColor: "#ff6b6b",
            borderUpColor: "#00ff87",
            borderDownColor: "#ff6b6b",
            wickUpColor: "#00ff87",
            wickDownColor: "#ff6b6b",
        });
        candleSeries.setData(data.candles);

        // Volume as histogram
        const volumeSeries = addSeries(chart, "histogram", {
            priceFormat: { type: "volume" },
            priceScaleId: "volume",
        });
        volumeSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
        });
        volumeSeries.setData(data.volume);

        // EMA 9 — green
        if (data.ema9 && data.ema9.length) {
            const ema9 = addSeries(chart, "line", {
                color: "#00ff87",
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
            });
            ema9.setData(data.ema9);
        }

        // EMA 21 — yellow
        if (data.ema21 && data.ema21.length) {
            const ema21 = addSeries(chart, "line", {
                color: "#ffcc00",
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
            });
            ema21.setData(data.ema21);
        }

        // EMA 50 — blue
        if (data.ema50 && data.ema50.length) {
            const ema50 = addSeries(chart, "line", {
                color: "#4a9eff",
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
            });
            ema50.setData(data.ema50);
        }

        // Fit content
        chart.timeScale().fitContent();

        // Resize observer so chart fills card properly
        const ro = new ResizeObserver(() => {
            chart.applyOptions({ width: container.clientWidth });
        });
        ro.observe(container);

    } catch (err) {
        console.error("Chart error for " + ticker + ":", err);
        container.innerHTML =
            '<div class="chart-loading">Failed to load chart: ' + err.message + '</div>';
    }
}

// ── Filtering ──────────────────────────────────────────────────────────────

(function () {
    "use strict";

    const state = {
        status: "all",
        sector: "all",
        type: "all",
    };

    function applyFilters() {
        const cards = document.querySelectorAll(".card");
        cards.forEach((card) => {
            const matchStatus =
                state.status === "all" || card.dataset.status === state.status;
            const matchSector =
                state.sector === "all" || card.dataset.sector === state.sector;
            const matchType =
                state.type === "all" || card.dataset.type === state.type;

            if (matchStatus && matchSector && matchType) {
                card.classList.remove("hidden");
            } else {
                card.classList.add("hidden");
            }
        });
    }

    function setupFilterGroup(containerId, stateKey) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const buttons = container.querySelectorAll(".filter-btn");
        buttons.forEach((btn) => {
            btn.addEventListener("click", () => {
                buttons.forEach((b) => b.classList.remove("active"));
                btn.classList.add("active");
                state[stateKey] = btn.dataset.filter;
                applyFilters();
            });
        });
    }

    setupFilterGroup("status-filters", "status");
    setupFilterGroup("sector-filters", "sector");
    setupFilterGroup("type-filters", "type");

    // Date selector
    const dateSelect = document.getElementById("date-select");
    if (dateSelect) {
        dateSelect.addEventListener("change", () => {
            window.location.href = "/?date=" + encodeURIComponent(dateSelect.value);
        });
    }

    // Sort cards by score descending
    const grid = document.getElementById("results-grid");
    if (grid) {
        const cards = Array.from(grid.querySelectorAll(".card"));
        cards.sort((a, b) => (parseInt(b.dataset.score) || 0) - (parseInt(a.dataset.score) || 0));
        cards.forEach((card) => grid.appendChild(card));
    }
})();
