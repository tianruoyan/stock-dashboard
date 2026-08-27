ALTER TABLE watchlist_sync_batch ADD COLUMN source_identity_hash TEXT;
ALTER TABLE watchlist_sync_batch ADD COLUMN input_state TEXT;
ALTER TABLE watchlist_sync_batch ADD COLUMN completeness_reason TEXT;

CREATE TABLE IF NOT EXISTS watchlist_shadow_snapshot (
    shadow_snapshot_id TEXT PRIMARY KEY,
    sync_batch_id TEXT NOT NULL REFERENCES watchlist_sync_batch(sync_batch_id),
    normalized_code TEXT NOT NULL,
    display_name TEXT,
    source_id TEXT,
    source_id_state TEXT NOT NULL CHECK (source_id_state IN ('provided', 'not_provided')),
    observed_at TEXT NOT NULL,
    UNIQUE (sync_batch_id, normalized_code)
);

CREATE INDEX IF NOT EXISTS idx_shadow_snapshot_batch
ON watchlist_shadow_snapshot(sync_batch_id, normalized_code);

CREATE TRIGGER IF NOT EXISTS shadow_snapshot_append_only_update
BEFORE UPDATE ON watchlist_shadow_snapshot
BEGIN
    SELECT RAISE(ABORT, 'shadow_snapshot_append_only');
END;

CREATE TRIGGER IF NOT EXISTS shadow_snapshot_append_only_delete
BEFORE DELETE ON watchlist_shadow_snapshot
BEGIN
    SELECT RAISE(ABORT, 'shadow_snapshot_append_only');
END;
