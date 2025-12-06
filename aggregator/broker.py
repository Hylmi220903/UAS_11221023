"""
Log Aggregator - Redis Broker Module
Handles message queue operations using Redis
"""
import redis.asyncio as redis
import json
import logging
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
import asyncio

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class Broker:
    """
    Redis-based message broker untuk event queue.
    Supports at-least-once delivery dengan acknowledgment.
    """
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self._connected = False
        self._processing = False
    
    async def connect(self) -> None:
        """Initialize Redis connection"""
        if self.redis is not None:
            return
        
        try:
            self.redis = redis.from_url(
                settings.broker_url,
                max_connections=settings.redis_max_connections,
                decode_responses=True
            )
            # Test connection
            await self.redis.ping()
            self._connected = True
            logger.info("Redis broker connected")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close Redis connection"""
        self._processing = False
        if self.redis:
            await self.redis.close()
            self.redis = None
            self._connected = False
            logger.info("Redis broker disconnected")
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self.redis is not None
    
    async def publish_event(self, event: Dict[str, Any]) -> bool:
        """
        Publish event to queue.
        Uses LPUSH for FIFO ordering when consumed with BRPOP.
        """
        try:
            event_json = json.dumps(event, default=str)
            await self.redis.lpush(settings.event_queue_name, event_json)
            logger.debug(f"Event published: {event.get('event_id')}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            return False
    
    async def publish_batch(self, events: List[Dict[str, Any]]) -> int:
        """Publish multiple events atomically using pipeline"""
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                for event in events:
                    event_json = json.dumps(event, default=str)
                    pipe.lpush(settings.event_queue_name, event_json)
                await pipe.execute()
            logger.info(f"Batch of {len(events)} events published")
            return len(events)
        except Exception as e:
            logger.error(f"Failed to publish batch: {e}")
            return 0
    
    async def consume_event(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """
        Consume single event from queue with blocking.
        Uses BRPOP for at-least-once delivery.
        """
        try:
            result = await self.redis.brpop(settings.event_queue_name, timeout=timeout)
            if result:
                _, event_json = result
                event = json.loads(event_json)
                return event
            return None
        except Exception as e:
            logger.error(f"Failed to consume event: {e}")
            return None
    
    async def get_queue_size(self) -> int:
        """Get current queue size"""
        try:
            return await self.redis.llen(settings.event_queue_name)
        except Exception as e:
            logger.error(f"Failed to get queue size: {e}")
            return 0
    
    async def move_to_dead_letter(self, event: Dict[str, Any], error: str) -> None:
        """Move failed event to dead letter queue"""
        try:
            event['_error'] = error
            event['_failed_at'] = datetime.utcnow().isoformat()
            event_json = json.dumps(event, default=str)
            await self.redis.lpush(settings.dead_letter_queue_name, event_json)
            logger.warning(f"Event moved to dead letter queue: {event.get('event_id')}")
        except Exception as e:
            logger.error(f"Failed to move to dead letter queue: {e}")
    
    async def health_check(self) -> bool:
        """Check Redis connectivity"""
        try:
            await self.redis.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    async def start_worker(
        self,
        process_func: Callable[[Dict[str, Any]], Any],
        worker_id: str = "worker-1"
    ) -> None:
        """
        Start background worker to process events from queue.
        Implements at-least-once delivery with retry logic.
        """
        self._processing = True
        logger.info(f"Worker {worker_id} started")
        
        while self._processing:
            try:
                event = await self.consume_event(timeout=1.0)
                if event:
                    try:
                        await process_func(event)
                        logger.debug(f"Worker {worker_id} processed: {event.get('event_id')}")
                    except Exception as e:
                        logger.error(f"Worker {worker_id} failed to process event: {e}")
                        # Retry with backoff or move to dead letter
                        retries = event.get('_retries', 0)
                        if retries < settings.max_retries:
                            event['_retries'] = retries + 1
                            await self.publish_event(event)
                            await asyncio.sleep(settings.retry_delay_seconds * (settings.retry_backoff_multiplier ** retries))
                        else:
                            await self.move_to_dead_letter(event, str(e))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"Worker {worker_id} stopped")
    
    def stop_workers(self) -> None:
        """Signal workers to stop"""
        self._processing = False


# Global broker instance
broker = Broker()


async def get_broker() -> Broker:
    """Dependency injection for broker"""
    if not broker.is_connected:
        await broker.connect()
    return broker
