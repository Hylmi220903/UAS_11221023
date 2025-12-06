-- Database initialization script for Log Aggregator
-- Creates tables with proper constraints for idempotency and deduplication

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create events table with unique constraint for deduplication
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    source VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    received_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ,
    
    -- Unique constraint untuk deduplication (topic, event_id)
    CONSTRAINT unique_topic_event UNIQUE (topic, event_id)
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_events_topic ON events(topic);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_received_at ON events(received_at);

-- Create processed_events table for tracking processed events (dedup store)
CREATE TABLE IF NOT EXISTS processed_events (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    worker_id VARCHAR(100),
    
    -- Unique constraint untuk idempotent processing
    CONSTRAINT unique_processed_event UNIQUE (topic, event_id)
);

CREATE INDEX IF NOT EXISTS idx_processed_topic ON processed_events(topic);

-- Create statistics table for atomic counter updates
CREATE TABLE IF NOT EXISTS statistics (
    id SERIAL PRIMARY KEY,
    stat_key VARCHAR(100) UNIQUE NOT NULL,
    stat_value BIGINT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Initialize statistics
INSERT INTO statistics (stat_key, stat_value) VALUES 
    ('received', 0),
    ('unique_processed', 0),
    ('duplicate_dropped', 0)
ON CONFLICT (stat_key) DO NOTHING;

-- Create audit_log table for tracking all operations
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    operation VARCHAR(50) NOT NULL,
    topic VARCHAR(255),
    event_id VARCHAR(255),
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at);

-- Create outbox table for outbox pattern (optional but implemented)
CREATE TABLE IF NOT EXISTS outbox (
    id SERIAL PRIMARY KEY,
    event_topic VARCHAR(255) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ,
    
    CONSTRAINT unique_outbox_event UNIQUE (event_topic, event_id)
);

CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);

-- Function to atomically increment statistics
CREATE OR REPLACE FUNCTION increment_stat(key_name VARCHAR, increment_by BIGINT DEFAULT 1)
RETURNS BIGINT AS $$
DECLARE
    new_value BIGINT;
BEGIN
    UPDATE statistics 
    SET stat_value = stat_value + increment_by,
        updated_at = CURRENT_TIMESTAMP
    WHERE stat_key = key_name
    RETURNING stat_value INTO new_value;
    
    RETURN new_value;
END;
$$ LANGUAGE plpgsql;

-- Function for idempotent event insert (returns true if new, false if duplicate)
CREATE OR REPLACE FUNCTION insert_event_idempotent(
    p_topic VARCHAR,
    p_event_id VARCHAR,
    p_timestamp TIMESTAMPTZ,
    p_source VARCHAR,
    p_payload JSONB
) RETURNS BOOLEAN AS $$
DECLARE
    inserted BOOLEAN := FALSE;
BEGIN
    -- Try to insert, catch unique violation
    INSERT INTO events (topic, event_id, timestamp, source, payload)
    VALUES (p_topic, p_event_id, p_timestamp, p_source, p_payload)
    ON CONFLICT (topic, event_id) DO NOTHING;
    
    -- Check if insert happened
    GET DIAGNOSTICS inserted = ROW_COUNT;
    
    RETURN inserted > 0;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO aggregator_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO aggregator_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO aggregator_user;
