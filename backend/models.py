from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = f"sqlite:///{BASE_DIR / 'contract_alpha.db'}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    company: Mapped[str] = mapped_column(String(120), index=True)
    award_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float)
    agency: Mapped[str] = mapped_column(String(120))


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open_roles: Mapped[int] = mapped_column(Integer)
    mfg_roles: Mapped[int] = mapped_column(Integer)
    eng_roles: Mapped[int] = mapped_column(Integer)


class SerpCache(Base):
    __tablename__ = "serp_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    query: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
