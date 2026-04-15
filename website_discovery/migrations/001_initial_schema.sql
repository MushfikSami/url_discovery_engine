-- ============================================
-- URL Discovery Service - Initial Schema Migration
-- Version: 1.0.0
-- ============================================

-- Enable UUID extension (optional, for future use)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- Domain Tracking Table
-- ============================================
-- Stores discovered .gov.bd domains with liveness status
CREATE TABLE IF NOT EXISTS domains (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL UNIQUE,
    protocol VARCHAR(10) NOT NULL DEFAULT 'https',
    is_live BOOLEAN NOT NULL DEFAULT TRUE,
    status_code INTEGER,
    response_time INTEGER,  -- Response time in milliseconds
    last_checked TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    rediscovered_at TIMESTAMP WITH TIME ZONE,

    -- Optional metadata
    content_hash VARCHAR(64),
    tags TEXT[]
);

-- ============================================
-- Seed URLs Table
-- ============================================
-- Stores initial URLs used to start discovery
CREATE TABLE IF NOT EXISTS seed_urls (
    id SERIAL PRIMARY KEY,
    url VARCHAR(500) NOT NULL UNIQUE,
    source VARCHAR(50) NOT NULL DEFAULT 'manual',
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- URL Queue Table
-- ============================================
-- Manages URLs pending discovery processing
CREATE TABLE IF NOT EXISTS url_queue (
    id SERIAL PRIMARY KEY,
    url VARCHAR(500) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    scheduled_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    attempts INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    domain VARCHAR(255) REFERENCES domains(domain) ON DELETE SET NULL
);

-- ============================================
-- Discovery Log Table
-- ============================================
-- Audit trail of all discovery actions
CREATE TABLE IF NOT EXISTS discovery_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    action VARCHAR(50) NOT NULL,  -- discovered, checked, failed, etc.
    domain VARCHAR(255) REFERENCES domains(domain) ON DELETE SET NULL,
    details JSONB,
    error_message TEXT
);

-- ============================================
-- Indexes for Performance Optimization
-- ============================================

-- Domain lookups (unique constraint already exists)
CREATE INDEX IF NOT EXISTS idx_domains_domain
    ON domains(domain);

-- Query for live domains only
CREATE INDEX IF NOT EXISTS idx_domains_is_live
    ON domains(is_live);

-- Recently checked domains (for scheduling)
CREATE INDEX IF NOT EXISTS idx_domains_last_checked
    ON domains(last_checked);

-- Hash-based content comparison
CREATE INDEX IF NOT EXISTS idx_domains_content_hash
    ON domains(content_hash)
    WHERE content_hash IS NOT NULL;

-- Partial index for dead domains (for liveness checks)
CREATE INDEX IF NOT EXISTS idx_domains_dead
    ON domains(domain)
    WHERE is_live = FALSE;

-- Seed URL lookups
CREATE INDEX IF NOT EXISTS idx_seed_urls_url
    ON seed_urls(url);

-- Queue processing (pending URLs ordered by priority and time)
CREATE INDEX IF NOT EXISTS idx_url_queue_status_priority
    ON url_queue(status, priority, scheduled_at)
    WHERE status = 'pending';

-- Queue by status only (for cleanup)
CREATE INDEX IF NOT EXISTS idx_url_queue_status
    ON url_queue(status);

-- Discovery log by domain (for historical queries)
CREATE INDEX IF NOT EXISTS idx_discovery_log_domain
    ON discovery_log(domain);

-- Discovery log by timestamp (for recent activity)
CREATE INDEX IF NOT EXISTS idx_discovery_log_timestamp
    ON discovery_log(timestamp);

-- Composite index for status report queries
CREATE INDEX IF NOT EXISTS idx_discovery_log_status
    ON discovery_log(timestamp DESC)
    WHERE domain IS NOT NULL;

-- ============================================
-- Triggers for Automatic Updates
-- ============================================

-- Function to automatically update rediscovered_at timestamp
-- When a domain changes from dead to live
CREATE OR REPLACE FUNCTION update_rediscovered_at()
RETURNS TRIGGER AS $$
BEGIN
    -- Only update when transitioning from dead to live
    IF NEW.is_live = TRUE AND OLD.is_live = FALSE THEN
        NEW.rediscovered_at = CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to call update_rediscovered_at on domain updates
DROP TRIGGER IF EXISTS trigger_update_rediscovered_at ON domains;
CREATE TRIGGER trigger_update_rediscovered_at
    BEFORE UPDATE ON domains
    FOR EACH ROW
    EXECUTE FUNCTION update_rediscovered_at();

-- Function to log domain discoveries automatically
CREATE OR REPLACE FUNCTION log_discovery()
RETURNS TRIGGER AS $$
BEGIN
    -- Log new domain discoveries (always called on INSERT)
    INSERT INTO discovery_log (action, domain, details)
    VALUES ('discovered', NEW.domain,
            jsonb_build_object(
                'protocol', NEW.protocol,
                'is_live', NEW.is_live,
                'source', 'automatic'
            ));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to log domain changes
DROP TRIGGER IF EXISTS trigger_log_discovery ON domains;
CREATE TRIGGER trigger_log_discovery
    AFTER INSERT ON domains
    FOR EACH ROW
    EXECUTE FUNCTION log_discovery();

-- Function to log liveness check results
CREATE OR REPLACE FUNCTION log_liveness_check()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO discovery_log (action, domain, details, error_message)
    VALUES (
        'checked',
        NEW.domain,
        jsonb_build_object(
            'status_code', NEW.status_code,
            'response_time', NEW.response_time,
            'is_live', NEW.is_live
        ),
        CASE WHEN NOT NEW.is_live AND NEW.status_code IS NOT NULL
             THEN 'Status code: ' || NEW.status_code::text
             ELSE NULL
        END
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to log liveness status changes
DROP TRIGGER IF EXISTS trigger_log_liveness_check ON domains;
CREATE TRIGGER trigger_log_liveness_check
    AFTER UPDATE ON domains
    FOR EACH ROW
    WHEN (OLD.is_live IS DISTINCT FROM NEW.is_live)
    EXECUTE FUNCTION log_liveness_check();

-- ============================================
-- Views for Common Queries
-- ============================================

-- View: Live domains with latest check info
CREATE OR REPLACE VIEW v_live_domains AS
SELECT
    d.id,
    d.domain,
    d.protocol,
    d.status_code,
    d.response_time,
    d.last_checked,
    d.discovered_at
FROM domains d
WHERE d.is_live = TRUE
ORDER BY d.last_checked DESC;

-- View: Dead domains needing recheck
CREATE OR REPLACE VIEW v_dead_domains AS
SELECT
    d.id,
    d.domain,
    d.status_code,
    d.last_checked,
    d.rediscovered_at,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - d.last_checked)) as seconds_since_check
FROM domains d
WHERE d.is_live = FALSE
ORDER BY d.last_checked ASC;

-- View: Recent discoveries
CREATE OR REPLACE VIEW v_recent_discoveries AS
SELECT
    d.domain,
    d.protocol,
    d.is_live,
    d.status_code,
    d.discovered_at,
    COUNT(dl.id) as check_count
FROM domains d
LEFT JOIN discovery_log dl ON d.domain = dl.domain AND dl.action = 'checked'
WHERE d.discovered_at > (CURRENT_TIMESTAMP - INTERVAL '7 days')
GROUP BY d.id, d.domain, d.protocol, d.is_live, d.status_code, d.discovered_at
ORDER BY d.discovered_at DESC;

-- View: Discovery statistics
CREATE OR REPLACE VIEW v_discovery_stats AS
SELECT
    COUNT(*) as total_domains,
    SUM(CASE WHEN is_live THEN 1 ELSE 0 END) as live_domains,
    SUM(CASE WHEN NOT is_live THEN 1 ELSE 0 END) as dead_domains,
    MAX(discovered_at) as newest_discovery,
    MIN(discovered_at) as oldest_discovery,
    COUNT(DISTINCT CASE WHEN rediscovered_at IS NOT NULL THEN domain END) as rediscovered_count
FROM domains;

-- View: Queue summary
CREATE OR REPLACE VIEW v_queue_summary AS
SELECT
    status,
    priority,
    COUNT(*) as count,
    MAX(scheduled_at) as latest_scheduled,
    MIN(scheduled_at) as oldest_scheduled
FROM url_queue
GROUP BY status, priority
ORDER BY status, priority;

-- View: Recent discovery activity
CREATE OR REPLACE VIEW v_discovery_activity AS
SELECT
    dl.action,
    dl.domain,
    dl.timestamp,
    dl.details,
    dl.error_message
FROM discovery_log dl
WHERE dl.timestamp > (CURRENT_TIMESTAMP - INTERVAL '24 hours')
ORDER BY dl.timestamp DESC
LIMIT 1000;

-- ============================================
-- Functions for Common Operations
-- ============================================

-- Function to safely insert or ignore duplicate domains
CREATE OR REPLACE FUNCTION upsert_domain(
    p_domain VARCHAR(255),
    p_protocol VARCHAR(10) DEFAULT 'https',
    p_status_code INTEGER DEFAULT NULL,
    p_response_time INTEGER DEFAULT NULL,
    p_is_live BOOLEAN DEFAULT TRUE
)
RETURNS INTEGER AS $$
DECLARE
    v_domain_id INTEGER;
    v_exists BOOLEAN;
BEGIN
    -- Check if domain exists
    SELECT EXISTS(SELECT 1 FROM domains WHERE domain = p_domain) INTO v_exists;

    IF v_exists THEN
        -- Update existing domain
        UPDATE domains SET
            protocol = p_protocol,
            status_code = p_status_code,
            response_time = p_response_time,
            is_live = p_is_live,
            last_checked = CURRENT_TIMESTAMP
        WHERE domain = p_domain
        RETURNING id INTO v_domain_id;

        RAISE NOTICE 'Updated existing domain: %', p_domain;
    ELSE
        -- Insert new domain
        INSERT INTO domains (domain, protocol, status_code, response_time, is_live)
        VALUES (p_domain, p_protocol, p_status_code, p_response_time, p_is_live)
        RETURNING id INTO v_domain_id;

        RAISE NOTICE 'Inserted new domain: %', p_domain;
    END IF;

    RETURN v_domain_id;
END;
$$ LANGUAGE plpgsql;

-- Function to check queue for processing
CREATE OR REPLACE FUNCTION get_next_queue_item(
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    id INTEGER,
    url VARCHAR(500),
    priority INTEGER,
    scheduled_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT uq.id, uq.url, uq.priority, uq.scheduled_at
    FROM url_queue uq
    WHERE uq.status = 'pending'
      AND uq.attempts < 3
      AND uq.scheduled_at <= CURRENT_TIMESTAMP
    ORDER BY uq.priority ASC, uq.scheduled_at ASC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- Permissions (optional - adjust for your setup)
-- ============================================

-- Grant permissions to application user
-- Note: Adjust the role name to match your setup
DO $$
BEGIN
    -- Create role if it doesn't exist
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'url_discovery') THEN
        CREATE ROLE url_discovery WITH LOGIN PASSWORD 'secure_password_here';
    END IF;

    -- Grant permissions
    GRANT USAGE ON SCHEMA public TO url_discovery;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO url_discovery;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO url_discovery;

    -- Grant permissions on views
    GRANT SELECT ON v_live_domains TO url_discovery;
    GRANT SELECT ON v_dead_domains TO url_discovery;
    GRANT SELECT ON v_recent_discoveries TO url_discovery;
    GRANT SELECT ON v_discovery_stats TO url_discovery;
    GRANT SELECT ON v_queue_summary TO url_discovery;
    GRANT SELECT ON v_discovery_activity TO url_discovery;

    -- Set default permissions for future objects
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO url_discovery;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO url_discovery;
END $$;

-- ============================================
-- End of Migration
-- ============================================
