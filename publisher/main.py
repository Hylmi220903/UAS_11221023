"""
Event Publisher - Main Application
Generates and publishes events to the Log Aggregator with configurable duplicate rate
"""
import asyncio
import httpx
import json
import random
import uuid
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@dataclass
class PublishStats:
    """Statistics for publishing session"""
    total_sent: int = 0
    successful: int = 0
    failed: int = 0
    duplicates_sent: int = 0
    unique_events: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    @property
    def duration(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time
    
    @property
    def events_per_second(self) -> float:
        if self.duration > 0:
            return self.total_sent / self.duration
        return 0


class EventGenerator:
    """
    Event generator with configurable duplicate rate.
    Generates realistic log events with controlled duplication for testing.
    """
    
    def __init__(self):
        self.topics = settings.topics.split(',')
        self.sources = settings.sources.split(',')
        self.generated_events: List[Dict[str, Any]] = []
        self.log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        self.messages = [
            "User authentication successful",
            "Database connection established",
            "Request processed successfully",
            "Cache miss, fetching from database",
            "Configuration reloaded",
            "Background job completed",
            "API rate limit reached",
            "Session timeout detected",
            "File upload completed",
            "Email notification sent"
        ]
    
    def generate_event(self, force_unique: bool = False) -> Dict[str, Any]:
        """Generate a single event"""
        topic = random.choice(self.topics)
        source = random.choice(self.sources)
        
        # Check if we should create a duplicate
        should_duplicate = (
            not force_unique and 
            len(self.generated_events) > 0 and 
            random.random() < settings.duplicate_rate
        )
        
        if should_duplicate:
            # Return a copy of a previously generated event (duplicate)
            original = random.choice(self.generated_events)
            return original.copy()
        
        # Generate new unique event
        event = {
            "topic": topic,
            "event_id": f"evt-{uuid.uuid4()}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": source,
            "payload": {
                "level": random.choice(self.log_levels),
                "message": random.choice(self.messages),
                "request_id": str(uuid.uuid4())[:8],
                "user_id": f"user-{random.randint(1000, 9999)}",
                "duration_ms": random.randint(1, 500),
                "metadata": {
                    "version": "1.0.0",
                    "environment": "production"
                }
            }
        }
        
        # Store for potential duplication later
        self.generated_events.append(event)
        
        # Limit memory usage
        if len(self.generated_events) > 1000:
            self.generated_events = self.generated_events[-500:]
        
        return event
    
    def generate_batch(self, size: int) -> List[Dict[str, Any]]:
        """Generate a batch of events"""
        return [self.generate_event() for _ in range(size)]
    
    def generate_unique_batch(self, size: int) -> List[Dict[str, Any]]:
        """Generate a batch of unique events (no duplicates)"""
        return [self.generate_event(force_unique=True) for _ in range(size)]


class EventPublisher:
    """
    Publishes events to the Log Aggregator via HTTP API.
    Supports single and batch publishing with retry logic.
    """
    
    def __init__(self, target_url: str):
        self.target_url = target_url.rstrip('/')
        self.stats = PublishStats()
        self.generator = EventGenerator()
        self.client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    async def publish_single(self, event: Dict[str, Any]) -> bool:
        """Publish single event via POST /publish"""
        try:
            response = await self.client.post(
                f"{self.target_url}/publish",
                json=event
            )
            
            if response.status_code == 200:
                result = response.json()
                self.stats.successful += 1
                if result.get('is_duplicate'):
                    logger.debug(f"Duplicate detected: {event['event_id']}")
                return True
            else:
                logger.warning(f"Publish failed: {response.status_code}")
                self.stats.failed += 1
                return False
        except Exception as e:
            logger.error(f"Publish error: {e}")
            self.stats.failed += 1
            return False
    
    async def publish_batch(self, events: List[Dict[str, Any]]) -> bool:
        """Publish batch of events via POST /publish/batch"""
        try:
            response = await self.client.post(
                f"{self.target_url}/publish/batch",
                json={"events": events}
            )
            
            if response.status_code == 200:
                result = response.json()
                self.stats.successful += result.get('unique_processed', 0)
                self.stats.duplicates_sent += result.get('duplicates_dropped', 0)
                logger.info(
                    f"Batch: {result.get('total_received')} total, "
                    f"{result.get('unique_processed')} unique, "
                    f"{result.get('duplicates_dropped')} duplicates"
                )
                return True
            else:
                logger.warning(f"Batch publish failed: {response.status_code}")
                self.stats.failed += len(events)
                return False
        except Exception as e:
            logger.error(f"Batch publish error: {e}")
            self.stats.failed += len(events)
            return False
    
    async def run_single_mode(self, count: int) -> PublishStats:
        """Run publisher in single event mode"""
        logger.info(f"Starting single mode: {count} events")
        
        for i in range(count):
            event = self.generator.generate_event()
            is_dup = event in self.generator.generated_events[:-1]
            
            if is_dup:
                self.stats.duplicates_sent += 1
            else:
                self.stats.unique_events += 1
            
            await self.publish_single(event)
            self.stats.total_sent += 1
            
            if (i + 1) % 100 == 0:
                logger.info(f"Progress: {i + 1}/{count} events sent")
            
            if settings.delay_ms > 0:
                await asyncio.sleep(settings.delay_ms / 1000)
        
        self.stats.end_time = time.time()
        return self.stats
    
    async def run_batch_mode(self, total_count: int, batch_size: int) -> PublishStats:
        """Run publisher in batch mode"""
        logger.info(f"Starting batch mode: {total_count} events in batches of {batch_size}")
        
        batches_sent = 0
        remaining = total_count
        
        while remaining > 0:
            current_batch_size = min(batch_size, remaining)
            events = self.generator.generate_batch(current_batch_size)
            
            # Count duplicates in this batch
            seen = set()
            for event in events:
                key = (event['topic'], event['event_id'])
                if key in seen:
                    self.stats.duplicates_sent += 1
                else:
                    seen.add(key)
                    self.stats.unique_events += 1
            
            await self.publish_batch(events)
            self.stats.total_sent += current_batch_size
            
            batches_sent += 1
            remaining -= current_batch_size
            
            if batches_sent % 10 == 0:
                logger.info(f"Progress: {self.stats.total_sent}/{total_count} events sent")
            
            if settings.delay_ms > 0:
                await asyncio.sleep(settings.delay_ms / 1000)
        
        self.stats.end_time = time.time()
        return self.stats
    
    async def run_concurrent_mode(
        self,
        total_count: int,
        concurrency: int = 10
    ) -> PublishStats:
        """Run publisher with concurrent requests for stress testing"""
        logger.info(f"Starting concurrent mode: {total_count} events with {concurrency} concurrent workers")
        
        semaphore = asyncio.Semaphore(concurrency)
        
        async def publish_with_limit(event: Dict[str, Any]):
            async with semaphore:
                await self.publish_single(event)
                self.stats.total_sent += 1
        
        events = [self.generator.generate_event() for _ in range(total_count)]
        
        # Count unique vs duplicates
        seen = set()
        for event in events:
            key = (event['topic'], event['event_id'])
            if key in seen:
                self.stats.duplicates_sent += 1
            else:
                seen.add(key)
                self.stats.unique_events += 1
        
        await asyncio.gather(*[publish_with_limit(e) for e in events])
        
        self.stats.end_time = time.time()
        return self.stats


async def wait_for_aggregator(url: str, max_retries: int = 30, delay: float = 2.0) -> bool:
    """Wait for aggregator to be ready"""
    logger.info(f"Waiting for aggregator at {url}...")
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        for i in range(max_retries):
            try:
                response = await client.get(f"{url}/health")
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'healthy':
                        logger.info("Aggregator is ready!")
                        return True
            except Exception as e:
                logger.debug(f"Attempt {i+1}/{max_retries}: {e}")
            
            await asyncio.sleep(delay)
    
    logger.error("Aggregator did not become ready in time")
    return False


async def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("Event Publisher Starting")
    logger.info("=" * 60)
    logger.info(f"Target URL: {settings.target_url}")
    logger.info(f"Event count: {settings.event_count}")
    logger.info(f"Duplicate rate: {settings.duplicate_rate * 100}%")
    logger.info(f"Batch size: {settings.batch_size}")
    logger.info("=" * 60)
    
    # Wait for aggregator
    if not await wait_for_aggregator(settings.target_url):
        logger.error("Exiting: Aggregator not available")
        return
    
    async with EventPublisher(settings.target_url) as publisher:
        # Run in batch mode
        stats = await publisher.run_batch_mode(
            total_count=settings.event_count,
            batch_size=settings.batch_size
        )
        
        # Print summary
        logger.info("=" * 60)
        logger.info("Publishing Complete - Summary")
        logger.info("=" * 60)
        logger.info(f"Total events sent: {stats.total_sent}")
        logger.info(f"Successful: {stats.successful}")
        logger.info(f"Failed: {stats.failed}")
        logger.info(f"Unique events: {stats.unique_events}")
        logger.info(f"Duplicates sent: {stats.duplicates_sent}")
        logger.info(f"Duration: {stats.duration:.2f} seconds")
        logger.info(f"Throughput: {stats.events_per_second:.2f} events/sec")
        logger.info("=" * 60)
        
        # Get final stats from aggregator
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{settings.target_url}/stats")
                if response.status_code == 200:
                    aggregator_stats = response.json()
                    logger.info("Aggregator Stats:")
                    logger.info(f"  Received: {aggregator_stats.get('received')}")
                    logger.info(f"  Unique Processed: {aggregator_stats.get('unique_processed')}")
                    logger.info(f"  Duplicates Dropped: {aggregator_stats.get('duplicate_dropped')}")
                    logger.info(f"  Topics: {aggregator_stats.get('topics')}")
        except Exception as e:
            logger.error(f"Failed to get aggregator stats: {e}")


if __name__ == "__main__":
    asyncio.run(main())
