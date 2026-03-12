"""
Improzo Signal Engine — Core Data Models
SQLAlchemy ORM models + Pydantic schemas for the entire pipeline.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Text, JSON,
    Enum as SAEnum, Index, ForeignKey
)
from sqlalchemy.orm import DeclarativeBase, relationship


# ─── Enums ────────────────────────────────────────────────────────────────────

class SignalType(str, Enum):
    LEADERSHIP_CHANGE = "leadership_change"
    JOB_POSTING = "job_posting"
    TECHNOLOGY_ADOPTION = "technology_adoption"
    FUNDING_EVENT = "funding_event"
    EXPANSION = "expansion"
    PARTNERSHIP = "partnership"
    REGULATORY_CHANGE = "regulatory_change"
    EARNINGS_EVENT = "earnings_event"
    PRODUCT_LAUNCH = "product_launch"
    MA_ACTIVITY = "ma_activity"
    CONTENT_ENGAGEMENT = "content_engagement"
    EVENT_ATTENDANCE = "event_attendance"


class SignalStatus(str, Enum):
    RAW = "raw"
    CLASSIFIED = "classified"
    VERIFIED = "verified"
    REJECTED = "rejected"
    PUSHED = "pushed"
    FAILED = "failed"


class SourceType(str, Enum):
    NEWS_API = "news_api"
    RSS_FEED = "rss_feed"
    PR_WIRE = "pr_wire"
    JOB_BOARD = "job_board"
    LINKEDIN = "linkedin"
    REGULATORY = "regulatory"
    SEC_FILING = "sec_filing"
    CUSTOM_WEB = "custom_web"


class ScraperStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


# ─── SQLAlchemy Base ──────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ─── ORM Models ───────────────────────────────────────────────────────────────

class SignalRecord(Base):
    """Core signal record stored in the database."""
    __tablename__ = "signals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title = Column(String(500), nullable=False, index=True)
    description = Column(Text, nullable=True)
    signal_type = Column(SAEnum(SignalType), nullable=False, index=True)
    status = Column(SAEnum(SignalStatus), default=SignalStatus.RAW, index=True)

    # Source information
    source_url = Column(String(2000), nullable=True)
    source_type = Column(SAEnum(SourceType), nullable=False)
    source_name = Column(String(200), nullable=True)
    raw_content = Column(Text, nullable=True)

    # Target company
    company_name = Column(String(300), nullable=True, index=True)
    company_domain = Column(String(300), nullable=True)
    company_hubspot_id = Column(String(50), nullable=True)

    # NLP results
    confidence = Column(Float, default=0.0)
    embedding_vector = Column(JSON, nullable=True)
    entities = Column(JSON, nullable=True)  # extracted named entities
    keywords = Column(JSON, nullable=True)

    # Scoring
    recency_score = Column(Integer, default=0)  # 1-5
    relevance_score = Column(Integer, default=0)  # 1-5
    authority_score = Column(Integer, default=0)  # 1-5
    composite_score = Column(Float, default=0.0)  # 1-15

    # HubSpot sync
    hubspot_object_id = Column(String(50), nullable=True)
    hubspot_synced_at = Column(DateTime, nullable=True)

    # Deduplication
    content_hash = Column(String(64), nullable=True, index=True)
    dedup_cluster_id = Column(String(36), nullable=True)
    is_duplicate = Column(Boolean, default=False)

    # Metadata
    published_at = Column(DateTime, nullable=True)
    collected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    classified_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    verified_by = Column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_signals_company_type", "company_name", "signal_type"),
        Index("ix_signals_score", "composite_score"),
        Index("ix_signals_collected", "collected_at"),
    )


class ScraperRun(Base):
    """Tracks each scraper execution."""
    __tablename__ = "scraper_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scraper_name = Column(String(100), nullable=False, index=True)
    source_type = Column(SAEnum(SourceType), nullable=False)
    status = Column(SAEnum(ScraperStatus), default=ScraperStatus.IDLE)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    signals_found = Column(Integer, default=0)
    signals_new = Column(Integer, default=0)
    signals_duplicate = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)


class ICPAccount(Base):
    """Ideal Customer Profile account tracking."""
    __tablename__ = "icp_accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_name = Column(String(300), nullable=False, index=True)
    domain = Column(String(300), nullable=True, unique=True)
    hubspot_company_id = Column(String(50), nullable=True)

    # ICP scoring dimensions (1-5 each)
    industry_fit = Column(Integer, default=0)
    size_fit = Column(Integer, default=0)
    tech_fit = Column(Integer, default=0)
    geo_fit = Column(Integer, default=0)
    budget_fit = Column(Integer, default=0)
    icp_score = Column(Float, default=0.0)  # composite 1-25

    # Signal tracking
    total_signals = Column(Integer, default=0)
    signal_velocity = Column(Float, default=0.0)  # signals per week
    last_signal_at = Column(DateTime, nullable=True)
    tier = Column(String(10), default="2")  # "1" or "2"

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PipelineMetric(Base):
    """Hourly pipeline health metrics."""
    __tablename__ = "pipeline_metrics"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    signals_collected = Column(Integer, default=0)
    signals_classified = Column(Integer, default=0)
    signals_verified = Column(Integer, default=0)
    signals_pushed = Column(Integer, default=0)
    signals_rejected = Column(Integer, default=0)
    duplicates_caught = Column(Integer, default=0)
    avg_confidence = Column(Float, default=0.0)
    avg_processing_time_ms = Column(Float, default=0.0)
    scraper_uptime_pct = Column(Float, default=100.0)
    active_scrapers = Column(Integer, default=0)
    errors = Column(Integer, default=0)


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class RawSignalInput(BaseModel):
    """Input from a scraper — raw, unprocessed signal."""
    title: str
    description: Optional[str] = None
    source_url: Optional[str] = None
    source_type: SourceType
    source_name: Optional[str] = None
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    raw_content: Optional[str] = None
    published_at: Optional[datetime] = None


class ClassifiedSignal(BaseModel):
    """Signal after NLP classification."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str] = None
    signal_type: SignalType
    confidence: float
    company_name: Optional[str] = None
    entities: Optional[dict] = None
    keywords: Optional[list[str]] = None


class ScoredSignal(BaseModel):
    """Signal after scoring."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    signal_type: SignalType
    confidence: float
    recency_score: int
    relevance_score: int
    authority_score: int
    composite_score: float
    company_name: Optional[str] = None
    source_url: Optional[str] = None
    source_type: SourceType
    status: SignalStatus


class SignalResponse(BaseModel):
    """Full signal response for API."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str] = None
    signal_type: SignalType
    status: SignalStatus
    source_url: Optional[str] = None
    source_type: SourceType
    source_name: Optional[str] = None
    company_name: Optional[str] = None
    confidence: float = 0.0
    recency_score: int = 0
    relevance_score: int = 0
    authority_score: int = 0
    composite_score: float = 0.0
    is_duplicate: bool = False
    hubspot_object_id: Optional[str] = None
    published_at: Optional[datetime] = None
    collected_at: Optional[datetime] = None
    classified_at: Optional[datetime] = None


class EngineHealthResponse(BaseModel):
    """Engine health metrics for dashboard."""
    status: str = "healthy"
    uptime_pct: float = 100.0
    active_scrapers: int = 0
    total_scrapers: int = 0
    signals_today: int = 0
    signals_this_week: int = 0
    avg_confidence: float = 0.0
    pipeline_throughput: float = 0.0  # signals/hour
    last_scan_at: Optional[datetime] = None
    errors_last_hour: int = 0


class ScraperStatusResponse(BaseModel):
    """Individual scraper status."""
    name: str
    source_type: SourceType
    status: ScraperStatus
    last_run_at: Optional[datetime] = None
    signals_found: int = 0
    success_rate: float = 100.0
    avg_duration_seconds: float = 0.0
