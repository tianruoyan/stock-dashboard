DROP TRIGGER IF EXISTS user_asset_update_guard;

CREATE TRIGGER user_asset_update_guard
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
    SELECT CASE WHEN NEW.membership_state IS NOT OLD.membership_state AND NOT EXISTS (
        SELECT 1 FROM user_asset_change_log
        WHERE user_asset_id = OLD.user_asset_id
          AND request_id = NEW.last_request_id
          AND field_name = 'membership_state'
    ) THEN RAISE(ABORT, 'user_asset_change_log_required') END;
    SELECT CASE WHEN NEW.user_priority IS NOT OLD.user_priority AND NOT EXISTS (
        SELECT 1 FROM user_asset_change_log
        WHERE user_asset_id = OLD.user_asset_id
          AND request_id = NEW.last_request_id
          AND field_name = 'user_priority'
    ) THEN RAISE(ABORT, 'user_asset_change_log_required') END;
    SELECT CASE WHEN NEW.user_intent IS NOT OLD.user_intent AND NOT EXISTS (
        SELECT 1 FROM user_asset_change_log
        WHERE user_asset_id = OLD.user_asset_id
          AND request_id = NEW.last_request_id
          AND field_name = 'user_intent'
    ) THEN RAISE(ABORT, 'user_asset_change_log_required') END;
    SELECT CASE WHEN NEW.user_note IS NOT OLD.user_note AND NOT EXISTS (
        SELECT 1 FROM user_asset_change_log
        WHERE user_asset_id = OLD.user_asset_id
          AND request_id = NEW.last_request_id
          AND field_name = 'user_note'
    ) THEN RAISE(ABORT, 'user_asset_change_log_required') END;
    SELECT CASE WHEN NEW.user_confirmed_at IS NOT OLD.user_confirmed_at AND NOT EXISTS (
        SELECT 1 FROM user_asset_change_log
        WHERE user_asset_id = OLD.user_asset_id
          AND request_id = NEW.last_request_id
          AND field_name = 'user_confirmed_at'
    ) THEN RAISE(ABORT, 'user_asset_change_log_required') END;
END;
