import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. Get the DB URL from Environment Variables (Vercel injects this)
# If not found, fallback to local SQLite (for your laptop)
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pnl.db")

# 2. Fix for Postgres URL (SQLAlchemy needs 'postgresql://', Neon gives 'postgres://')
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
        "postgres://", "postgresql://", 1)

# 3. Create Engine
if "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={
                           "check_same_thread": False})
else:
    # Postgres (Neon) doesn't need 'check_same_thread'
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
