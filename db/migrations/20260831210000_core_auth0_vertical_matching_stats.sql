-- migrate:up
-- Auth0 vertical matching rollup tracked request_vertical_matching snapshots
-- (total and success incremented together → always 100%). Switch to the Email
-- request spine + auth0_attempts queue, mirroring the data vertical pattern.

CREATE OR REPLACE FUNCTION core_drop_bulk_vertical_auth0_matching_delta(
    p_download_id BIGINT,
    p_old_status TEXT,
    p_new_status TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_old_bucket TEXT;
    v_new_bucket TEXT;
BEGIN
    IF p_download_id IS NULL THEN
        RETURN;
    END IF;

    v_old_bucket := core_vertical_data_matching_status_bucket(p_old_status);
    v_new_bucket := core_vertical_data_matching_status_bucket(p_new_status);

    IF v_old_bucket IS NULL AND v_new_bucket IS NULL THEN
        RETURN;
    END IF;

    PERFORM core_ensure_drop_bulk_vertical_stats(p_download_id, 'auth0', 'matching');
    UPDATE drop_bulk_vertical_stats
       SET open = GREATEST(
               0,
               open
               + CASE WHEN v_old_bucket = 'open' THEN -1 ELSE 0 END
               + CASE WHEN v_new_bucket = 'open' THEN 1 ELSE 0 END
           ),
           success = GREATEST(
               0,
               success
               + CASE WHEN v_old_bucket = 'success' THEN -1 ELSE 0 END
               + CASE WHEN v_new_bucket = 'success' THEN 1 ELSE 0 END
           ),
           failed = GREATEST(
               0,
               failed
               + CASE WHEN v_old_bucket = 'failed' THEN -1 ELSE 0 END
               + CASE WHEN v_new_bucket = 'failed' THEN 1 ELSE 0 END
           ),
           in_flight = GREATEST(
               0,
               in_flight
               + CASE WHEN v_old_bucket = 'in_flight' THEN -1 ELSE 0 END
               + CASE WHEN v_new_bucket = 'in_flight' THEN 1 ELSE 0 END
           ),
           updated_at = NOW()
     WHERE download_id = p_download_id
       AND vertical = 'auth0'
       AND stage = 'matching';
END;
$$;

CREATE OR REPLACE FUNCTION core_auth0_attempts_vertical_stats()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_download_id BIGINT;
    v_is_latest BOOLEAN;
    v_prev_status TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    SELECT r.bulk_process_download_id
      INTO v_download_id
      FROM requests r
     WHERE r.id = NEW.request_id;

    IF v_download_id IS NULL OR NEW.step <> 'matching' THEN
        RETURN NEW;
    END IF;

    SELECT NOT EXISTS (
        SELECT 1
          FROM auth0_attempts aa
         WHERE aa.request_id = NEW.request_id
           AND aa.step = NEW.step
           AND aa.attempt_number > NEW.attempt_number
    ) INTO v_is_latest;

    IF NOT v_is_latest THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.attempt_number > 1 THEN
            SELECT aa.status
              INTO v_prev_status
              FROM auth0_attempts aa
             WHERE aa.request_id = NEW.request_id
               AND aa.step = NEW.step
               AND aa.attempt_number < NEW.attempt_number
             ORDER BY aa.attempt_number DESC
             LIMIT 1;
        ELSE
            v_prev_status := 'none';
        END IF;
        PERFORM core_drop_bulk_vertical_auth0_matching_delta(
            v_download_id, v_prev_status, NEW.status
        );
    ELSIF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        PERFORM core_drop_bulk_vertical_auth0_matching_delta(
            v_download_id, OLD.status, NEW.status
        );
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION core_auth0_attempts_vertical_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core_auth0_attempts_vertical_stats() TO PUBLIC;

DROP TRIGGER IF EXISTS auth0_attempts_vertical_stats ON auth0_attempts;
CREATE TRIGGER auth0_attempts_vertical_stats
    AFTER INSERT OR UPDATE OF status ON auth0_attempts
    FOR EACH ROW
    EXECUTE FUNCTION core_auth0_attempts_vertical_stats();

-- Seed auth0 matching open bucket for Email DROP requests at promote time.
CREATE OR REPLACE FUNCTION core_requests_bulk_stats_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_response_status SMALLINT;
    v_list_type VARCHAR;
BEGIN
    IF NEW.bulk_process_download_id IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM core_ensure_drop_bulk_process_stats(NEW.bulk_process_download_id);
    UPDATE drop_bulk_process_stats
       SET request_rows = request_rows + 1,
           matching_none = matching_none + 1,
           updated_at = NOW()
     WHERE download_id = NEW.bulk_process_download_id;

    IF NEW.intake_source = 'drop' AND NEW.raw_record_id IS NOT NULL THEN
        SELECT drr.response_status, drr.list_type
          INTO v_response_status, v_list_type
          FROM drop_raw_requests drr
         WHERE drr.id = NEW.raw_record_id;

        IF v_response_status IS NULL THEN
            UPDATE drop_bulk_process_stats
               SET fulfill_unset = fulfill_unset + 1,
                   updated_at = NOW()
             WHERE download_id = NEW.bulk_process_download_id;
        ELSE
            UPDATE drop_bulk_process_stats
               SET fulfill_done = fulfill_done + 1,
                   updated_at = NOW()
             WHERE download_id = NEW.bulk_process_download_id;
        END IF;

        IF v_list_type = 'Email' THEN
            PERFORM core_ensure_drop_bulk_vertical_stats(
                NEW.bulk_process_download_id, 'auth0', 'matching'
            );
            UPDATE drop_bulk_vertical_stats
               SET total = total + 1,
                   open = open + 1,
                   updated_at = NOW()
             WHERE download_id = NEW.bulk_process_download_id
               AND vertical = 'auth0'
               AND stage = 'matching';
        END IF;
    END IF;

    PERFORM core_ensure_drop_bulk_vertical_stats(
        NEW.bulk_process_download_id, 'data', 'matching'
    );
    UPDATE drop_bulk_vertical_stats
       SET total = total + 1,
           open = open + 1,
           updated_at = NOW()
     WHERE download_id = NEW.bulk_process_download_id
       AND vertical = 'data'
       AND stage = 'matching';

    RETURN NEW;
END;
$$;

-- Snapshots gate review only — matching progress lives on auth0_attempts.
CREATE OR REPLACE FUNCTION core_request_vertical_matching_bulk_stats()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_download_id BIGINT;
    v_has_disposition BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT r.bulk_process_download_id
          INTO v_download_id
          FROM requests r
         WHERE r.id = NEW.request_id;

        IF v_download_id IS NULL THEN
            RETURN NEW;
        END IF;

        SELECT EXISTS (
            SELECT 1
              FROM request_vertical_dispositions rvd
             WHERE rvd.request_id = NEW.request_id
               AND rvd.vertical = NEW.vertical
        ) INTO v_has_disposition;

        IF NOT v_has_disposition THEN
            PERFORM core_ensure_drop_bulk_vertical_stats(
                v_download_id, NEW.vertical, 'review'
            );
            UPDATE drop_bulk_vertical_stats
               SET total = total + 1,
                   open = open + 1,
                   updated_at = NOW()
             WHERE download_id = v_download_id
               AND vertical = NEW.vertical
               AND stage = 'review';
        END IF;

        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.vertical IS DISTINCT FROM NEW.vertical
           OR OLD.request_id IS DISTINCT FROM NEW.request_id THEN
            RETURN NEW;
        END IF;
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        SELECT r.bulk_process_download_id
          INTO v_download_id
          FROM requests r
         WHERE r.id = OLD.request_id;

        IF v_download_id IS NULL THEN
            RETURN OLD;
        END IF;

        SELECT EXISTS (
            SELECT 1
              FROM request_vertical_dispositions rvd
             WHERE rvd.request_id = OLD.request_id
               AND rvd.vertical = OLD.vertical
        ) INTO v_has_disposition;

        IF NOT v_has_disposition THEN
            UPDATE drop_bulk_vertical_stats
               SET total = GREATEST(0, total - 1),
                   open = GREATEST(0, open - 1),
                   updated_at = NOW()
             WHERE download_id = v_download_id
               AND vertical = OLD.vertical
               AND stage = 'review';
        END IF;

        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$;

-- Recompute auth0 matching from Email spine + latest auth0_attempt per request.
DELETE FROM drop_bulk_vertical_stats
 WHERE vertical = 'auth0'
   AND stage = 'matching';

INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
SELECT
    sub.download_id,
    'auth0',
    'matching',
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE sub.bucket = 'open')::bigint,
    COUNT(*) FILTER (WHERE sub.bucket = 'success')::bigint,
    COUNT(*) FILTER (WHERE sub.bucket = 'failed')::bigint,
    COUNT(*) FILTER (WHERE sub.bucket = 'in_flight')::bigint
  FROM (
    SELECT DISTINCT ON (r.id)
           r.bulk_process_download_id AS download_id,
           CASE
               WHEN aa.status IS NULL THEN 'open'
               WHEN aa.status = 'success' THEN 'success'
               WHEN aa.status = 'in_flight' THEN 'in_flight'
               WHEN aa.status IN (
                   'submit_error', 'outcome_error', 'timeout', 'failed'
               ) THEN 'failed'
               ELSE 'open'
           END AS bucket
      FROM requests r
      JOIN drop_raw_requests drr
        ON r.intake_source = 'drop'
       AND r.raw_record_id = drr.id
       AND drr.list_type = 'Email'
      LEFT JOIN auth0_attempts aa
        ON aa.request_id = r.id
       AND aa.step = 'matching'
     WHERE r.bulk_process_download_id IS NOT NULL
     ORDER BY r.id, aa.attempt_number DESC NULLS LAST, aa.attempted_at DESC NULLS LAST
  ) sub
 GROUP BY sub.download_id
ON CONFLICT (download_id, vertical, stage) DO UPDATE
   SET total = EXCLUDED.total,
       open = EXCLUDED.open,
       success = EXCLUDED.success,
       failed = EXCLUDED.failed,
       in_flight = EXCLUDED.in_flight,
       updated_at = NOW();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT EXECUTE ON FUNCTION core_drop_bulk_vertical_auth0_matching_delta(
            BIGINT, TEXT, TEXT
        ) TO app_user;
        GRANT EXECUTE ON FUNCTION core_auth0_attempts_vertical_stats() TO app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS auth0_attempts_vertical_stats ON auth0_attempts;
DROP FUNCTION IF EXISTS core_auth0_attempts_vertical_stats();
DROP FUNCTION IF EXISTS core_drop_bulk_vertical_auth0_matching_delta(BIGINT, TEXT, TEXT);

-- Restore request insert without auth0 seeding.
CREATE OR REPLACE FUNCTION core_requests_bulk_stats_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_response_status SMALLINT;
BEGIN
    IF NEW.bulk_process_download_id IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM core_ensure_drop_bulk_process_stats(NEW.bulk_process_download_id);
    UPDATE drop_bulk_process_stats
       SET request_rows = request_rows + 1,
           matching_none = matching_none + 1,
           updated_at = NOW()
     WHERE download_id = NEW.bulk_process_download_id;

    IF NEW.intake_source = 'drop' AND NEW.raw_record_id IS NOT NULL THEN
        SELECT drr.response_status
          INTO v_response_status
          FROM drop_raw_requests drr
         WHERE drr.id = NEW.raw_record_id;

        IF v_response_status IS NULL THEN
            UPDATE drop_bulk_process_stats
               SET fulfill_unset = fulfill_unset + 1,
                   updated_at = NOW()
             WHERE download_id = NEW.bulk_process_download_id;
        ELSE
            UPDATE drop_bulk_process_stats
               SET fulfill_done = fulfill_done + 1,
                   updated_at = NOW()
             WHERE download_id = NEW.bulk_process_download_id;
        END IF;
    END IF;

    PERFORM core_ensure_drop_bulk_vertical_stats(
        NEW.bulk_process_download_id, 'data', 'matching'
    );
    UPDATE drop_bulk_vertical_stats
       SET total = total + 1,
           open = open + 1,
           updated_at = NOW()
     WHERE download_id = NEW.bulk_process_download_id
       AND vertical = 'data'
       AND stage = 'matching';

    RETURN NEW;
END;
$$;

-- Restore snapshot-driven matching counters for external verticals.
CREATE OR REPLACE FUNCTION core_request_vertical_matching_bulk_stats()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_download_id BIGINT;
    v_has_disposition BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT r.bulk_process_download_id
          INTO v_download_id
          FROM requests r
         WHERE r.id = NEW.request_id;

        IF v_download_id IS NULL THEN
            RETURN NEW;
        END IF;

        PERFORM core_ensure_drop_bulk_vertical_stats(
            v_download_id, NEW.vertical, 'matching'
        );
        UPDATE drop_bulk_vertical_stats
           SET total = total + 1,
               success = success + 1,
               updated_at = NOW()
         WHERE download_id = v_download_id
           AND vertical = NEW.vertical
           AND stage = 'matching';

        SELECT EXISTS (
            SELECT 1
              FROM request_vertical_dispositions rvd
             WHERE rvd.request_id = NEW.request_id
               AND rvd.vertical = NEW.vertical
        ) INTO v_has_disposition;

        IF NOT v_has_disposition THEN
            PERFORM core_ensure_drop_bulk_vertical_stats(
                v_download_id, NEW.vertical, 'review'
            );
            UPDATE drop_bulk_vertical_stats
               SET total = total + 1,
                   open = open + 1,
                   updated_at = NOW()
             WHERE download_id = v_download_id
               AND vertical = NEW.vertical
               AND stage = 'review';
        END IF;

        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.vertical IS DISTINCT FROM NEW.vertical
           OR OLD.request_id IS DISTINCT FROM NEW.request_id THEN
            RETURN NEW;
        END IF;
        RETURN NEW;

    ELSIF TG_OP = 'DELETE' THEN
        SELECT r.bulk_process_download_id
          INTO v_download_id
          FROM requests r
         WHERE r.id = OLD.request_id;

        IF v_download_id IS NULL THEN
            RETURN OLD;
        END IF;

        UPDATE drop_bulk_vertical_stats
           SET total = GREATEST(0, total - 1),
               success = GREATEST(0, success - 1),
               updated_at = NOW()
         WHERE download_id = v_download_id
           AND vertical = OLD.vertical
           AND stage = 'matching';

        SELECT EXISTS (
            SELECT 1
              FROM request_vertical_dispositions rvd
             WHERE rvd.request_id = OLD.request_id
               AND rvd.vertical = OLD.vertical
        ) INTO v_has_disposition;

        IF NOT v_has_disposition THEN
            UPDATE drop_bulk_vertical_stats
               SET total = GREATEST(0, total - 1),
                   open = GREATEST(0, open - 1),
                   updated_at = NOW()
             WHERE download_id = v_download_id
               AND vertical = OLD.vertical
               AND stage = 'review';
        END IF;

        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$;
