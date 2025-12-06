"""
Log Aggregator - Event Models
Pydantic models untuk validasi event dan response
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
import uuid


class EventStatus(str, Enum):
    """Status of an event"""
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class Event(BaseModel):
    """
    Model untuk single event
    Sesuai dengan spesifikasi: { "topic": "string", "event_id": "string-unik", 
    "timestamp": "ISO8601", "source": "string", "payload": { ... } }
    """
    topic: str = Field(..., min_length=1, max_length=255, description="Topic name for the event")
    event_id: str = Field(..., min_length=1, max_length=255, description="Unique event identifier")
    timestamp: datetime = Field(..., description="Event timestamp in ISO8601 format")
    source: str = Field(..., min_length=1, max_length=255, description="Source of the event")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event payload data")
    
    @field_validator('topic', 'event_id', 'source')
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Field cannot be empty or whitespace only')
        return v.strip()
    
    @field_validator('event_id')
    @classmethod
    def validate_event_id_format(cls, v: str) -> str:
        """Validate event_id is collision-resistant (UUID-like or custom format)"""
        v = v.strip()
        # Allow UUID format or custom format with alphanumeric and hyphens
        if len(v) < 8:
            raise ValueError('event_id must be at least 8 characters for collision resistance')
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "topic": "application-logs",
                "event_id": "evt-550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2024-12-04T10:30:00Z",
                "source": "service-a",
                "payload": {
                    "level": "INFO",
                    "message": "User login successful",
                    "user_id": "12345"
                }
            }
        }


class BatchEvents(BaseModel):
    """Model untuk batch event submission"""
    events: List[Event] = Field(..., min_length=1, max_length=1000, description="List of events to publish")


class PublishResponse(BaseModel):
    """Response model untuk POST /publish"""
    success: bool
    message: str
    event_id: Optional[str] = None
    is_duplicate: bool = False
    received_at: Optional[datetime] = None


class BatchPublishResponse(BaseModel):
    """Response model untuk batch publish"""
    success: bool
    total_received: int
    unique_processed: int
    duplicates_dropped: int
    failed: int
    details: List[PublishResponse] = Field(default_factory=list)


class EventResponse(BaseModel):
    """Response model untuk single event dalam GET /events"""
    topic: str
    event_id: str
    timestamp: datetime
    source: str
    payload: Dict[str, Any]
    received_at: datetime
    processed_at: Optional[datetime] = None


class EventsListResponse(BaseModel):
    """Response model untuk GET /events"""
    success: bool
    topic: Optional[str] = None
    count: int
    events: List[EventResponse]


class StatsResponse(BaseModel):
    """
    Response model untuk GET /stats
    Berisi: received, unique_processed, duplicate_dropped, topics, uptime
    """
    received: int = Field(..., description="Total events received")
    unique_processed: int = Field(..., description="Unique events successfully processed")
    duplicate_dropped: int = Field(..., description="Duplicate events dropped")
    topics: List[str] = Field(default_factory=list, description="List of active topics")
    topic_counts: Dict[str, int] = Field(default_factory=dict, description="Event count per topic")
    uptime_seconds: float = Field(..., description="Service uptime in seconds")
    uptime_formatted: str = Field(..., description="Human-readable uptime")
    workers_active: int = Field(default=0, description="Number of active workers")
    queue_size: int = Field(default=0, description="Current queue size")


class HealthResponse(BaseModel):
    """Response model untuk health check"""
    status: str
    database: str
    broker: str
    uptime_seconds: float
    version: str


class ErrorResponse(BaseModel):
    """Standard error response"""
    success: bool = False
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
