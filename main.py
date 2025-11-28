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
import hashlib
from models import ApiKeyDB

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
    <link rel="manifest" href="/public/manifest.json">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0b0e14; color: #e2e8f0; font-family: 'Inter', sans-serif; }
        .card { background: #151b28; border: 1px solid #2d3748; }
        .metric-val { font-family: 'Courier New', monospace; }
        .h-cell { flex: 1; height: 24px; border-radius: 2px; margin: 0 1px; }
        .bg-safe { background-color: #10b981; opacity: 0.8; }
        .bg-warn { background-color: #f59e0b; }
        .bg-danger { background-color: #ef4444; }
        .bg-fatal { background-color: #7f1d1d; }
    </style>
</head>
<body class="p-4 md:p-8">
    <div class="max-w-6xl mx-auto">
        <header class="flex justify-between items-center mb-8">
            <div>
                <h1 class="text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-indigo-400">
                    PnL Risk Engine
                </h1>
                <p class="text-sm text-gray-500 mt-1">Institutional Execution Analytics</p>
            </div>
            
            <div class="flex items-center gap-4">
                <button id="installBtn" class="hidden bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold px-4 py-2 rounded-full transition flex items-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                    INSTALL APP
                </button>
                <div class="text-right">
                    <div class="text-xs text-gray-500 uppercase tracking-wider">System Status</div>
                    <div class="text-green-400 font-bold flex items-center gap-2 justify-end">
                        <span class="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span> ONLINE
                    </div>
                </div>
            </div>
        </header>

        <div class="card rounded-xl p-6 mb-8">
            <h2 class="text-xs font-bold text-gray-500 uppercase mb-4 tracking-wider">Liquidity Hole Heatmap (Real-time Sonar)</h2>
            <div id="heatmapGrid" class="space-y-3"></div>
        </div>
        <div id="riskCards" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
    </div>

    <script>
        // --- 1. PWA INSTALL LOGIC ---
        let deferredPrompt;
        const installBtn = document.getElementById('installBtn');

        window.addEventListener('beforeinstallprompt', (e) => {
            // Prevent Chrome 67 and earlier from automatically showing the prompt
            e.preventDefault();
            // Stash the event so it can be triggered later.
            deferredPrompt = e;
            // Update UI to notify the user they can add to home screen
            installBtn.classList.remove('hidden');
        });

        installBtn.addEventListener('click', (e) => {
            // Hide the app provided install promotion
            installBtn.classList.add('hidden');
            // Show the install prompt
            deferredPrompt.prompt();
            // Wait for the user to respond to the prompt
            deferredPrompt.userChoice.then((choiceResult) => {
                if (choiceResult.outcome === 'accepted') {
                    console.log('User accepted the A2HS prompt');
                }
                deferredPrompt = null;
            });
        });

        // --- 2. EXISTING DASHBOARD LOGIC ---
        function getHurstLabel(h) {
            if(h > 0.6) return {text: "PERSISTENT (RISK)", color: "text-red-400", border: "border-red-900"};
            if(h < 0.4) return {text: "MEAN REVERTING", color: "text-green-400", border: "border-green-900"};
            return {text: "RANDOM WALK", color: "text-gray-400", border: "border-gray-700"};
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/v1/global_status');
                const data = await res.json();
                
                // Update Heatmap
                const heatmap = document.getElementById('heatmapGrid');
                heatmap.innerHTML = '';
                
                data.forEach(broker => {
                    const row = document.createElement('div');
                    row.className = 'flex items-center gap-4';
                    
                    const label = document.createElement('div');
                    label.className = 'w-24 text-xs font-bold text-gray-400 uppercase text-right';
                    label.innerText = broker.broker;
                    
                    const cellsContainer = document.createElement('div');
                    cellsContainer.className = 'flex-1 flex';
                    
                    broker.history.slice(-40).forEach(lat => {
                        const cell = document.createElement('div');
                        cell.className = 'h-cell transition-all';
                        if(lat < 50) cell.classList.add('bg-safe');
                        else if(lat < 150) cell.classList.add('bg-warn');
                        else if(lat < 500) cell.classList.add('bg-danger');
                        else cell.classList.add('bg-fatal');
                        cellsContainer.appendChild(cell);
                    });
                    
                    row.appendChild(label);
                    row.appendChild(cellsContainer);
                    heatmap.appendChild(row);
                });

                // Update Risk Cards
                const cards = document.getElementById('riskCards');
                cards.innerHTML = '';
                
                data.forEach(b => {
                    const hurstInfo = getHurstLabel(b.hurst);
                    const html = `
                    <div class="card rounded-xl p-5 hover:border-blue-500/50 transition">
                        <div class="flex justify-between items-start mb-4">
                            <div>
                                <h3 class="text-xl font-bold text-white capitalize flex items-center gap-2">
                                    ${b.broker}
                                </h3>
                                <div class="text-[10px] ${hurstInfo.color} font-bold mt-2 tracking-wide border ${hurstInfo.border} inline-block px-2 py-0.5 rounded">
                                    H=${b.hurst.toFixed(2)}: ${hurstInfo.text}
                                </div>
                            </div>
                            <div class="text-right">
                                <div class="text-3xl font-black metric-val ${b.p99 > 300 ? 'text-red-500' : 'text-gray-200'}">${b.p99}</div>
                                <div class="text-[10px] text-gray-500 uppercase mt-1">P99 Latency (ms)</div>
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-4 mt-6 border-t border-gray-800 pt-4">
                            <div>
                                <div class="text-[10px] text-gray-500 uppercase font-bold">Stability (Jitter)</div>
                                <div class="text-sm font-mono text-gray-300">±${b.jitter}ms</div>
                            </div>
                            <div>
                                <div class="text-[10px] text-gray-500 uppercase font-bold">Systemic Corr</div>
                                <div class="text-sm font-mono text-blue-300">${(b.correlation * 100).toFixed(0)}%</div>
                            </div>
                        </div>
                    </div>`;
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


async def verify_key(x_pro_key: str = Header(None), db: Session = Depends(get_db)):
    if not x_pro_key or not x_pro_key.startswith("sk_"):
        raise HTTPException(
            status_code=401, detail="Missing or Invalid API Key Format")

    # 1. Hash the incoming key
    incoming_hash = hashlib.sha256(x_pro_key.encode()).hexdigest()

    # 2. Check DB for existence
    key_record = db.query(ApiKeyDB).filter(
        ApiKeyDB.key_hash == incoming_hash).first()

    if not key_record:
        raise HTTPException(status_code=403, detail="Invalid API Key")

    if not key_record.is_active:
        raise HTTPException(status_code=403, detail="API Key Revoked")

    # Return the real User ID linked to this key
    return key_record.user_id

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

# --- ORACLE ROUTING ENGINE (The "Waze" Logic) ---


class RoutingRequest(BaseModel):
    symbol: str
    size: float
    # "normal" or "high" (High urgency ignores risk for speed)
    urgency: str = "normal"


@app.post("/v1/oracle/route")
async def get_smart_route(req: RoutingRequest, user_id: str = Depends(verify_key), db: Session = Depends(get_db)):
    """
    The 'Waze' API: Tells the bot exactly where to route the trade.
    Monetization: Only available to Pro Users (valid API Key).
    """
    # 1. Get Live Data (Last 2 minutes)
    since = datetime.utcnow() - timedelta(minutes=2)
    raw = db.query(TelemetryDB).filter(TelemetryDB.timestamp >= since).all()

    # 2. Group & Analyze
    candidates = {}
    for r in raw:
        if r.broker not in candidates:
            candidates[r.broker] = []
        candidates[r.broker].append(r.latency_ms)

    scored_brokers = []

    for broker, lats in candidates.items():
        if len(lats) < 3:
            continue  # Not enough data to trust

        # Calculate Metrics
        avg_lat = statistics.mean(lats)
        jitter = np.std(lats)
        hurst = calculate_hurst(lats)
        p99 = np.percentile(lats, 99)

        # 3. The Scoring Algorithm
        # Lower score is better.
        score = avg_lat + (jitter * 2)

        # PENALTIES
        risk_flags = []

        # A. Non-Ergodic Penalty (Hurst > 0.5 means "Cluster Risk")
        if hurst > 0.6:
            score += 200
            risk_flags.append("Unstable (High Hurst)")

        # B. Fat Tail Penalty
        if p99 > (avg_lat * 3):
            score += 100
            risk_flags.append("Fat Tail Risk")

        # C. Urgency Logic
        # If urgency is HIGH, we forgive Jitter but punish pure Latency
        if req.urgency == "high":
            score = avg_lat  # Pure speed

        scored_brokers.append({
            "broker": broker,
            "score": int(score),
            "latency_ms": int(avg_lat),
            "risk_flags": risk_flags
        })

    # 4. Sort by Best Score
    scored_brokers.sort(key=lambda x: x['score'])

    if not scored_brokers:
        return {"status": "no_data", "recommendation": None}

    best = scored_brokers[0]

    # 5. The Recommendation
    return {
        "status": "optimized",
        "recommendation": best["broker"],
        "metrics": {
            "expected_latency": best["latency_ms"],
            "risk_factors": best["risk_flags"]
        },
        "alternatives": scored_brokers[1:3]
    }
