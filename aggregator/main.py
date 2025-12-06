"""
Log Aggregator - Main Application
FastAPI application with Pub-Sub log aggregation, idempotency, and deduplication
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from models import (
    Event, BatchEvents, PublishResponse, BatchPublishResponse,
    EventResponse, EventsListResponse, StatsResponse, HealthResponse, ErrorResponse
)
from database import Database, get_database, db
from broker import Broker, get_broker, broker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Track application start time for uptime calculation
START_TIME = datetime.utcnow()

# Worker tasks
worker_tasks: List[asyncio.Task] = []


async def process_event_from_queue(event_data: dict) -> None:
    """
    Process event from queue with idempotent insert.
    This function is called by background workers.
    """
    try:
        await db.insert_event_idempotent(
            topic=event_data['topic'],
            event_id=event_data['event_id'],
            timestamp=datetime.fromisoformat(event_data['timestamp'].replace('Z', '+00:00')) 
                if isinstance(event_data['timestamp'], str) else event_data['timestamp'],
            source=event_data['source'],
            payload=event_data.get('payload', {}),
            worker_id=f"worker-{os.getpid()}"
        )
    except Exception as e:
        logger.error(f"Error processing event from queue: {e}")
        raise


async def start_workers(count: int = 4) -> None:
    """Start background worker tasks"""
    global worker_tasks
    
    for i in range(count):
        task = asyncio.create_task(
            broker.start_worker(process_event_from_queue, f"worker-{i+1}")
        )
        worker_tasks.append(task)
    
    logger.info(f"Started {count} background workers")


async def stop_workers() -> None:
    """Stop all background workers"""
    global worker_tasks
    
    broker.stop_workers()
    
    for task in worker_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    worker_tasks.clear()
    logger.info("All workers stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("Starting Log Aggregator...")
    
    try:
        await db.connect()
        await broker.connect()
        
        # Start workers if not in worker mode
        if not settings.worker_mode:
            await start_workers(settings.worker_count)
        else:
            # Worker mode - only process queue
            await start_workers(settings.worker_count)
        
        logger.info("Log Aggregator started successfully")
        yield
    finally:
        # Shutdown
        logger.info("Shutting down Log Aggregator...")
        await stop_workers()
        await broker.disconnect()
        await db.disconnect()
        logger.info("Log Aggregator shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Log Aggregator",
    description="Distributed Pub-Sub Log Aggregator with Idempotent Consumer and Deduplication",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== API Endpoints ====================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint untuk liveness/readiness probe.
    Memeriksa konektivitas database dan broker.
    """
    db_healthy = await db.health_check() if db.is_connected else False
    broker_healthy = await broker.health_check() if broker.is_connected else False
    
    uptime = (datetime.utcnow() - START_TIME).total_seconds()
    
    status = "healthy" if (db_healthy and broker_healthy) else "unhealthy"
    
    return HealthResponse(
        status=status,
        database="connected" if db_healthy else "disconnected",
        broker="connected" if broker_healthy else "disconnected",
        uptime_seconds=uptime,
        version=settings.app_version
    )


@app.post("/publish", response_model=PublishResponse, tags=["Events"])
async def publish_event(event: Event, database: Database = Depends(get_database)):
    """
    Publish single event ke aggregator.
    
    Implementasi idempotency:
    - Menggunakan unique constraint (topic, event_id)
    - INSERT ... ON CONFLICT DO NOTHING untuk atomic deduplication
    - Event yang sama akan diabaikan tanpa error
    
    Isolation Level: READ COMMITTED
    Pattern: Idempotent Insert
    """
    try:
        success, is_new = await database.insert_event_idempotent(
            topic=event.topic,
            event_id=event.event_id,
            timestamp=event.timestamp,
            source=event.source,
            payload=event.payload,
            worker_id="api-direct"
        )
        
        return PublishResponse(
            success=True,
            message="Event processed successfully" if is_new else "Duplicate event ignored",
            event_id=event.event_id,
            is_duplicate=not is_new,
            received_at=datetime.utcnow()
        )
    except Exception as e:
        logger.error(f"Failed to publish event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/publish/batch", response_model=BatchPublishResponse, tags=["Events"])
async def publish_batch_events(
    batch: BatchEvents,
    database: Database = Depends(get_database)
):
    """
    Publish batch events dengan atomic transaction.
    
    Transaksi:
    - Seluruh batch diproses dalam satu transaction
    - Jika ada error, seluruh batch di-rollback
    - Deduplication tetap berlaku untuk setiap event
    
    Isolation Level: READ COMMITTED
    Pattern: Batch Atomic Insert
    """
    try:
        events_data = [
            {
                'topic': e.topic,
                'event_id': e.event_id,
                'timestamp': e.timestamp,
                'source': e.source,
                'payload': e.payload
            }
            for e in batch.events
        ]
        
        total, new_count, duplicate_count = await database.batch_insert_events_atomic(
            events_data,
            worker_id="api-batch"
        )
        
        return BatchPublishResponse(
            success=True,
            total_received=total,
            unique_processed=new_count,
            duplicates_dropped=duplicate_count,
            failed=0
        )
    except Exception as e:
        logger.error(f"Failed to publish batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/publish/queue", response_model=PublishResponse, tags=["Events"])
async def publish_to_queue(event: Event, broker_inst: Broker = Depends(get_broker)):
    """
    Publish event ke message queue untuk async processing.
    
    At-least-once delivery:
    - Event dikirim ke Redis queue
    - Worker akan memproses dan melakukan deduplication
    - Retry mechanism dengan exponential backoff
    """
    try:
        event_data = {
            'topic': event.topic,
            'event_id': event.event_id,
            'timestamp': event.timestamp.isoformat(),
            'source': event.source,
            'payload': event.payload
        }
        
        success = await broker_inst.publish_event(event_data)
        
        if success:
            return PublishResponse(
                success=True,
                message="Event queued for processing",
                event_id=event.event_id,
                is_duplicate=False,
                received_at=datetime.utcnow()
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to queue event")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to queue event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/events", response_model=EventsListResponse, tags=["Events"])
async def get_events(
    topic: Optional[str] = Query(None, description="Filter by topic"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum events to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    database: Database = Depends(get_database)
):
    """
    Get list of processed events.
    
    Features:
    - Filter by topic (optional)
    - Pagination with limit/offset
    - Returns only unique, processed events
    """
    try:
        events = await database.get_events(topic=topic, limit=limit, offset=offset)
        
        event_responses = [
            EventResponse(
                topic=e['topic'],
                event_id=e['event_id'],
                timestamp=e['timestamp'],
                source=e['source'],
                payload=e['payload'],
                received_at=e['received_at'],
                processed_at=e.get('processed_at')
            )
            for e in events
        ]
        
        return EventsListResponse(
            success=True,
            topic=topic,
            count=len(event_responses),
            events=event_responses
        )
    except Exception as e:
        logger.error(f"Failed to get events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse, tags=["Statistics"])
async def get_stats(
    database: Database = Depends(get_database),
    broker_inst: Broker = Depends(get_broker)
):
    """
    Get aggregation statistics.
    
    Returns:
    - received: Total events received
    - unique_processed: Unique events successfully processed
    - duplicate_dropped: Duplicate events that were dropped
    - topics: List of active topics
    - topic_counts: Event count per topic
    - uptime: Service uptime
    - queue_size: Current message queue size
    """
    try:
        stats = await database.get_statistics()
        queue_size = await broker_inst.get_queue_size()
        
        uptime_seconds = (datetime.utcnow() - START_TIME).total_seconds()
        uptime_delta = timedelta(seconds=uptime_seconds)
        
        # Format uptime as human readable
        days = uptime_delta.days
        hours, remainder = divmod(uptime_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_formatted = f"{days}d {hours}h {minutes}m {seconds}s"
        
        return StatsResponse(
            received=stats['received'],
            unique_processed=stats['unique_processed'],
            duplicate_dropped=stats['duplicate_dropped'],
            topics=stats['topics'],
            topic_counts=stats['topic_counts'],
            uptime_seconds=uptime_seconds,
            uptime_formatted=uptime_formatted,
            workers_active=len(worker_tasks),
            queue_size=queue_size
        )
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/events", tags=["Events"])
async def clear_events(database: Database = Depends(get_database)):
    """
    Clear all events (for testing purposes only).
    """
    try:
        async with database.transaction() as conn:
            await conn.execute("DELETE FROM audit_log")
            await conn.execute("DELETE FROM processed_events")
            await conn.execute("DELETE FROM events")
            await conn.execute("UPDATE statistics SET stat_value = 0")
        
        return {"success": True, "message": "All events cleared"}
    except Exception as e:
        logger.error(f"Failed to clear events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            success=False,
            error=str(exc.detail),
            detail=None,
            timestamp=datetime.utcnow()
        ).model_dump(mode='json')
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            success=False,
            error="Internal server error",
            detail=str(exc),
            timestamp=datetime.utcnow()
        ).model_dump(mode='json')
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        workers=1,
        log_level=settings.log_level.lower()
    )
