"""
Log Aggregator - Configuration Settings
Menggunakan Pydantic Settings untuk environment-based configuration
"""
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database settings
    database_url: str = "postgresql://aggregator_user:aggregator_pass@localhost:5432/logaggregator"
    db_pool_min_size: int = 5
    db_pool_max_size: int = 20
    
    # Redis broker settings
    broker_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50
    
    # Worker settings
    worker_count: int = 4
    worker_mode: bool = False
    
    # Application settings
    app_name: str = "Log Aggregator"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    
    # Queue settings
    event_queue_name: str = "event_queue"
    processing_queue_name: str = "processing_queue"
    dead_letter_queue_name: str = "dead_letter_queue"
    
    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    retry_backoff_multiplier: float = 2.0
    
    # Batch processing settings
    batch_size: int = 100
    batch_timeout_seconds: float = 5.0
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
