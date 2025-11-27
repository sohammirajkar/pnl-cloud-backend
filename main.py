import logging
import statistics
import math
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import SessionLocal, engine, Base
from models import TradeLogDB, TelemetryDB
from datetime import datetime, timedelta

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn")

# Initialize Database
Base.metadata.create_all(bind=engine)

app = FastAPI()

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# --- DATA MODELS ---


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


# --- RISK-AWARE DASHBOARD HTML ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Global Execution Risk Monitor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #020617; color: #e2e8f0; font-family: 'Inter', sans-serif; }
        .rank-1 { border-left: 4px solid #22c55e; background: linear-gradient(90deg, #14532d 0%, #1e293b 100%); }
        .rank-danger { border-left: 4px solid #ef4444; background: linear-gradient(90deg, #450a0a 0%, #1e293b 100%); }
        .metric-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; }
        .risk-badge { font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
        .glitch { animation: glitch 1s linear infinite; }
        @keyframes glitch {
            2%, 64% { transform: translate(2px,0) skew(0deg); }
            4%, 60% { transform: translate(-2px,0) skew(0deg); }
            62% { transform: translate(0,0) skew(5deg); }
        }
    </style>
</head>
<body class="p-4 md:p-8">
    <div class="max-w-5xl mx-auto">
        <div class="text-center mb-10">
            <h1 class="text-4xl md:text-5xl font-black text-white mb-2 tracking-tight">
                <span class="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400">PnL Watchdog</span> Risk Map
            </h1>
            <p class="text-lg text-gray-400">Monitoring <span id="activeNodes" class="text-white font-bold">--</span> nodes for Fat Tail events.</p>
            
            <div class="mt-6 flex justify-center gap-4">
                <a href="https://github.com/sohammirajkar/pnl-cloud-backend" target="_blank" class="bg-slate-800 border border-slate-700 hover:border-blue-500 text-white px-4 py-2 rounded-lg text-sm font-semibold transition">
                    View Source
                </a>
                <div class="bg-blue-600/20 border border-blue-500/50 text-blue-200 px-4 py-2 rounded-lg text-sm">
                    pip install pnl-watchdog==0.3.2
                </div>
            </div>
        </div>

        <div class="flex justify-center gap-6 mb-6 text-xs text-gray-500">
            <div class="flex items-center gap-2">
                <div class="w-3 h-3 bg-green-500 rounded-full"></div> Ergodic (Safe)
            </div>
            <div class="flex items-center gap-2">
                <div class="w-3 h-3 bg-red-500 rounded-full"></div> Non-Ergodic (Fat Tail Risk)
            </div>
        </div>

        <div class="space-y-4" id="leaderboard">
            <div class="text-center text-gray-500 animate-pulse mt-10">Calculating Risk Metrics...</div>
        </div>
    </div>

    <script>
        async function loadLeaderboard() {
            try {
                const res = await fetch('/v1/global_status');
                const data = await res.json();
                
                const container = document.getElementById('leaderboard');
                container.innerHTML = '';
                let totalNodes = 0;

                data.forEach((row, index) => {
                    totalNodes += row.volume;
                    const isSafe = row.risk_score < 30;
                    const isDangerous = row.risk_score > 70;
                    
                    // Determine CSS class
                    let cardClass = "bg-slate-800 border-slate-700";
                    if (index === 0 && isSafe) cardClass = "rank-1 shadow-lg shadow-green-900/20 border-green-800";
                    if (isDangerous) cardClass = "rank-danger border-red-900";

                    const html = `
                        <div class="p-5 rounded-lg border ${cardClass} transition hover:scale-[1.01]">
                            <div class="flex flex-col md:flex-row items-center justify-between gap-4">
                                <div class="flex items-center gap-4 w-full md:w-1/3">
                                    <div class="text-xl font-bold text-slate-600">#${index + 1}</div>
                                    <div>
                                        <h3 class="text-xl font-bold text-white capitalize flex items-center gap-2">
                                            ${row.broker}
                                            ${isDangerous ? '<span class="risk-badge bg-red-900 text-red-200">FAT TAIL RISK</span>' : ''}
                                            ${index === 0 ? '<span class="risk-badge bg-green-900 text-green-200">BEST EXECUTION</span>' : ''}
                                        </h3>
                                        <div class="text-xs text-gray-400 mt-1">Based on ${row.volume} recent trades</div>
                                    </div>
                                </div>

                                <div class="grid grid-cols-4 gap-4 w-full md:w-2/3">
                                    
                                    <div class="text-center">
                                        <div class="metric-label">Avg Speed</div>
                                        <div class="text-lg font-mono text-white">${row.avg_lat}ms</div>
                                    </div>

                                    <div class="text-center border-l border-slate-700">
                                        <div class="metric-label text-yellow-500 font-bold">P99 (Tail)</div>
                                        <div class="text-lg font-mono ${row.p99_lat > 200 ? 'text-red-400 font-bold' : 'text-yellow-200'}">
                                            ${row.p99_lat}ms
                                        </div>
                                    </div>

                                    <div class="text-center border-l border-slate-700">
                                        <div class="metric-label">Jitter (σ)</div>
                                        <div class="text-lg font-mono text-gray-300">±${row.jitter}ms</div>
                                    </div>

                                    <div class="text-center border-l border-slate-700">
                                        <div class="metric-label">Slippage</div>
                                        <div class="text-lg font-mono ${row.avg_slip > 0.01 ? 'text-red-400' : 'text-emerald-400'}">
                                            ${row.avg_slip}%
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                    container.innerHTML += html;
                });
                document.getElementById('activeNodes').innerText = totalNodes;
            } catch (err) {
                console.error("Failed to load map", err);
            }
        }
        loadLeaderboard();
        setInterval(loadLeaderboard, 3000);
    </script>
</body>
</html>
"""

# --- ENDPOINTS ---


@app.get("/")
async def root():
    return {"status": "online", "service": "PnL Risk Oracle"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


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
        return {"status": "contributed"}
    except Exception as e:
        logger.error(f"Error saving telemetry: {e}")
        raise HTTPException(status_code=500, detail="Database error")

# --- THE RISK ENGINE (Advanced Math) ---


@app.get("/v1/global_status")
async def get_global_map(db: Session = Depends(get_db)):
    """
    Calculates P99 (Tail Risk), Jitter (StdDev), and Average.
    """
    # 1. Fetch RAW data from last 5 minutes (needed for P99/StdDev calc)
    five_mins_ago = datetime.utcnow() - timedelta(minutes=5)

    # We fetch raw rows instead of SQL aggregation to perform P99 math in Python
    # (More flexible for 'Fat Tail' detection)
    raw_data = db.query(TelemetryDB).filter(
        TelemetryDB.timestamp >= five_mins_ago).all()

    # 2. Group by Broker
    broker_stats = {}
    for row in raw_data:
        if row.broker not in broker_stats:
            broker_stats[row.broker] = {"lats": [], "slips": []}
        broker_stats[row.broker]["lats"].append(row.latency_ms)
        broker_stats[row.broker]["slips"].append(row.slippage)

    leaderboard = []

    # 3. Calculate Risk Metrics
    for broker, data in broker_stats.items():
        lats = data["lats"]
        slips = data["slips"]

        count = len(lats)
        if count < 2:
            continue  # Need at least 2 points for stats

        # A. Basic Stats
        avg_lat = statistics.mean(lats)
        avg_slip = statistics.mean(slips)

        # B. Jitter (Standard Deviation) - "How unstable is it?"
        jitter = statistics.stdev(lats) if count > 1 else 0

        # C. P99 (Tail Risk) - "What is the worst 1% case?"
        lats.sort()
        p99_index = int(count * 0.99)
        p99_lat = lats[min(p99_index, count - 1)]

        # D. Risk Score Algorithm (Power Law Detection)
        # If P99 is > 3x the Average, it's a Fat Tail event.
        fat_tail_ratio = p99_lat / (avg_lat + 1)  # +1 to avoid div by zero

        # Base score (Lower is better)
        risk_score = (avg_lat * 0.4) + (jitter * 0.3) + \
            (p99_lat * 0.3) + (avg_slip * 5000)

        # Penalty for Fat Tails
        if fat_tail_ratio > 3.0:
            risk_score += 50  # Massive penalty for non-ergodic behavior

        leaderboard.append({
            "broker": broker,
            "avg_lat": int(avg_lat),
            "p99_lat": int(p99_lat),
            "jitter": int(jitter),
            "avg_slip": float(f"{avg_slip:.5f}"),
            "volume": count,
            "risk_score": int(risk_score)
        })

    # Sort by Risk Score (Lowest Risk First)
    return sorted(leaderboard, key=lambda x: x['risk_score'])

# --- PRO ENDPOINTS ---


@app.get("/v1/logs")
async def get_logs(user_id: str = Depends(verify_key), limit: int = 50, db: Session = Depends(get_db)):
    return db.query(TradeLogDB).filter(TradeLogDB.user_id == user_id).order_by(TradeLogDB.timestamp.desc()).limit(limit).all()


@app.post("/v1/log_trade")
async def log_trade(log: TradeLog, user_id: str = Depends(verify_key), db: Session = Depends(get_db)):
    new_log = TradeLogDB(user_id=user_id, **log.dict())
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    return {"success": True, "log_id": new_log.id}
