"""
Log Aggregator - Database Module
Handles PostgreSQL connections and operations with transaction support
"""
import asyncpg
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from contextlib import asynccontextmanager
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class Database:
    """
    Database class dengan connection pooling dan transaction support
    Menggunakan asyncpg untuk async PostgreSQL operations
    """
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self._connected = False
    
    async def connect(self) -> None:
        """Initialize connection pool"""
        if self.pool is not None:
            return
        
        async def init_connection(conn):
            """Configure JSON codec for JSONB columns"""
            await conn.set_type_codec(
                'jsonb',
                encoder=json.dumps,
                decoder=json.loads,
                schema='pg_catalog'
            )
            await conn.set_type_codec(
                'json',
                encoder=json.dumps,
                decoder=json.loads,
                schema='pg_catalog'
            )
        
        try:
            self.pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=settings.db_pool_min_size,
                max_size=settings.db_pool_max_size,
                command_timeout=60,
                init=init_connection
            )
            self._connected = True
            logger.info("Database connection pool established")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            self.pool = None
            self._connected = False
            logger.info("Database connection pool closed")
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self.pool is not None
    
    @asynccontextmanager
    async def transaction(self):
        """
        Context manager untuk transaction dengan isolation level READ COMMITTED.
        
        READ COMMITTED dipilih karena:
        1. Mencegah dirty reads
        2. Cukup untuk use case deduplication dengan unique constraints
        3. Performa lebih baik dari SERIALIZABLE
        4. Unique constraints sudah menjamin atomicity untuk insert
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation='read_committed'):
                yield conn
    
    @asynccontextmanager
    async def serializable_transaction(self):
        """
        Transaction dengan SERIALIZABLE isolation untuk operasi kritis.
        Digunakan ketika perlu absolute consistency (jarang dibutuhkan).
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation='serializable'):
                yield conn
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def insert_event_idempotent(
        self,
        topic: str,
        event_id: str,
        timestamp: datetime,
        source: str,
        payload: dict,
        worker_id: str = "main"
    ) -> Tuple[bool, bool]:
        """
        Insert event dengan idempotent pattern menggunakan ON CONFLICT DO NOTHING.
        
        Returns:
            Tuple[bool, bool]: (success, is_new_event)
            - success: True jika operasi berhasil
            - is_new_event: True jika event baru, False jika duplikat
        
        Isolation: READ COMMITTED dengan unique constraint
        Pattern: INSERT ... ON CONFLICT DO NOTHING
        """
        async with self.transaction() as conn:
            # Step 1: Try to insert into events table
            result = await conn.execute("""
                INSERT INTO events (topic, event_id, timestamp, source, payload, processed_at)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (topic, event_id) DO NOTHING
            """, topic, event_id, timestamp, source, payload)
            
            # Check if insert happened (result contains "INSERT 0 1" if successful)
            is_new = "INSERT 0 1" in result
            
            if is_new:
                # Step 2: Record in processed_events for tracking
                await conn.execute("""
                    INSERT INTO processed_events (topic, event_id, worker_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (topic, event_id) DO NOTHING
                """, topic, event_id, worker_id)
                
                # Step 3: Update statistics atomically
                await conn.execute("""
                    UPDATE statistics SET stat_value = stat_value + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE stat_key = 'unique_processed'
                """)
                
                # Step 4: Log to audit
                await conn.execute("""
                    INSERT INTO audit_log (operation, topic, event_id, details)
                    VALUES ('INSERT', $1, $2, $3)
                """, topic, event_id, {"source": source, "worker_id": worker_id})
                
                logger.info(f"New event processed: {topic}/{event_id}")
            else:
                # Event is duplicate - update duplicate counter
                await conn.execute("""
                    UPDATE statistics SET stat_value = stat_value + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE stat_key = 'duplicate_dropped'
                """)
                
                await conn.execute("""
                    INSERT INTO audit_log (operation, topic, event_id, details)
                    VALUES ('DUPLICATE', $1, $2, $3)
                """, topic, event_id, {"worker_id": worker_id})
                
                logger.info(f"Duplicate event dropped: {topic}/{event_id}")
            
            # Always increment received counter
            await conn.execute("""
                UPDATE statistics SET stat_value = stat_value + 1, updated_at = CURRENT_TIMESTAMP
                WHERE stat_key = 'received'
            """)
            
            return True, is_new
    
    async def batch_insert_events_atomic(
        self,
        events: List[Dict[str, Any]],
        worker_id: str = "main"
    ) -> Tuple[int, int, int]:
        """
        Batch insert dengan atomic transaction.
        Seluruh batch berhasil atau gagal bersama.
        
        Returns:
            Tuple[int, int, int]: (total, new_count, duplicate_count)
        """
        new_count = 0
        duplicate_count = 0
        
        async with self.transaction() as conn:
            for event in events:
                result = await conn.execute("""
                    INSERT INTO events (topic, event_id, timestamp, source, payload, processed_at)
                    VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                    ON CONFLICT (topic, event_id) DO NOTHING
                """, event['topic'], event['event_id'], event['timestamp'], 
                    event['source'], event['payload'])
                
                if "INSERT 0 1" in result:
                    new_count += 1
                    await conn.execute("""
                        INSERT INTO processed_events (topic, event_id, worker_id)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (topic, event_id) DO NOTHING
                    """, event['topic'], event['event_id'], worker_id)
                else:
                    duplicate_count += 1
            
            # Update statistics atomically for entire batch
            total = len(events)
            await conn.execute("""
                UPDATE statistics SET stat_value = stat_value + $1, updated_at = CURRENT_TIMESTAMP
                WHERE stat_key = 'received'
            """, total)
            
            await conn.execute("""
                UPDATE statistics SET stat_value = stat_value + $1, updated_at = CURRENT_TIMESTAMP
                WHERE stat_key = 'unique_processed'
            """, new_count)
            
            await conn.execute("""
                UPDATE statistics SET stat_value = stat_value + $1, updated_at = CURRENT_TIMESTAMP
                WHERE stat_key = 'duplicate_dropped'
            """, duplicate_count)
            
            logger.info(f"Batch processed: {total} total, {new_count} new, {duplicate_count} duplicates")
            
            return total, new_count, duplicate_count
    
    async def get_events(
        self,
        topic: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get events, optionally filtered by topic"""
        async with self.pool.acquire() as conn:
            if topic:
                rows = await conn.fetch("""
                    SELECT topic, event_id, timestamp, source, payload, received_at, processed_at
                    FROM events
                    WHERE topic = $1
                    ORDER BY timestamp DESC
                    LIMIT $2 OFFSET $3
                """, topic, limit, offset)
            else:
                rows = await conn.fetch("""
                    SELECT topic, event_id, timestamp, source, payload, received_at, processed_at
                    FROM events
                    ORDER BY timestamp DESC
                    LIMIT $1 OFFSET $2
                """, limit, offset)
            
            return [dict(row) for row in rows]
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get aggregated statistics"""
        async with self.pool.acquire() as conn:
            # Get basic stats
            stats_rows = await conn.fetch("""
                SELECT stat_key, stat_value FROM statistics
            """)
            stats = {row['stat_key']: row['stat_value'] for row in stats_rows}
            
            # Get unique topics
            topics_rows = await conn.fetch("""
                SELECT DISTINCT topic FROM events ORDER BY topic
            """)
            topics = [row['topic'] for row in topics_rows]
            
            # Get topic counts
            topic_counts_rows = await conn.fetch("""
                SELECT topic, COUNT(*) as count FROM events GROUP BY topic ORDER BY count DESC
            """)
            topic_counts = {row['topic']: row['count'] for row in topic_counts_rows}
            
            return {
                'received': stats.get('received', 0),
                'unique_processed': stats.get('unique_processed', 0),
                'duplicate_dropped': stats.get('duplicate_dropped', 0),
                'topics': topics,
                'topic_counts': topic_counts
            }
    
    async def check_event_exists(self, topic: str, event_id: str) -> bool:
        """Check if event already exists (for pre-check deduplication)"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 1 FROM events WHERE topic = $1 AND event_id = $2
            """, topic, event_id)
            return row is not None
    
    async def health_check(self) -> bool:
        """Check database connectivity"""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


# Global database instance
db = Database()


async def get_database() -> Database:
    """Dependency injection for database"""
    if not db.is_connected:
        await db.connect()
    return db
