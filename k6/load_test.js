/**
 * K6 Load Test Script for Log Aggregator
 * Tests throughput, latency, and deduplication under load
 * 
 * Usage:
 *   k6 run k6/load_test.js
 *   k6 run --vus 50 --duration 60s k6/load_test.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { randomString } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

// Custom metrics
const eventsPublished = new Counter('events_published');
const duplicatesSent = new Counter('duplicates_sent');
const successRate = new Rate('success_rate');
const publishLatency = new Trend('publish_latency');
const batchLatency = new Trend('batch_latency');

// Test configuration
export const options = {
    stages: [
        { duration: '30s', target: 10 },   // Ramp up to 10 VUs
        { duration: '1m', target: 50 },    // Ramp up to 50 VUs
        { duration: '2m', target: 50 },    // Stay at 50 VUs
        { duration: '30s', target: 100 },  // Peak at 100 VUs
        { duration: '1m', target: 100 },   // Stay at peak
        { duration: '30s', target: 0 },    // Ramp down
    ],
    thresholds: {
        http_req_duration: ['p(95)<500'],  // 95% of requests under 500ms
        success_rate: ['rate>0.95'],        // 95% success rate
        http_req_failed: ['rate<0.05'],     // Less than 5% failures
    },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

// Topics for testing
const TOPICS = ['app-logs', 'security-logs', 'system-logs', 'audit-logs', 'perf-logs'];
const SOURCES = ['service-a', 'service-b', 'service-c', 'gateway', 'worker'];

// Cache for duplicate generation
let previousEvents = [];

/**
 * Generate a unique event
 */
function generateEvent() {
    const event = {
        topic: TOPICS[Math.floor(Math.random() * TOPICS.length)],
        event_id: `evt-${randomString(8)}-${Date.now()}`,
        timestamp: new Date().toISOString(),
        source: SOURCES[Math.floor(Math.random() * SOURCES.length)],
        payload: {
            level: ['DEBUG', 'INFO', 'WARNING', 'ERROR'][Math.floor(Math.random() * 4)],
            message: `Test message ${randomString(16)}`,
            request_id: randomString(8),
            user_id: `user-${Math.floor(Math.random() * 10000)}`,
            duration_ms: Math.floor(Math.random() * 500),
        },
    };
    
    // Store for potential duplication
    if (previousEvents.length < 100) {
        previousEvents.push(event);
    }
    
    return event;
}

/**
 * Generate a duplicate event (30% chance)
 */
function generateEventWithDuplicates() {
    if (previousEvents.length > 0 && Math.random() < 0.3) {
        duplicatesSent.add(1);
        return previousEvents[Math.floor(Math.random() * previousEvents.length)];
    }
    return generateEvent();
}

/**
 * Generate batch of events
 */
function generateBatch(size) {
    const events = [];
    for (let i = 0; i < size; i++) {
        events.push(generateEventWithDuplicates());
    }
    return { events };
}

/**
 * Setup function - runs once before the test
 */
export function setup() {
    console.log('Starting load test against:', BASE_URL);
    
    // Check health endpoint
    const healthRes = http.get(`${BASE_URL}/health`);
    check(healthRes, {
        'health check passed': (r) => r.status === 200,
    });
    
    // Get initial stats
    const statsRes = http.get(`${BASE_URL}/stats`);
    const initialStats = statsRes.json();
    
    return { initialStats };
}

/**
 * Main test function
 */
export default function() {
    group('Single Event Publishing', function() {
        const event = generateEventWithDuplicates();
        
        const startTime = new Date();
        const res = http.post(
            `${BASE_URL}/publish`,
            JSON.stringify(event),
            { headers: { 'Content-Type': 'application/json' } }
        );
        const duration = new Date() - startTime;
        
        publishLatency.add(duration);
        eventsPublished.add(1);
        
        const success = check(res, {
            'single publish success': (r) => r.status === 200,
            'response has event_id': (r) => r.json().event_id !== undefined,
        });
        
        successRate.add(success);
    });
    
    sleep(0.1);
    
    group('Batch Event Publishing', function() {
        const batch = generateBatch(20);
        
        const startTime = new Date();
        const res = http.post(
            `${BASE_URL}/publish/batch`,
            JSON.stringify(batch),
            { headers: { 'Content-Type': 'application/json' } }
        );
        const duration = new Date() - startTime;
        
        batchLatency.add(duration);
        eventsPublished.add(batch.events.length);
        
        const success = check(res, {
            'batch publish success': (r) => r.status === 200,
            'batch processed count': (r) => r.json().total_received === batch.events.length,
        });
        
        successRate.add(success);
    });
    
    sleep(0.1);
    
    // Occasionally check stats
    if (Math.random() < 0.1) {
        group('Stats Check', function() {
            const res = http.get(`${BASE_URL}/stats`);
            
            check(res, {
                'stats endpoint success': (r) => r.status === 200,
                'has received count': (r) => r.json().received !== undefined,
                'has unique processed': (r) => r.json().unique_processed !== undefined,
            });
        });
    }
}

/**
 * Teardown function - runs once after the test
 */
export function teardown(data) {
    console.log('Load test completed');
    
    // Get final stats
    const statsRes = http.get(`${BASE_URL}/stats`);
    const finalStats = statsRes.json();
    
    console.log('='.repeat(60));
    console.log('Final Statistics:');
    console.log(`  Total Received: ${finalStats.received}`);
    console.log(`  Unique Processed: ${finalStats.unique_processed}`);
    console.log(`  Duplicates Dropped: ${finalStats.duplicate_dropped}`);
    console.log(`  Topics: ${finalStats.topics.join(', ')}`);
    console.log(`  Queue Size: ${finalStats.queue_size}`);
    console.log('='.repeat(60));
    
    // Calculate changes
    const receivedDiff = finalStats.received - data.initialStats.received;
    const uniqueDiff = finalStats.unique_processed - data.initialStats.unique_processed;
    const dupDiff = finalStats.duplicate_dropped - data.initialStats.duplicate_dropped;
    
    console.log('Changes during test:');
    console.log(`  New events received: ${receivedDiff}`);
    console.log(`  New unique processed: ${uniqueDiff}`);
    console.log(`  New duplicates dropped: ${dupDiff}`);
    console.log(`  Dedup rate: ${((dupDiff / receivedDiff) * 100).toFixed(2)}%`);
}
