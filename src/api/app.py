"""
FastAPI Application — REST API + WebSocket for Improzo Signal Engine.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, desc

from config.settings import settings
from src.models import (
    SignalRecord, SignalStatus, SignalType, SourceType,
    SignalResponse, EngineHealthResponse, ScraperStatusResponse,
    RawSignalInput, PipelineMetric, ScraperRun,
)
from src.pipeline import SignalPipeline
from src.utils.database import init_db, get_session
from src.utils.logging import setup_logging, get_logger

logger = get_logger("api")

# Global pipeline instance
pipeline: Optional[SignalPipeline] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — init DB, pipeline, scheduler."""
    global pipeline
    setup_logging()
    logger.info("starting_signal_engine", version=settings.version)

    # Initialize database
    await init_db()

    # Initialize pipeline
    pipeline = SignalPipeline()
    await pipeline.initialize()

    logger.info("signal_engine_ready")
    yield

    logger.info("shutting_down_signal_engine")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Automated Signal Intelligence Engine for Improzo GTM Platform",
    docs_url="/docs" if settings.api.docs_enabled else None,
    redoc_url="/redoc" if settings.api.docs_enabled else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_pipeline() -> SignalPipeline:
    if pipeline is None:
        raise HTTPException(500, "Pipeline not initialized")
    return pipeline


# ─── Health & Status ─────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
async def root():
    return {
        "name": settings.app_name,
        "version": settings.version,
        "status": "running",
        "environment": settings.environment.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health", response_model=EngineHealthResponse, tags=["Health"])
async def health_check(p: SignalPipeline = Depends(get_pipeline)):
    """Get engine health status."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    async with get_session() as session:
        # Signals today
        result = await session.execute(
            select(func.count(SignalRecord.id)).where(
                SignalRecord.collected_at >= today_start
            )
        )
        signals_today = result.scalar() or 0

        # Signals this week
        result = await session.execute(
            select(func.count(SignalRecord.id)).where(
                SignalRecord.collected_at >= week_start
            )
        )
        signals_week = result.scalar() or 0

        # Average confidence
        result = await session.execute(
            select(func.avg(SignalRecord.confidence)).where(
                SignalRecord.collected_at >= today_start,
                SignalRecord.confidence > 0,
            )
        )
        avg_confidence = result.scalar() or 0.0

        # Errors last hour
        result = await session.execute(
            select(func.count(ScraperRun.id)).where(
                ScraperRun.started_at >= now - timedelta(hours=1),
                ScraperRun.status == "failed",
            )
        )
        errors = result.scalar() or 0

    scrapers = p.scraper_manager.get_scraper_statuses()
    active = sum(1 for s in scrapers if s["status"] == "running")

    return EngineHealthResponse(
        status="running" if p.is_running else "healthy",
        uptime_pct=round((len(scrapers) - errors) / max(len(scrapers), 1) * 100, 1),
        active_scrapers=active,
        total_scrapers=len(scrapers),
        signals_today=signals_today,
        signals_this_week=signals_week,
        avg_confidence=round(avg_confidence, 3),
        pipeline_throughput=round(signals_today / max((now.hour or 1), 1), 1),
        errors_last_hour=errors,
    )


@app.get("/scrapers", tags=["Scrapers"])
async def get_scraper_statuses(p: SignalPipeline = Depends(get_pipeline)):
    """Get status of all scrapers."""
    return {"scrapers": p.scraper_manager.get_scraper_statuses()}


# ─── Signal Operations ───────────────────────────────────────────────────────

@app.get("/signals", tags=["Signals"])
async def list_signals(
    status: Optional[SignalStatus] = None,
    signal_type: Optional[SignalType] = None,
    company: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="composite_score", regex="^(composite_score|collected_at|confidence)$"),
):
    """List signals with filtering and pagination."""
    async with get_session() as session:
        query = select(SignalRecord).where(SignalRecord.is_duplicate == False)

        if status:
            query = query.where(SignalRecord.status == status)
        if signal_type:
            query = query.where(SignalRecord.signal_type == signal_type)
        if company:
            query = query.where(SignalRecord.company_name.ilike(f"%{company}%"))
        if min_score:
            query = query.where(SignalRecord.composite_score >= min_score)

        # Sort
        sort_col = getattr(SignalRecord, sort_by)
        query = query.order_by(desc(sort_col)).offset(offset).limit(limit)

        result = await session.execute(query)
        signals = result.scalars().all()

        # Total count
        count_query = select(func.count(SignalRecord.id)).where(SignalRecord.is_duplicate == False)
        if status:
            count_query = count_query.where(SignalRecord.status == status)
        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0

    return {
        "signals": [SignalResponse.model_validate(s).model_dump() for s in signals],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/signals/{signal_id}", response_model=SignalResponse, tags=["Signals"])
async def get_signal(signal_id: str):
    """Get a specific signal by ID."""
    async with get_session() as session:
        result = await session.execute(
            select(SignalRecord).where(SignalRecord.id == signal_id)
        )
        signal = result.scalar_one_or_none()
        if not signal:
            raise HTTPException(404, "Signal not found")
        return SignalResponse.model_validate(signal)


@app.post("/signals/{signal_id}/verify", tags=["Signals"])
async def verify_signal(signal_id: str):
    """Manually verify a signal."""
    async with get_session() as session:
        result = await session.execute(
            select(SignalRecord).where(SignalRecord.id == signal_id)
        )
        signal = result.scalar_one_or_none()
        if not signal:
            raise HTTPException(404, "Signal not found")

        signal.status = SignalStatus.VERIFIED
        signal.verified_at = datetime.now(timezone.utc)
        signal.verified_by = "manual"

    return {"status": "verified", "signal_id": signal_id}


@app.post("/signals/{signal_id}/reject", tags=["Signals"])
async def reject_signal(signal_id: str):
    """Manually reject a signal."""
    async with get_session() as session:
        result = await session.execute(
            select(SignalRecord).where(SignalRecord.id == signal_id)
        )
        signal = result.scalar_one_or_none()
        if not signal:
            raise HTTPException(404, "Signal not found")

        signal.status = SignalStatus.REJECTED

    return {"status": "rejected", "signal_id": signal_id}


@app.post("/signals/{signal_id}/push", tags=["Signals"])
async def push_signal_to_hubspot(signal_id: str, p: SignalPipeline = Depends(get_pipeline)):
    """Push a single signal to HubSpot."""
    async with get_session() as session:
        result = await session.execute(
            select(SignalRecord).where(SignalRecord.id == signal_id)
        )
        signal = result.scalar_one_or_none()
        if not signal:
            raise HTTPException(404, "Signal not found")

        hubspot_id = await p.hubspot.push_signal(signal)
        if hubspot_id:
            return {"status": "pushed", "hubspot_id": hubspot_id}
        else:
            raise HTTPException(500, "Failed to push to HubSpot")


# ─── Pipeline Operations ────────────────────────────────────────────────────

@app.post("/pipeline/scan", tags=["Pipeline"])
async def trigger_scan(
    scrapers: Optional[list[str]] = Query(default=None),
    companies: Optional[list[str]] = Query(default=None),
    push_to_hubspot: bool = Query(default=True),
    p: SignalPipeline = Depends(get_pipeline),
):
    """Trigger a full pipeline scan."""
    if p.is_running:
        raise HTTPException(409, "Pipeline is already running")

    # Run in background
    asyncio.create_task(
        p.run_full_scan(
            target_companies=companies,
            scraper_names=scrapers,
            push_to_hubspot=push_to_hubspot,
        )
    )

    return {
        "status": "scan_started",
        "scrapers": scrapers or list(p.scraper_manager.scrapers.keys()),
        "companies": companies,
    }


@app.post("/pipeline/process", tags=["Pipeline"])
async def process_single_signal(
    signal: RawSignalInput,
    p: SignalPipeline = Depends(get_pipeline),
):
    """Process a single raw signal through the pipeline."""
    record = await p.process_signal(signal)
    return SignalResponse.model_validate(record).model_dump()


@app.get("/pipeline/metrics", tags=["Pipeline"])
async def get_pipeline_metrics(
    hours: int = Query(default=24, le=168),
):
    """Get pipeline metrics for the last N hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with get_session() as session:
        result = await session.execute(
            select(PipelineMetric)
            .where(PipelineMetric.timestamp >= since)
            .order_by(desc(PipelineMetric.timestamp))
            .limit(100)
        )
        metrics = result.scalars().all()

    return {
        "metrics": [
            {
                "timestamp": m.timestamp.isoformat(),
                "signals_collected": m.signals_collected,
                "signals_classified": m.signals_classified,
                "signals_verified": m.signals_verified,
                "signals_pushed": m.signals_pushed,
                "duplicates_caught": m.duplicates_caught,
                "avg_confidence": m.avg_confidence,
                "scraper_uptime_pct": m.scraper_uptime_pct,
                "errors": m.errors,
            }
            for m in metrics
        ],
        "period_hours": hours,
    }


@app.get("/pipeline/last-run", tags=["Pipeline"])
async def get_last_run(p: SignalPipeline = Depends(get_pipeline)):
    """Get metrics from the last pipeline run."""
    return p.last_metrics or {"message": "No runs yet"}


# ─── Analytics ───────────────────────────────────────────────────────────────

@app.get("/analytics/distribution", tags=["Analytics"])
async def signal_distribution():
    """Get signal distribution by type."""
    async with get_session() as session:
        result = await session.execute(
            select(
                SignalRecord.signal_type,
                func.count(SignalRecord.id),
            )
            .where(SignalRecord.is_duplicate == False)
            .group_by(SignalRecord.signal_type)
        )
        distribution = {row[0].value: row[1] for row in result.all()}

    return {"distribution": distribution}


@app.get("/analytics/top-companies", tags=["Analytics"])
async def top_companies(limit: int = Query(default=20, le=100)):
    """Get top companies by signal count."""
    async with get_session() as session:
        result = await session.execute(
            select(
                SignalRecord.company_name,
                func.count(SignalRecord.id).label("signal_count"),
                func.avg(SignalRecord.composite_score).label("avg_score"),
            )
            .where(
                SignalRecord.is_duplicate == False,
                SignalRecord.company_name.isnot(None),
            )
            .group_by(SignalRecord.company_name)
            .order_by(desc("signal_count"))
            .limit(limit)
        )

    return {
        "companies": [
            {
                "company": row[0],
                "signal_count": row[1],
                "avg_score": round(row[2], 2) if row[2] else 0,
            }
            for row in result.all()
        ]
    }


@app.get("/analytics/source-stats", tags=["Analytics"])
async def source_stats():
    """Get signal counts by source type."""
    async with get_session() as session:
        result = await session.execute(
            select(
                SignalRecord.source_type,
                func.count(SignalRecord.id),
                func.avg(SignalRecord.confidence),
            )
            .where(SignalRecord.is_duplicate == False)
            .group_by(SignalRecord.source_type)
        )

    return {
        "sources": [
            {
                "source_type": row[0].value,
                "count": row[1],
                "avg_confidence": round(row[2], 3) if row[2] else 0,
            }
            for row in result.all()
        ]
    }


# ─── WebSocket — Real-Time Signal Feed ───────────────────────────────────────

@app.websocket("/ws/signals")
async def websocket_signal_feed(websocket: WebSocket):
    """Real-time signal feed via WebSocket."""
    await websocket.accept()
    logger.info("websocket_client_connected")

    p = get_pipeline()
    queue = p.subscribe()

    try:
        while True:
            signal_data = await queue.get()
            await websocket.send_json(signal_data)
    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected")
    finally:
        p.unsubscribe(queue)


# ─── HubSpot ────────────────────────────────────────────────────────────────

@app.get("/hubspot/health", tags=["HubSpot"])
async def hubspot_health(p: SignalPipeline = Depends(get_pipeline)):
    """Check HubSpot connectivity."""
    return await p.hubspot.health_check()


@app.post("/hubspot/setup-schema", tags=["HubSpot"])
async def setup_hubspot_schema(p: SignalPipeline = Depends(get_pipeline)):
    """Create the Signal custom object schema in HubSpot."""
    try:
        await p.hubspot.ensure_custom_object_schema()
        return {"status": "schema_ready"}
    except Exception as e:
        raise HTTPException(500, f"Schema setup failed: {str(e)}")
