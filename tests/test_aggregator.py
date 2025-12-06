"""
Tests for Log Aggregator
Comprehensive test suite covering dedup, persistence, concurrency, and API validation
"""
import pytest
import asyncio
import httpx
import uuid
import time
from datetime import datetime
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import threading

# Test configuration
BASE_URL = "http://localhost:8080"
TIMEOUT = 30.0


@pytest.fixture(scope="module")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def base_url():
    """Base URL for API requests"""
    return BASE_URL


@pytest.fixture
def sample_event() -> Dict[str, Any]:
    """Generate a sample event for testing"""
    return {
        "topic": "test-topic",
        "event_id": f"evt-{uuid.uuid4()}",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "test-service",
        "payload": {
            "level": "INFO",
            "message": "Test message",
            "test_id": str(uuid.uuid4())[:8]
        }
    }


@pytest.fixture
def duplicate_events(sample_event) -> List[Dict[str, Any]]:
    """Generate duplicate events with same topic and event_id"""
    return [sample_event.copy() for _ in range(5)]


class TestEventSchemaValidation:
    """Test event schema validation (Tests 1-3)"""
    
    def test_01_valid_event_accepted(self, base_url, sample_event):
        """Test 1: Valid event should be accepted"""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(f"{base_url}/publish", json=sample_event)
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["event_id"] == sample_event["event_id"]
    
    def test_02_invalid_event_rejected_missing_topic(self, base_url, sample_event):
        """Test 2: Event without topic should be rejected"""
        invalid_event = sample_event.copy()
        del invalid_event["topic"]
        
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(f"{base_url}/publish", json=invalid_event)
            assert response.status_code == 422  # Validation error
    
    def test_03_invalid_event_rejected_short_event_id(self, base_url, sample_event):
        """Test 3: Event with too short event_id should be rejected"""
        invalid_event = sample_event.copy()
        invalid_event["event_id"] = "short"  # Less than 8 characters
        
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(f"{base_url}/publish", json=invalid_event)
            assert response.status_code == 422  # Validation error


class TestIdempotencyAndDeduplication:
    """Test idempotency and deduplication (Tests 4-7)"""
    
    def test_04_duplicate_event_detected(self, base_url, sample_event):
        """Test 4: Duplicate event should be detected and marked"""
        with httpx.Client(timeout=TIMEOUT) as client:
            # First publish
            response1 = client.post(f"{base_url}/publish", json=sample_event)
            assert response1.status_code == 200
            data1 = response1.json()
            assert data1["is_duplicate"] is False
            
            # Second publish (duplicate)
            response2 = client.post(f"{base_url}/publish", json=sample_event)
            assert response2.status_code == 200
            data2 = response2.json()
            assert data2["is_duplicate"] is True
    
    def test_05_multiple_duplicates_only_one_processed(self, base_url):
        """Test 5: Multiple duplicates should result in only one processed event"""
        event = {
            "topic": "dedup-test",
            "event_id": f"evt-dedup-{uuid.uuid4()}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {"test": "dedup"}
        }
        
        with httpx.Client(timeout=TIMEOUT) as client:
            # Get initial stats
            stats_before = client.get(f"{base_url}/stats").json()
            initial_unique = stats_before["unique_processed"]
            
            # Send same event 10 times
            for _ in range(10):
                client.post(f"{base_url}/publish", json=event)
            
            # Get final stats
            stats_after = client.get(f"{base_url}/stats").json()
            final_unique = stats_after["unique_processed"]
            
            # Should only have increased by 1
            assert final_unique == initial_unique + 1
    
    def test_06_batch_deduplication(self, base_url):
        """Test 6: Batch with duplicates should only process unique events"""
        unique_id = f"evt-batch-{uuid.uuid4()}"
        events = [
            {
                "topic": "batch-dedup-test",
                "event_id": unique_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "source": "test-service",
                "payload": {"batch": i}
            }
            for i in range(5)  # 5 identical events
        ]
        
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(f"{base_url}/publish/batch", json={"events": events})
            assert response.status_code == 200
            data = response.json()
            assert data["unique_processed"] == 1
            assert data["duplicates_dropped"] == 4
    
    def test_07_different_topics_same_event_id(self, base_url):
        """Test 7: Same event_id in different topics should both be processed"""
        event_id = f"evt-multitopic-{uuid.uuid4()}"
        
        event1 = {
            "topic": "topic-a",
            "event_id": event_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {"topic": "a"}
        }
        
        event2 = {
            "topic": "topic-b",
            "event_id": event_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {"topic": "b"}
        }
        
        with httpx.Client(timeout=TIMEOUT) as client:
            response1 = client.post(f"{base_url}/publish", json=event1)
            assert response1.json()["is_duplicate"] is False
            
            response2 = client.post(f"{base_url}/publish", json=event2)
            assert response2.json()["is_duplicate"] is False


class TestConcurrencyAndTransactions:
    """Test concurrency and transaction handling (Tests 8-11)"""
    
    def test_08_concurrent_same_event_no_race_condition(self, base_url):
        """Test 8: Concurrent publishing of same event should not cause race condition"""
        event = {
            "topic": "concurrent-test",
            "event_id": f"evt-concurrent-{uuid.uuid4()}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {"concurrent": True}
        }
        
        results = []
        
        def publish_event():
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(f"{BASE_URL}/publish", json=event)
                results.append(response.json())
        
        # Run 10 concurrent requests
        threads = [threading.Thread(target=publish_event) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Exactly one should be non-duplicate
        non_duplicates = sum(1 for r in results if not r.get("is_duplicate", True))
        duplicates = sum(1 for r in results if r.get("is_duplicate", False))
        
        assert non_duplicates == 1
        assert duplicates == 9
    
    def test_09_concurrent_batch_atomic_transaction(self, base_url):
        """Test 9: Concurrent batch operations maintain transaction atomicity"""
        batch_id = str(uuid.uuid4())[:8]
        
        def send_batch(batch_num: int):
            events = [
                {
                    "topic": f"concurrent-batch-{batch_id}",
                    "event_id": f"evt-cb-{batch_num}-{i}-{uuid.uuid4()}",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "source": "test-service",
                    "payload": {"batch": batch_num, "item": i}
                }
                for i in range(10)
            ]
            
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(f"{BASE_URL}/publish/batch", json={"events": events})
                return response.json()
        
        # Run 5 concurrent batches
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(send_batch, i) for i in range(5)]
            results = [f.result() for f in futures]
        
        # All batches should succeed
        total_processed = sum(r.get("unique_processed", 0) for r in results)
        assert total_processed == 50  # 5 batches * 10 events each
    
    def test_10_stats_consistency_under_load(self, base_url):
        """Test 10: Statistics remain consistent under concurrent load"""
        with httpx.Client(timeout=TIMEOUT) as client:
            # Get initial stats
            stats_before = client.get(f"{base_url}/stats").json()
            initial_received = stats_before["received"]
            initial_unique = stats_before["unique_processed"]
            initial_dropped = stats_before["duplicate_dropped"]
            
            # Send known number of events with known duplicates
            event_template = {
                "topic": "stats-test",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "source": "test-service",
                "payload": {}
            }
            
            unique_count = 20
            duplicate_per_unique = 3
            
            for i in range(unique_count):
                event = event_template.copy()
                event["event_id"] = f"evt-stats-{uuid.uuid4()}"
                
                # Send original and duplicates
                for _ in range(duplicate_per_unique):
                    client.post(f"{base_url}/publish", json=event)
            
            # Get final stats
            stats_after = client.get(f"{base_url}/stats").json()
            
            expected_total_received = unique_count * duplicate_per_unique
            actual_received_diff = stats_after["received"] - initial_received
            actual_unique_diff = stats_after["unique_processed"] - initial_unique
            actual_dropped_diff = stats_after["duplicate_dropped"] - initial_dropped
            
            assert actual_received_diff == expected_total_received
            assert actual_unique_diff == unique_count
            assert actual_dropped_diff == unique_count * (duplicate_per_unique - 1)
    
    def test_11_multi_worker_no_double_processing(self, base_url):
        """Test 11: Multiple workers should not double-process events"""
        # This test verifies that even with multiple workers, 
        # each event is processed exactly once
        
        event_id = f"evt-worker-{uuid.uuid4()}"
        event = {
            "topic": "worker-test",
            "event_id": event_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {"worker_test": True}
        }
        
        with httpx.Client(timeout=TIMEOUT) as client:
            # Publish event via queue (workers will process)
            response = client.post(f"{base_url}/publish/queue", json=event)
            assert response.status_code == 200
            
            # Wait for processing
            time.sleep(2)
            
            # Try to publish same event again via queue
            client.post(f"{base_url}/publish/queue", json=event)
            
            # Wait for processing
            time.sleep(2)
            
            # Check events - should only have one
            events_response = client.get(f"{base_url}/events", params={"topic": "worker-test"})
            events = events_response.json()["events"]
            
            matching = [e for e in events if e["event_id"] == event_id]
            assert len(matching) <= 1


class TestAPIEndpoints:
    """Test API endpoints functionality (Tests 12-14)"""
    
    def test_12_get_events_returns_processed_events(self, base_url, sample_event):
        """Test 12: GET /events returns processed events"""
        # First publish an event
        sample_event["topic"] = "get-events-test"
        sample_event["event_id"] = f"evt-get-{uuid.uuid4()}"
        
        with httpx.Client(timeout=TIMEOUT) as client:
            client.post(f"{base_url}/publish", json=sample_event)
            
            # Get events for topic
            response = client.get(
                f"{base_url}/events",
                params={"topic": "get-events-test"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert len(data["events"]) > 0
            
            # Find our event
            found = any(
                e["event_id"] == sample_event["event_id"]
                for e in data["events"]
            )
            assert found
    
    def test_13_get_stats_returns_valid_statistics(self, base_url):
        """Test 13: GET /stats returns valid statistics structure"""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{base_url}/stats")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify all required fields
            assert "received" in data
            assert "unique_processed" in data
            assert "duplicate_dropped" in data
            assert "topics" in data
            assert "uptime_seconds" in data
            assert "uptime_formatted" in data
            
            # Verify types
            assert isinstance(data["received"], int)
            assert isinstance(data["unique_processed"], int)
            assert isinstance(data["duplicate_dropped"], int)
            assert isinstance(data["topics"], list)
            assert isinstance(data["uptime_seconds"], (int, float))
    
    def test_14_health_endpoint_returns_status(self, base_url):
        """Test 14: Health endpoint returns proper status"""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{base_url}/health")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "status" in data
            assert "database" in data
            assert "broker" in data
            assert "uptime_seconds" in data
            assert "version" in data


class TestPersistence:
    """Test data persistence (Tests 15-16)"""
    
    def test_15_events_persist_after_query(self, base_url):
        """Test 15: Events can be retrieved after being published"""
        event = {
            "topic": "persistence-test",
            "event_id": f"evt-persist-{uuid.uuid4()}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {"persist_test": True}
        }
        
        with httpx.Client(timeout=TIMEOUT) as client:
            # Publish
            client.post(f"{base_url}/publish", json=event)
            
            # Query multiple times
            for _ in range(3):
                response = client.get(
                    f"{base_url}/events",
                    params={"topic": "persistence-test"}
                )
                events = response.json()["events"]
                found = any(e["event_id"] == event["event_id"] for e in events)
                assert found
                time.sleep(0.1)
    
    def test_16_dedup_state_persists(self, base_url):
        """Test 16: Deduplication state persists across requests"""
        event = {
            "topic": "dedup-persist-test",
            "event_id": f"evt-dedup-persist-{uuid.uuid4()}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {"dedup_persist": True}
        }
        
        with httpx.Client(timeout=TIMEOUT) as client:
            # First publish - should be new
            response1 = client.post(f"{base_url}/publish", json=event)
            assert response1.json()["is_duplicate"] is False
            
            # Wait a bit
            time.sleep(1)
            
            # Second publish - should be duplicate (state persisted)
            response2 = client.post(f"{base_url}/publish", json=event)
            assert response2.json()["is_duplicate"] is True


class TestStressAndPerformance:
    """Stress and performance tests (Tests 17-18)"""
    
    def test_17_batch_performance(self, base_url):
        """Test 17: Batch processing handles large batches efficiently"""
        events = [
            {
                "topic": "stress-test",
                "event_id": f"evt-stress-{uuid.uuid4()}",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "source": "stress-test-service",
                "payload": {"item": i}
            }
            for i in range(500)
        ]
        
        with httpx.Client(timeout=60.0) as client:
            start_time = time.time()
            response = client.post(f"{base_url}/publish/batch", json={"events": events})
            duration = time.time() - start_time
            
            assert response.status_code == 200
            data = response.json()
            assert data["total_received"] == 500
            assert data["unique_processed"] == 500
            
            # Should complete in reasonable time (< 30 seconds)
            assert duration < 30
    
    def test_18_high_duplicate_rate_handling(self, base_url):
        """Test 18: System handles high duplicate rate efficiently"""
        # Create 100 unique events, send each 5 times = 500 total, 80% duplicates
        unique_events = [
            {
                "topic": "high-dup-test",
                "event_id": f"evt-highdup-{uuid.uuid4()}",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "source": "dup-test-service",
                "payload": {"unique_id": i}
            }
            for i in range(100)
        ]
        
        # Expand with duplicates
        all_events = []
        for event in unique_events:
            all_events.extend([event.copy() for _ in range(5)])
        
        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{base_url}/publish/batch", json={"events": all_events})
            
            assert response.status_code == 200
            data = response.json()
            assert data["total_received"] == 500
            assert data["unique_processed"] == 100
            assert data["duplicates_dropped"] == 400


class TestEdgeCases:
    """Edge case tests (Tests 19-20)"""
    
    def test_19_empty_payload_accepted(self, base_url):
        """Test 19: Event with empty payload should be accepted"""
        event = {
            "topic": "empty-payload-test",
            "event_id": f"evt-empty-{uuid.uuid4()}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {}
        }
        
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(f"{base_url}/publish", json=event)
            assert response.status_code == 200
            assert response.json()["success"] is True
    
    def test_20_special_characters_in_topic(self, base_url):
        """Test 20: Topic with allowed special characters should work"""
        event = {
            "topic": "test-topic_v2.logs",
            "event_id": f"evt-special-{uuid.uuid4()}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "test-service",
            "payload": {"test": "special_chars"}
        }
        
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(f"{base_url}/publish", json=event)
            assert response.status_code == 200
            assert response.json()["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
