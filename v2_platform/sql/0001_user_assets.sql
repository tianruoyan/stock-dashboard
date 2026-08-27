CREATE TABLE IF NOT EXISTS asset_write_authorization (
    request_id TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'sync_service', 'ai', 'style_model', 'system')),
    operation TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_master (
    security_id TEXT PRIMARY KEY,
    market TEXT NOT NULL CHECK (market IN ('CN_SSE', 'CN_SZSE', 'CN_BSE', 'HK_HKEX', 'US', 'OTHER')),
    ticker TEXT NOT NULL,
    normalized_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    security_type TEXT NOT NULL CHECK (security_type IN ('stock', 'etf', 'index', 'other')),
    currency TEXT,
    listing_state TEXT NOT NULL CHECK (listing_state IN ('active', 'suspended', 'delisted', 'unknown')),
    identity_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (market, ticker)
);

CREATE TABLE IF NOT EXISTS user_watchlist_asset (
    user_asset_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    security_id TEXT NOT NULL REFERENCES security_master(security_id),
    membership_state TEXT NOT NULL CHECK (membership_state IN ('active', 'deleted_confirmed')),
    user_priority TEXT NOT NULL CHECK (user_priority IN ('high', 'normal', 'low')),
    user_intent TEXT CHECK (user_intent IS NULL OR user_intent IN ('holding', 'swing', 'watch', 'research', 'event')),
    user_note TEXT,
    user_confirmed_at TEXT,
    user_confirmed_evidence_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    deleted_at TEXT,
    delete_evidence_id TEXT,
    last_request_id TEXT NOT NULL REFERENCES asset_write_authorization(request_id),
    UNIQUE (user_id, security_id),
    CHECK ((user_confirmed_at IS NULL AND user_confirmed_evidence_id IS NULL) OR (user_confirmed_at IS NOT NULL AND user_confirmed_evidence_id IS NOT NULL)),
    CHECK ((membership_state = 'active' AND deleted_at IS NULL AND delete_evidence_id IS NULL) OR (membership_state = 'deleted_confirmed' AND deleted_at IS NOT NULL AND delete_evidence_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS watchlist_sync_batch (
    sync_batch_id TEXT PRIMARY KEY,
    watchlist_source TEXT NOT NULL CHECK (watchlist_source IN ('ths_cloud', 'broker_sync')),
    sync_mode TEXT NOT NULL CHECK (sync_mode IN ('full', 'incremental', 'file_fallback')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    batch_state TEXT NOT NULL CHECK (batch_state IN ('running', 'success', 'partial', 'failed', 'rejected')),
    source_as_of TEXT,
    completeness_verified INTEGER NOT NULL DEFAULT 0 CHECK (completeness_verified IN (0, 1)),
    source_record_count INTEGER,
    added_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    delete_observed_count INTEGER NOT NULL DEFAULT 0,
    delete_applied_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    raw_content_hash TEXT,
    deletion_allowed INTEGER NOT NULL DEFAULT 0 CHECK (deletion_allowed IN (0, 1)),
    failure_reason TEXT,
    CHECK (deletion_allowed = 0 OR (batch_state = 'success' AND sync_mode = 'full' AND completeness_verified = 1))
);

CREATE TABLE IF NOT EXISTS watchlist_source_link (
    source_link_id TEXT PRIMARY KEY,
    user_asset_id TEXT NOT NULL REFERENCES user_watchlist_asset(user_asset_id),
    watchlist_source TEXT NOT NULL CHECK (watchlist_source IN ('ths_cloud', 'manual_add', 'broker_sync')),
    source_priority INTEGER NOT NULL CHECK (source_priority > 0),
    source_id TEXT,
    source_account_id TEXT,
    source_list_id TEXT,
    source_security_id TEXT,
    source_state TEXT NOT NULL CHECK (source_state IN ('active', 'delete_observed', 'deleted_confirmed', 'conflict')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sync_time TEXT NOT NULL,
    last_sync_batch_id TEXT REFERENCES watchlist_sync_batch(sync_batch_id),
    delete_evidence_id TEXT,
    last_request_id TEXT NOT NULL REFERENCES asset_write_authorization(request_id),
    CHECK ((source_state = 'deleted_confirmed' AND delete_evidence_id IS NOT NULL) OR source_state != 'deleted_confirmed')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_source_identity
ON watchlist_source_link(user_asset_id, watchlist_source, IFNULL(source_id, ''), IFNULL(source_list_id, ''));

CREATE TABLE IF NOT EXISTS watchlist_sync_event (
    sync_event_id TEXT PRIMARY KEY,
    sync_batch_id TEXT NOT NULL REFERENCES watchlist_sync_batch(sync_batch_id),
    security_id TEXT REFERENCES security_master(security_id),
    source_link_id TEXT REFERENCES watchlist_source_link(source_link_id),
    event_type TEXT NOT NULL CHECK (event_type IN ('observed_add', 'observed_update', 'observed_missing', 'confirmed_delete', 'unchanged', 'conflict')),
    before_snapshot TEXT,
    after_snapshot TEXT,
    evidence_ref TEXT NOT NULL,
    applied INTEGER NOT NULL CHECK (applied IN (0, 1)),
    block_reason TEXT,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_asset_change_log (
    change_id TEXT PRIMARY KEY,
    user_asset_id TEXT NOT NULL REFERENCES user_watchlist_asset(user_asset_id),
    field_name TEXT NOT NULL CHECK (field_name IN ('membership_state', 'user_priority', 'user_intent', 'user_note', 'user_confirmed_at')),
    before_value TEXT,
    after_value TEXT,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'sync_service')),
    actor_id TEXT,
    change_reason TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    request_id TEXT NOT NULL REFERENCES asset_write_authorization(request_id)
);

CREATE TABLE IF NOT EXISTS stock_research_profile (
    research_profile_id TEXT PRIMARY KEY,
    security_id TEXT NOT NULL UNIQUE REFERENCES security_master(security_id),
    research_state TEXT NOT NULL CHECK (research_state IN ('not_started', 'incomplete', 'complete', 'stale')),
    attention_reason TEXT,
    mapping_basis TEXT,
    counter_evidence_json TEXT,
    suitable_environment_json TEXT,
    unsuitable_environment_json TEXT,
    liquidity_risk TEXT,
    position_risk TEXT,
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    profile_version TEXT NOT NULL,
    effective_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS theme_master (
    theme_id TEXT PRIMARY KEY,
    theme_name TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    theme_state TEXT NOT NULL,
    definition TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_theme_membership (
    security_theme_id TEXT PRIMARY KEY,
    security_id TEXT NOT NULL REFERENCES security_master(security_id),
    theme_id TEXT NOT NULL REFERENCES theme_master(theme_id),
    exposure_type TEXT NOT NULL,
    exposure_state TEXT NOT NULL,
    basis TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE (security_id, theme_id, exposure_type)
);

CREATE TABLE IF NOT EXISTS security_role_assignment (
    role_assignment_id TEXT PRIMARY KEY,
    security_id TEXT NOT NULL REFERENCES security_master(security_id),
    role_type TEXT NOT NULL,
    role_state TEXT NOT NULL,
    basis TEXT,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    effective_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS formal_observation_state (
    security_id TEXT PRIMARY KEY REFERENCES security_master(security_id),
    observation_state TEXT NOT NULL,
    reason TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_asset_state (
    security_id TEXT PRIMARY KEY REFERENCES security_master(security_id),
    analysis_state TEXT NOT NULL CHECK (analysis_state IN ('focus', 'wait_confirm', 'conditions_near', 'do_not_participate', 'risk_release', 'invalidated')),
    conclusion TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trading_candidate (
    candidate_id TEXT PRIMARY KEY,
    security_id TEXT NOT NULL REFERENCES security_master(security_id),
    candidate_state TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS style_basket (
    style_basket_id TEXT PRIMARY KEY,
    style_code TEXT NOT NULL,
    version TEXT NOT NULL,
    definition TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    UNIQUE (style_code, version)
);

CREATE TABLE IF NOT EXISTS style_basket_member (
    style_member_id TEXT PRIMARY KEY,
    style_basket_id TEXT NOT NULL REFERENCES style_basket(style_basket_id),
    security_id TEXT NOT NULL REFERENCES security_master(security_id),
    basis TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE (style_basket_id, security_id)
);

CREATE TABLE IF NOT EXISTS temporary_candidate (
    temporary_candidate_id TEXT PRIMARY KEY,
    security_id TEXT NOT NULL REFERENCES security_master(security_id),
    discovery_source TEXT NOT NULL CHECK (discovery_source IN ('system_candidate', 'research_import', 'event_scan', 'anomaly_scan')),
    candidate_state TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    valid_until TEXT
);

CREATE TRIGGER IF NOT EXISTS user_asset_insert_actor_guard
BEFORE INSERT ON user_watchlist_asset
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM asset_write_authorization
        WHERE request_id = NEW.last_request_id
          AND actor_type IN ('user', 'sync_service')
          AND operation = 'asset_create'
    ) THEN RAISE(ABORT, 'user_asset_actor_forbidden') END;
END;

CREATE TRIGGER IF NOT EXISTS user_asset_update_guard
BEFORE UPDATE ON user_watchlist_asset
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM asset_write_authorization
        WHERE request_id = NEW.last_request_id
          AND actor_type IN ('user', 'sync_service')
          AND operation IN ('asset_update', 'asset_delete')
    ) THEN RAISE(ABORT, 'user_asset_actor_forbidden') END;
    SELECT CASE WHEN NEW.revision != OLD.revision + 1
        THEN RAISE(ABORT, 'user_asset_revision_conflict') END;
    SELECT CASE WHEN OLD.user_confirmed_at IS NOT NULL AND NEW.user_confirmed_at IS NOT OLD.user_confirmed_at
        THEN RAISE(ABORT, 'user_confirmed_at_immutable') END;
    SELECT CASE WHEN NEW.membership_state = 'deleted_confirmed' AND EXISTS (
        SELECT 1 FROM watchlist_source_link
        WHERE user_asset_id = OLD.user_asset_id AND source_state = 'active'
    ) THEN RAISE(ABORT, 'active_source_protects_user_asset') END;
END;

CREATE TRIGGER IF NOT EXISTS user_asset_no_physical_delete
BEFORE DELETE ON user_watchlist_asset
BEGIN
    SELECT RAISE(ABORT, 'user_asset_physical_delete_forbidden');
END;

CREATE TRIGGER IF NOT EXISTS source_link_insert_actor_guard
BEFORE INSERT ON watchlist_source_link
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM asset_write_authorization
        WHERE request_id = NEW.last_request_id
          AND actor_type IN ('user', 'sync_service')
          AND operation = 'source_create'
    ) THEN RAISE(ABORT, 'source_actor_forbidden') END;
    SELECT CASE WHEN NEW.watchlist_source = 'manual_add' AND NOT EXISTS (
        SELECT 1 FROM asset_write_authorization
        WHERE request_id = NEW.last_request_id AND actor_type = 'user'
    ) THEN RAISE(ABORT, 'manual_source_requires_user') END;
    SELECT CASE WHEN NEW.watchlist_source IN ('ths_cloud', 'broker_sync') AND NOT EXISTS (
        SELECT 1 FROM asset_write_authorization
        WHERE request_id = NEW.last_request_id AND actor_type = 'sync_service'
    ) THEN RAISE(ABORT, 'synced_source_requires_service') END;
END;

CREATE TRIGGER IF NOT EXISTS source_link_update_actor_guard
BEFORE UPDATE ON watchlist_source_link
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM asset_write_authorization
        WHERE request_id = NEW.last_request_id
          AND actor_type IN ('user', 'sync_service')
          AND operation = 'source_update'
    ) THEN RAISE(ABORT, 'source_actor_forbidden') END;
END;

CREATE TRIGGER IF NOT EXISTS source_link_no_physical_delete
BEFORE DELETE ON watchlist_source_link
BEGIN
    SELECT RAISE(ABORT, 'source_link_physical_delete_forbidden');
END;

CREATE TRIGGER IF NOT EXISTS change_log_append_only_update
BEFORE UPDATE ON user_asset_change_log
BEGIN
    SELECT RAISE(ABORT, 'change_log_append_only');
END;

CREATE TRIGGER IF NOT EXISTS change_log_append_only_delete
BEFORE DELETE ON user_asset_change_log
BEGIN
    SELECT RAISE(ABORT, 'change_log_append_only');
END;

CREATE TRIGGER IF NOT EXISTS sync_event_append_only_update
BEFORE UPDATE ON watchlist_sync_event
BEGIN
    SELECT RAISE(ABORT, 'sync_event_append_only');
END;

CREATE TRIGGER IF NOT EXISTS sync_event_append_only_delete
BEFORE DELETE ON watchlist_sync_event
BEGIN
    SELECT RAISE(ABORT, 'sync_event_append_only');
END;

CREATE INDEX IF NOT EXISTS idx_user_watchlist_active
ON user_watchlist_asset(user_id, membership_state, user_priority);

CREATE INDEX IF NOT EXISTS idx_source_link_asset_state
ON watchlist_source_link(user_asset_id, source_state, source_priority DESC);

CREATE INDEX IF NOT EXISTS idx_change_log_asset_time
ON user_asset_change_log(user_asset_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_sync_event_batch
ON watchlist_sync_event(sync_batch_id, occurred_at);
