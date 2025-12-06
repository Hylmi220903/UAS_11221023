/**
 * K6 Stress Test for Deduplication Performance
 * Tests high duplicate rate scenarios
 * 
 * Usage:
 *   k6 run k6/stress_dedup.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate } from 'k6/metrics';
import { SharedArray } from 'k6/data';

// Custom metrics
const duplicatesHandled = new Counter('duplicates_handled');
const uniqueProcessed = new Counter('unique_processed');
const dedupSuccessRate = new Rate('dedup_success_rate');

// Test options
export const options = {
    scenarios: {
        // Scenario 1: High duplicate rate
        high_duplicates: {
            executor: 'constant-vus',
            vus: 20,
            duration: '2m',
            exec: 'highDuplicateTest',
        },
        // Scenario 2: Burst traffic
        burst_traffic: {
            executor: 'ramping-arrival-rate',
            startRate: 10,
            timeUnit: '1s',
            preAllocatedVUs: 50,
            maxVUs: 100,
            stages: [
                { duration: '30s', target: 100 },
                { duration: '1m', target: 100 },
                { duration: '30s', target: 10 },
            ],
            startTime: '2m30s',
            exec: 'burstTest',
        },
    },
    thresholds: {
        http_req_duration: ['p(95)<1000'],
        dedup_success_rate: ['rate>0.99'],
    },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

// Pre-generate events for duplicate testing
const preGeneratedEvents = new SharedArray('events', function () {
    const events = [];
    for (let i = 0; i < 100; i++) {
        events.push({
            topic: `stress-topic-${i % 5}`,
            event_id: `evt-stress-${i}-${Date.now()}`,
            timestamp: new Date().toISOString(),
            source: `stress-source-${i % 3}`,
            payload: { stress_test: true, index: i },
        });
    }
    return events;
});

/**
 * High duplicate rate test
 */
export function highDuplicateTest() {
    // Always pick from pre-generated events to create duplicates
    const event = preGeneratedEvents[Math.floor(Math.random() * preGeneratedEvents.length)];
    
    const res = http.post(
        `${BASE_URL}/publish`,
        JSON.stringify(event),
        { headers: { 'Content-Type': 'application/json' } }
    );
    
    const success = check(res, {
        'status is 200': (r) => r.status === 200,
        'response has is_duplicate field': (r) => r.json().is_duplicate !== undefined,
    });
    
    dedupSuccessRate.add(success);
    
    if (res.status === 200) {
        const data = res.json();
        if (data.is_duplicate) {
            duplicatesHandled.add(1);
        } else {
            uniqueProcessed.add(1);
        }
    }
    
    sleep(0.05);
}

/**
 * Burst traffic test with mixed events
 */
export function burstTest() {
    const isDuplicate = Math.random() < 0.5;
    let event;
    
    if (isDuplicate && preGeneratedEvents.length > 0) {
        event = preGeneratedEvents[Math.floor(Math.random() * preGeneratedEvents.length)];
    } else {
        event = {
            topic: `burst-topic-${Math.floor(Math.random() * 10)}`,
            event_id: `evt-burst-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            timestamp: new Date().toISOString(),
            source: 'burst-source',
            payload: { burst_test: true },
        };
    }
    
    const res = http.post(
        `${BASE_URL}/publish`,
        JSON.stringify(event),
        { headers: { 'Content-Type': 'application/json' } }
    );
    
    check(res, {
        'burst request successful': (r) => r.status === 200,
    });
}

/**
 * Setup
 */
export function setup() {
    console.log('Starting dedup stress test...');
    
    const healthRes = http.get(`${BASE_URL}/health`);
    if (healthRes.status !== 200) {
        throw new Error('Aggregator not healthy');
    }
    
    return { startTime: Date.now() };
}

/**
 * Teardown
 */
export function teardown(data) {
    const duration = (Date.now() - data.startTime) / 1000;
    console.log(`Test completed in ${duration.toFixed(2)} seconds`);
    
    const statsRes = http.get(`${BASE_URL}/stats`);
    if (statsRes.status === 200) {
        const stats = statsRes.json();
        console.log('Final Stats:');
        console.log(`  Received: ${stats.received}`);
        console.log(`  Unique: ${stats.unique_processed}`);
        console.log(`  Duplicates: ${stats.duplicate_dropped}`);
    }
}
