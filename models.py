from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from database import Base
from datetime import datetime
from sqlalchemy.sql import func


class TradeLogDB(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Segmentation
    user_id = Column(String, index=True)  # <--- NEW FIELD ADDED

    # Trade Details
    symbol = Column(String, index=True)
    side = Column(String)
    qty = Column(Float)
    broker = Column(String)

    # Metrics
    latency_ms = Column(Integer)
    slippage = Column(Float)
    status = Column(String)

    # Metadata
    timestamp = Column(DateTime, default=datetime.utcnow)


# 2. The "Global Map" Table (Anonymous Telemetry)
# This powers the public status page


class TelemetryDB(Base):
    __tablename__ = "global_telemetry"

    id = Column(Integer, primary_key=True, index=True)
    broker = Column(String, index=True)  # e.g. "binance", "alpaca"
    latency_ms = Column(Integer)
    slippage = Column(Float)
    status = Column(String)             # "verified" or "anomaly"
    timestamp = Column(DateTime, default=datetime.utcnow)


class ApiKeyDB(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key_hash = Column(String, unique=True, index=True)  # Store HASH only
    user_id = Column(String, index=True)                # Link to their UUID
    owner_name = Column(String)                         # "Petio Petrov"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
