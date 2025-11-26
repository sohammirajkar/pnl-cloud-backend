from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import SessionLocal, engine, Base
from models import TradeLogDB, TelemetryDB
from datetime import datetime, timedelta
from typing import List, Dict, Any
from fastapi.staticfiles import StaticFiles

# Initialize Database
Base.metadata.create_all(bind=engine)

app = FastAPI()

# --- ROBUST MOUNTING STRATEGY ---
try:
    # 1. Get absolute path to the 'public' folder (works better in cloud)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    public_path = os.path.join(script_dir, "public")

    # 2. Check if it exists. If not, log a warning but DO NOT CRASH.
    if os.path.exists(public_path):
        app.mount("/public", StaticFiles(directory=public_path), name="public")
        logger.info(f"✅ Mounted public folder at: {public_path}")
    else:
        logger.warning(
            f"⚠️ Public folder not found at {public_path}. Dashboard will be unavailable, but API will survive.")

except Exception as e:
    logger.error(f"❌ Failed to mount public folder: {str(e)}")
# -------------------------------

# CORS
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

# --- ENDPOINTS ---


@app.get("/")
async def root():
    return {"status": "online", "service": "PnL Global Oracle"}

# 1. THE PUBLIC "WAZE" ENDPOINT (Anonymous)


@app.post("/v1/telemetry")
async def submit_telemetry(payload: TelemetryPayload, db: Session = Depends(get_db)):
    """
    Free users send data here. No API Key required.
    """
    new_ping = TelemetryDB(
        broker=payload.broker.lower(),
        latency_ms=payload.latency_ms,
        slippage=payload.slippage,
        status=payload.status
    )
    db.add(new_ping)
    db.commit()
    return {"status": "contributed"}

# 2. THE GLOBAL MAP (Aggregated Stats)


@app.get("/v1/global_status")
async def get_global_map(db: Session = Depends(get_db)):
    """
    Returns the 'Traffic Light' status for every broker based on 
    data from the last 5 minutes.
    """
    five_mins_ago = datetime.utcnow() - timedelta(minutes=5)

    # SQL: SELECT broker, AVG(lat), AVG(slip), COUNT(*)
    stats = db.query(
        TelemetryDB.broker,
        func.avg(TelemetryDB.latency_ms).label("avg_lat"),
        func.avg(TelemetryDB.slippage).label("avg_slip"),
        func.count(TelemetryDB.id).label("volume")
    ).filter(
        TelemetryDB.timestamp >= five_mins_ago
    ).group_by(TelemetryDB.broker).all()

    leaderboard = []

    # Fix: Correctly unpack all 4 values returned by the query
    for broker, avg_lat, avg_slip, volume in stats:

        # Handle potential None values if averages fail
        lat = float(avg_lat) if avg_lat else 0.0
        slip = float(avg_slip) if avg_slip else 0.0

        # Calculate Health Score (0-100)
        score = 100 - (lat / 10) - (slip * 1000)
        score = int(max(0, min(100, score)))

        # Determine Traffic Light Status based on Latency
        health = "green"
        if lat > 500:
            health = "red"
        elif lat > 150:
            health = "yellow"

        leaderboard.append({
            "broker": broker,
            "status": health,
            "score": score,
            "latency": int(lat),
            "slippage": float(f"{slip:.5f}"),
            "volume": volume
        })

    # Return sorted list for the frontend to render
    return sorted(leaderboard, key=lambda x: x['score'], reverse=True)

# 3. THE PRO ENDPOINTS (Private)


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
