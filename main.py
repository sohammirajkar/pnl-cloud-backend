import logging
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse  # <--- NEW
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


# --- DASHBOARD HTML (EMBEDDED) ---
# This bypasses all file system errors
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Global Algo Execution Leaderboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #020617; color: #e2e8f0; font-family: 'Inter', sans-serif; }
        .rank-1 { border-left: 4px solid #22c55e; background: linear-gradient(90deg, #14532d 0%, #1e293b 100%); }
        .rank-low { border-left: 4px solid #ef4444; }
    </style>
</head>
<body class="p-8">
    <div class="max-w-4xl mx-auto">
        <div class="text-center mb-10">
            <h1 class="text-5xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400 mb-4">
                Global Execution Monitor
            </h1>
            <p class="text-xl text-gray-400">Real-time latency & slippage data from <span id="activeNodes" class="text-white font-bold">--</span> active algo traders.</p>
            <div class="mt-6">
                <a href="https://github.com/yourusername/pnl-watchdog" class="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-lg font-bold transition">
                    Join the Network (Install Library)
                </a>
            </div>
        </div>
        <div class="space-y-4" id="leaderboard">
            <div class="text-center text-gray-500 animate-pulse">Scanning Global Network...</div>
        </div>
    </div>
    <script>
        async function loadLeaderboard() {
            // Point to the relative API endpoint
            const res = await fetch('/v1/global_status');
            const data = await res.json();
            
            const container = document.getElementById('leaderboard');
            container.innerHTML = '';
            let totalNodes = 0;

            data.forEach((row, index) => {
                totalNodes += row.volume;
                const isTop = index === 0;
                const isLow = row.score < 50;
                
                const html = `
                    <div class="p-6 rounded-lg flex items-center justify-between bg-slate-800 border border-slate-700 ${isTop ? 'rank-1 shadow-lg shadow-green-900/20' : ''} ${isLow ? 'rank-low' : ''}">
                        <div class="flex items-center gap-4">
                            <div class="text-2xl font-bold text-gray-500">#${index + 1}</div>
                            <div>
                                <h3 class="text-2xl font-bold text-white capitalize">${row.broker}</h3>
                                <div class="flex gap-2 mt-1">
                                    <span class="text-xs bg-slate-700 px-2 py-1 rounded text-gray-300">Score: ${row.score}/100</span>
                                    ${isTop ? '<span class="text-xs bg-green-900 text-green-300 px-2 py-1 rounded">🏆 Fastest Execution</span>' : ''}
                                    ${isLow ? '<span class="text-xs bg-red-900 text-red-300 px-2 py-1 rounded">⚠️ Congested</span>' : ''}
                                </div>
                            </div>
                        </div>
                        <div class="flex gap-8 text-right">
                            <div>
                                <div class="text-xs text-gray-400 uppercase font-bold">Latency</div>
                                <div class="text-xl font-mono ${row.latency < 50 ? 'text-green-400' : 'text-yellow-400'}">${row.latency}ms</div>
                            </div>
                            <div>
                                <div class="text-xs text-gray-400 uppercase font-bold">Avg Slippage</div>
                                <div class="text-xl font-mono text-white">${row.slippage}</div>
                            </div>
                        </div>
                    </div>
                `;
                container.innerHTML += html;
            });
            document.getElementById('activeNodes').innerText = totalNodes;
        }
        loadLeaderboard();
        setInterval(loadLeaderboard, 5000);
    </script>
</body>
</html>
"""

# --- ENDPOINTS ---


@app.get("/")
async def root():
    return {"status": "online", "service": "PnL Global Oracle"}

# NEW: Serve Dashboard directly from Memory


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML

# 1. THE PUBLIC "WAZE" ENDPOINT (Anonymous)


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

# 2. THE GLOBAL MAP (Aggregated Stats)


@app.get("/v1/global_status")
async def get_global_map(db: Session = Depends(get_db)):
    five_mins_ago = datetime.utcnow() - timedelta(minutes=5)
    stats = db.query(
        TelemetryDB.broker,
        func.avg(TelemetryDB.latency_ms).label("avg_lat"),
        func.avg(TelemetryDB.slippage).label("avg_slip"),
        func.count(TelemetryDB.id).label("volume")
    ).filter(
        TelemetryDB.timestamp >= five_mins_ago
    ).group_by(TelemetryDB.broker).all()

    leaderboard = []
    for broker, avg_lat, avg_slip, volume in stats:
        lat = float(avg_lat) if avg_lat else 0.0
        slip = float(avg_slip) if avg_slip else 0.0
        score = 100 - (lat / 10) - (slip * 1000)
        score = int(max(0, min(100, score)))
        health = "green"
        if lat > 500:
            health = "red"
        elif lat > 150:
            health = "yellow"

        leaderboard.append({
            "broker": broker, "status": health, "score": score,
            "latency": int(lat), "slippage": float(f"{slip:.5f}"), "volume": volume
        })
    return sorted(leaderboard, key=lambda x: x['score'], reverse=True)

# 3. PRO ENDPOINTS


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
