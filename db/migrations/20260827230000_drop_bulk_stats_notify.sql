-- migrate:up
-- Commit-triggered push plane for live DROP bulk cards: when the
-- trigger-maintained rollup row changes, fan out a NOTIFY so admin-api can
-- push an SSE snapshot immediately instead of waiting for the 5s poll.
-- Payload is the download id only — counts-only signal, never PII. NOTIFY
-- delivers only after COMMIT, so listeners never see uncommitted counters.

CREATE OR REPLACE FUNCTION core_drop_bulk_process_stats_notify()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_notify('drop_bulk_stats_changed', NEW.download_id::text);
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION core_drop_bulk_process_stats_notify() IS
    'Fan-out signal for live bulk cards: notifies drop_bulk_stats_changed with the download id on rollup row change. Counts-only signal — never PII.';

DROP TRIGGER IF EXISTS drop_bulk_process_stats_notify ON drop_bulk_process_stats;
CREATE TRIGGER drop_bulk_process_stats_notify
    AFTER INSERT OR UPDATE ON drop_bulk_process_stats
    FOR EACH ROW
    EXECUTE FUNCTION core_drop_bulk_process_stats_notify();

COMMENT ON TRIGGER drop_bulk_process_stats_notify ON drop_bulk_process_stats IS
    'AFTER INSERT OR UPDATE fan-out to drop_bulk_stats_changed for live SSE push. Payload is the download id only — never PII.';

REVOKE ALL ON FUNCTION core_drop_bulk_process_stats_notify() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT EXECUTE ON FUNCTION core_drop_bulk_process_stats_notify()
            TO app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS drop_bulk_process_stats_notify ON drop_bulk_process_stats;
DROP FUNCTION IF EXISTS core_drop_bulk_process_stats_notify();
