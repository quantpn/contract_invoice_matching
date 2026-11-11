"""Database connection and session management using SQLAlchemy (PostgreSQL + pgvector via Docker)."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Mặc định kết nối tới PostgreSQL container (cổng 5434 trên host hoặc tên service 'db:5432' trong Docker)
DEFAULT_POSTGRES_URL = "postgresql+psycopg2://ai_user:ai_password@localhost:5434/contract_invoice_db"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_POSTGRES_URL)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
