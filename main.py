import logging
import statistics
import math
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import SessionLocal, engine, Base
from models import TradeLogDB, TelemetryDB
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn")

Base.metadata.create_all(bind=engine)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- QUANT FUNCTIONS ---


def calculate_hurst(ts):
    """
    Estimates Hurst Exponent (H) for a time series.
    H < 0.5: Mean Reverting (Safe)
    H ~ 0.5: Random Walk
    H > 0.5: Persistent (Trend/Dangerous behavior in latency)
    """
    if len(ts) < 20:
        return 0.5  # Not enough data

    lags = range(2, min(20, len(ts)//2))
    tau = [np.std(np.subtract(ts[lag:], ts[:-lag])) for lag in lags]

    # Avoid log(0) errors
    tau = [t if t > 0 else 1e-6 for t in tau]

    # Slope of log-log plot
    poly = np.polyfit(np.log(lags), np.log(tau), 1)
    return poly[0] * 2.0  # H approximation


# --- DASHBOARD HTML (With Heatmap & Math) ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PnL Risk Engine</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #0b0e14; color: #e2e8f0; font-family: 'Inter', sans-serif; }
        .card { background: #151b28; border: 1px solid #2d3748; }
        .metric-val { font-family: 'JetBrains Mono', monospace; }
        .heatmap-cell { width: 100%; height: 20px; border-radius: 2px; }
    </style>
</head>
<body class="p-6">
    <div class="max-w-6xl mx-auto">
        <header class="flex justify-between items-center mb-8">
            <div>
                <h1 class="text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-indigo-400">
                    PnL Risk Engine
                </h1>
                <p class="text-sm text-gray-500 mt-1">Institutional Execution Analytics</p>
            </div>
            <div class="text-right">
                <div class="text-xs text-gray-500 uppercase tracking-wider">System Status</div>
                <div class="text-green-400 font-bold flex items-center gap-2 justify-end">
                    <span class="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span> ONLINE
                </div>
            </div>
        </header>

        <div class="card rounded-xl p-6 mb-8">
            <h2 class="text-sm font-bold text-gray-400 uppercase mb-4 tracking-wider">Liquidity Hole Heatmap (Real-time)</h2>
            <div id="heatmapGrid" class="space-y-2">
                </div>
        </div>

        <div id="riskCards" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            </div>

    </div>

    <script>
        function getRiskColor(score) {
            if(score > 70) return 'text-red-500';
            if(score > 40) return 'text-yellow-500';
            return 'text-green-500';
        }

        function getHurstLabel(h) {
            if(h > 0.6) return {text: "PERSISTENT (RISK)", color: "text-red-400"};
            if(h < 0.4) return {text: "MEAN REVERTING", color: "text-green-400"};
            return {text: "RANDOM WALK", color: "text-gray-400"};
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/v1/global_status');
                const data = await res.json();
                
                // 1. Update Heatmap
                const heatmap = document.getElementById('heatmapGrid');
                heatmap.innerHTML = '';
                
                data.forEach(broker => {
                    // Create row
                    const row = document.createElement('div');
                    row.className = 'flex items-center gap-4';
                    
                    // Label
                    const label = document.createElement('div');
                    label.className = 'w-24 text-xs font-bold text-gray-400 uppercase text-right';
                    label.innerText = broker.broker;
                    
                    // Cells (We visualize the history array)
                    const cellsContainer = document.createElement('div');
                    cellsContainer.className = 'flex-1 flex gap-1';
                    
                    broker.history.slice(-30).forEach(lat => {
                        const cell = document.createElement('div');
                        cell.className = 'flex-1 h-6 rounded-sm transition-all';
                        
                        // Heatmap Color Logic
                        if(lat < 50) cell.style.backgroundColor = '#10b981'; // Green
                        else if(lat < 150) cell.style.backgroundColor = '#f59e0b'; // Yellow
                        else if(lat < 500) cell.style.backgroundColor = '#ef4444'; // Red
                        else cell.style.backgroundColor = '#7f1d1d'; // Dark Red (Death Spiral)
                        
                        cellsContainer.appendChild(cell);
                    });
                    
                    row.appendChild(label);
                    row.appendChild(cellsContainer);
                    heatmap.appendChild(row);
                });

                // 2. Update Cards
                const cards = document.getElementById('riskCards');
                cards.innerHTML = '';
                
                data.forEach(b => {
                    const hurstInfo = getHurstLabel(b.hurst);
                    
                    const html = `
                    <div class="card rounded-xl p-5 hover:border-blue-500/50 transition">
                        <div class="flex justify-between items-start mb-4">
                            <div>
                                <h3 class="text-xl font-bold text-white capitalize">${b.broker}</h3>
                                <div class="text-xs ${hurstInfo.color} font-bold mt-1 tracking-wide border border-gray-700 inline-block px-2 py-0.5 rounded">H=${b.hurst.toFixed(2)}: ${hurstInfo.text}</div>
                            </div>
                            <div class="text-right">
                                <div class="text-2xl font-black metric-val ${b.p99 > 300 ? 'text-red-500' : 'text-gray-200'}">${b.p99}ms</div>
                                <div class="text-[10px] text-gray-500 uppercase">P99 Latency</div>
                            </div>
                        </div>

                        <div class="grid grid-cols-2 gap-4 mt-6 border-t border-gray-800 pt-4">
                            <div>
                                <div class="text-[10px] text-gray-500 uppercase font-bold">Jitter (σ)</div>
                                <div class="text-sm font-mono text-gray-300">±${b.jitter}ms</div>
                            </div>
                            <div>
                                <div class="text-[10px] text-gray-500 uppercase font-bold">Systemic Corr</div>
                                <div class="text-sm font-mono text-blue-300">${(b.correlation * 100).toFixed(0)}%</div>
                            </div>
                        </div>
                    </div>
                    `;
                    cards.innerHTML += html;
                });

            } catch(e) { console.error(e); }
        }

        setInterval(updateDashboard, 2000);
        updateDashboard();
    </script>
</body>
</html>
"""

# --- DEPENDENCIES ---


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def verify_key(x_pro_key: str = Header(None)):
    if not x_pro_key or not x_pro_key.startswith("sk_"):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_pro_key.split('_')[-1]

# --- MODELS ---


class TradeLog(BaseModel):
    symbol: str
    side: str
    qty: float
    broker: str
    latency_ms: int
    slippage: float
    status: str


class TelemetryPayload(BaseModel):
    broker: str
    latency_ms: int
    slippage: float
    status: str

# --- ENDPOINTS ---


@app.get("/", response_class=HTMLResponse)
# Set dashboard as ROOT for easy access
async def root(): return DASHBOARD_HTML


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(): return DASHBOARD_HTML


@app.post("/v1/telemetry")
async def submit_telemetry(payload: TelemetryPayload, db: Session = Depends(get_db)):
    try:
        new_ping = TelemetryDB(
            broker=payload.broker.lower(),
            latency_ms=payload.latency_ms,
            slippage=payload.slippage,
            status=payload.status
        )
        db.add(new_ping)
        db.commit()
        return {"status": "ok"}
    except:
        return {"status": "error"}


@app.get("/v1/global_status")
async def get_global_map(db: Session = Depends(get_db)):
    # 1. Fetch recent data (last 2 minutes is enough for "Live" view)
    since = datetime.utcnow() - timedelta(minutes=2)
    raw = db.query(TelemetryDB).filter(TelemetryDB.timestamp >= since).all()

    # 2. Group by Broker
    data = {}
    for r in raw:
        if r.broker not in data:
            data[r.broker] = []
        data[r.broker].append(r.latency_ms)

    # 3. Calculate Global Average (for Correlation)
    all_latencies = [r.latency_ms for r in raw]
    global_avg = statistics.mean(all_latencies) if all_latencies else 0

    results = []
    for broker, lats in data.items():
        if len(lats) < 5:
            continue

        # A. Hurst Exponent
        hurst = calculate_hurst(lats)

        # B. Risk Metrics
        p99 = np.percentile(lats, 99)
        jitter = np.std(lats)

        # C. "Systemic Correlation" (Simple Proxy)
        # Does this broker deviate from the global average?
        # If correlation is high, they are systemic.
        # (Simplified to relative strength for performance)
        avg = statistics.mean(lats)
        correlation = min(1.0, avg / (global_avg + 1))

        results.append({
            "broker": broker,
            "p99": int(p99),
            "jitter": int(jitter),
            "hurst": hurst,
            "correlation": correlation,
            "history": lats[-30:]  # Send last 30 points for Heatmap
        })

    return sorted(results, key=lambda x: x['p99'])
