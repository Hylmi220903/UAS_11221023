"""
Event Publisher - Configuration Settings
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Publisher settings from environment variables"""
    
    # Target aggregator URL
    target_url: str = "http://aggregator:8080"
    
    # Redis broker (optional, for direct queue publishing)
    broker_url: str = "redis://broker:6379/0"
    
    # Event generation settings
    event_count: int = 1000
    duplicate_rate: float = 0.3  # 30% duplicates
    batch_size: int = 50
    delay_ms: int = 10
    
    # Topics to generate
    topics: str = "app-logs,security-logs,system-logs,audit-logs"
    
    # Sources
    sources: str = "service-a,service-b,service-c,gateway"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
