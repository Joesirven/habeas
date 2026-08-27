-- migrate:up
-- Expanded per-download pipeline counters: review + fulfillment on drop_bulk_process_stats
-- and per-vertical stage matrix on drop_bulk_vertical_stats. Integers, statuses, and
-- timestamps only — never personally identifiable information.
-- Data Request Opt-out Program (DROP) download grain is drop_connector_attempts.id.

ALTER TABLE drop_bulk_process_stats
    ADD COLUMN IF NOT EXISTS review_pending INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS review_approved INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS fulfill_unset INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS fulfill_done INT NOT NULL DEFAULT 0,
    DROP CONSTRAINT IF EXISTS drop_bulk_process_stats_counts_nonneg,
    ADD CONSTRAINT drop_bulk_process_stats_counts_nonneg
        CHECK (
            request_rows >= 0
            AND matching_pending >= 0
            AND matching_claimed >= 0
            AND matching_in_flight >= 0
            AND matching_success >= 0
            AND matching_failed >= 0
            AND matching_abandoned >= 0
            AND matching_none >= 0
            AND review_pending >= 0
            AND review_approved >= 0
            AND fulfill_unset >= 0
            AND fulfill_done >= 0
        );

COMMENT ON COLUMN drop_bulk_process_stats.review_pending IS
    'Count of matching.review approvals pending. Count only — never PII.';
COMMENT ON COLUMN drop_bulk_process_stats.review_approved IS
    'Count of matching.review approvals approved. Count only — never PII.';
COMMENT ON COLUMN drop_bulk_process_stats.fulfill_unset IS
    'Count of DROP requests with no response_status set. Count only — never PII.';
COMMENT ON COLUMN drop_bulk_process_stats.fulfill_done IS
    'Count of DROP requests with a response_status set. Count only — never PII.';

CREATE TABLE drop_bulk_vertical_stats (
    download_id  BIGINT NOT NULL REFERENCES drop_connector_attempts(id),
    vertical     VARCHAR(50) NOT NULL,
    stage        VARCHAR(20) NOT NULL,
    total        BIGINT NOT NULL DEFAULT 0,
    open         BIGINT NOT NULL DEFAULT 0,
    success      BIGINT NOT NULL DEFAULT 0,
    failed       BIGINT NOT NULL DEFAULT 0,
    in_flight    BIGINT NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT drop_bulk_vertical_stats_pk PRIMARY KEY (download_id, vertical, stage),
    CONSTRAINT drop_bulk_vertical_stats_stage_valid
        CHECK (stage IN ('matching', 'review', 'fulfillment')),
    CONSTRAINT drop_bulk_vertical_stats_counts_nonneg
        CHECK (total >= 0 AND open >= 0 AND success >= 0 AND failed >= 0 AND in_flight >= 0)
);

COMMENT ON TABLE drop_bulk_vertical_stats IS
    'Per-download vertical stage matrix for pipeline expand. Integers and statuses only — never PII.';
COMMENT ON COLUMN drop_bulk_vertical_stats.download_id IS
    'DROP download attempt identifier (drop_connector_attempts.id).';
COMMENT ON COLUMN drop_bulk_vertical_stats.vertical IS
    'Vertical name (for example, data, auth0, communications, people_hr).';
COMMENT ON COLUMN drop_bulk_vertical_stats.stage IS
    'Pipeline stage: matching, review, or fulfillment.';

CREATE OR REPLACE FUNCTION core_ensure_drop_bulk_vertical_stats(
    p_download_id BIGINT,
    p_vertical VARCHAR(50),
    p_stage VARCHAR(20)
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_download_id IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO drop_bulk_vertical_stats (download_id, vertical, stage)
    VALUES (p_download_id, p_vertical, p_stage)
    ON CONFLICT (download_id, vertical, stage) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION core_drop_bulk_process_review_delta(
    p_download_id BIGINT,
    p_old_status TEXT,
    p_new_status TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_download_id IS NULL THEN
        RETURN;
    END IF;
    PERFORM core_ensure_drop_bulk_process_stats(p_download_id);
    UPDATE drop_bulk_process_stats
       SET review_pending = GREATEST(
               0,
               review_pending
               + CASE WHEN p_old_status = 'pending' THEN -1 ELSE 0 END
               + CASE WHEN p_new_status = 'pending' THEN 1 ELSE 0 END
           ),
           review_approved = GREATEST(
               0,
               review_approved
               + CASE WHEN p_old_status = 'approved' THEN -1 ELSE 0 END
               + CASE WHEN p_new_status = 'approved' THEN 1 ELSE 0 END
           ),
           updated_at = NOW()
     WHERE download_id = p_download_id;
END;
$$;

CREATE OR REPLACE FUNCTION core_drop_bulk_process_fulfill_delta(
    p_download_id BIGINT,
    p_old_status SMALLINT,
    p_new_status SMALLINT,
    p_count INT DEFAULT 1
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_download_id IS NULL OR p_count = 0 THEN
        RETURN;
    END IF;
    PERFORM core_ensure_drop_bulk_process_stats(p_download_id);
    UPDATE drop_bulk_process_stats
       SET fulfill_unset = GREATEST(
               0,
               fulfill_unset
               + CASE WHEN p_old_status IS NULL THEN -p_count ELSE 0 END
               + CASE WHEN p_new_status IS NULL THEN p_count ELSE 0 END
           ),
           fulfill_done = GREATEST(
               0,
               fulfill_done
               + CASE WHEN p_old_status IS NOT NULL THEN -p_count ELSE 0 END
               + CASE WHEN p_new_status IS NOT NULL THEN p_count ELSE 0 END
           ),
           updated_at = NOW()
     WHERE download_id = p_download_id;
END;
$$;

CREATE OR REPLACE FUNCTION core_approval_requests_bulk_stats()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_download_id BIGINT;
    v_old_status TEXT;
    v_new_status TEXT;
BEGIN
    IF NEW.action_type IS DISTINCT FROM 'matching.review' THEN
        RETURN NEW;
    END IF;

    SELECT r.bulk_process_download_id
      INTO v_download_id
      FROM requests r
     WHERE r.id = NEW.request_id;

    IF v_download_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_old_status := NULL;
        v_new_status := NEW.status;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.status IS NOT DISTINCT FROM NEW.status THEN
            RETURN NEW;
        END IF;
        v_old_status := OLD.status;
        v_new_status := NEW.status;
    ELSE
        RETURN OLD;
    END IF;

    PERFORM core_drop_bulk_process_review_delta(v_download_id, v_old_status, v_new_status);
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION core_approval_requests_bulk_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core_approval_requests_bulk_stats() TO PUBLIC;

DROP TRIGGER IF EXISTS approval_requests_bulk_stats ON approval_requests;
CREATE TRIGGER approval_requests_bulk_stats
    AFTER INSERT OR UPDATE OF status ON approval_requests
    FOR EACH ROW
    EXECUTE FUNCTION core_approval_requests_bulk_stats();

CREATE OR REPLACE FUNCTION core_drop_raw_response_status_bulk_stats()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    rec RECORD;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.response_status IS NOT DISTINCT FROM NEW.response_status THEN
        RETURN NEW;
    END IF;

    FOR rec IN
        SELECT r.bulk_process_download_id AS download_id,
               COUNT(*)::int AS request_count
          FROM requests r
         WHERE r.raw_record_id = NEW.id
           AND r.bulk_process_download_id IS NOT NULL
         GROUP BY r.bulk_process_download_id
    LOOP
        PERFORM core_drop_bulk_process_fulfill_delta(
            rec.download_id, OLD.response_status, NEW.response_status,
            rec.request_count
        );
    END LOOP;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION core_drop_raw_response_status_bulk_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core_drop_raw_response_status_bulk_stats() TO PUBLIC;

DROP TRIGGER IF EXISTS drop_raw_response_status_bulk_stats ON drop_raw_requests;
CREATE TRIGGER drop_raw_response_status_bulk_stats
    AFTER UPDATE OF response_status ON drop_raw_requests
    FOR EACH ROW
    EXECUTE FUNCTION core_drop_raw_response_status_bulk_stats();

-- Extend request insert trigger to seed fulfillment counters and the data
-- vertical matching open bucket without double-counting request_rows.
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

CREATE OR REPLACE FUNCTION core_vertical_data_matching_status_bucket(p_status TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN p_status IS NULL THEN NULL
        WHEN p_status = 'none' THEN 'open'
        WHEN p_status = 'pending' THEN 'open'
        WHEN p_status = 'claimed' THEN 'open'
        WHEN p_status = 'abandoned' THEN 'open'
        WHEN p_status = 'in_flight' THEN 'in_flight'
        WHEN p_status = 'success' THEN 'success'
        WHEN p_status IN ('submit_error', 'outcome_error', 'timeout', 'failed') THEN 'failed'
        ELSE NULL
    END;
$$;

CREATE OR REPLACE FUNCTION core_drop_bulk_vertical_data_matching_delta(
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

    PERFORM core_ensure_drop_bulk_vertical_stats(p_download_id, 'data', 'matching');
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
       AND vertical = 'data'
       AND stage = 'matching';
END;
$$;

CREATE OR REPLACE FUNCTION core_matching_attempts_vertical_data_stats()
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

    IF v_download_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT NOT EXISTS (
        SELECT 1
          FROM matching_attempts ma
         WHERE ma.request_id = NEW.request_id
           AND ma.step = NEW.step
           AND ma.attempt_number > NEW.attempt_number
    ) INTO v_is_latest;

    IF NOT v_is_latest THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.attempt_number > 1 THEN
            SELECT ma.status
              INTO v_prev_status
              FROM matching_attempts ma
             WHERE ma.request_id = NEW.request_id
               AND ma.step = NEW.step
               AND ma.attempt_number < NEW.attempt_number
             ORDER BY ma.attempt_number DESC
             LIMIT 1;
        ELSE
            v_prev_status := 'none';
        END IF;
        PERFORM core_drop_bulk_vertical_data_matching_delta(
            v_download_id, v_prev_status, NEW.status
        );
    ELSIF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        PERFORM core_drop_bulk_vertical_data_matching_delta(
            v_download_id, OLD.status, NEW.status
        );
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION core_matching_attempts_vertical_data_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core_matching_attempts_vertical_data_stats() TO PUBLIC;

DROP TRIGGER IF EXISTS matching_attempts_vertical_data_stats ON matching_attempts;
CREATE TRIGGER matching_attempts_vertical_data_stats
    AFTER INSERT OR UPDATE OF status ON matching_attempts
    FOR EACH ROW
    EXECUTE FUNCTION core_matching_attempts_vertical_data_stats();

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
        -- request_id and vertical are immutable in practice; no counter move needed.
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

REVOKE ALL ON FUNCTION core_request_vertical_matching_bulk_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core_request_vertical_matching_bulk_stats() TO PUBLIC;

DROP TRIGGER IF EXISTS request_vertical_matching_bulk_stats ON request_vertical_matching;
CREATE TRIGGER request_vertical_matching_bulk_stats
    AFTER INSERT OR UPDATE OR DELETE ON request_vertical_matching
    FOR EACH ROW
    EXECUTE FUNCTION core_request_vertical_matching_bulk_stats();

CREATE OR REPLACE FUNCTION core_request_vertical_dispositions_bulk_stats()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_download_id BIGINT;
    v_has_matching BOOLEAN;
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
              FROM request_vertical_matching rvm
             WHERE rvm.request_id = NEW.request_id
               AND rvm.vertical = NEW.vertical
        ) INTO v_has_matching;

        IF v_has_matching THEN
            UPDATE drop_bulk_vertical_stats
               SET total = GREATEST(0, total - 1),
                   open = GREATEST(0, open - 1),
                   updated_at = NOW()
             WHERE download_id = v_download_id
               AND vertical = NEW.vertical
               AND stage = 'review';
        END IF;

        PERFORM core_ensure_drop_bulk_vertical_stats(
            v_download_id, NEW.vertical, 'fulfillment'
        );
        UPDATE drop_bulk_vertical_stats
           SET total = total + 1,
               success = success + 1,
               updated_at = NOW()
         WHERE download_id = v_download_id
           AND vertical = NEW.vertical
           AND stage = 'fulfillment';

        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN
        -- request_id and vertical are immutable in practice; no counter move needed.
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
              FROM request_vertical_matching rvm
             WHERE rvm.request_id = OLD.request_id
               AND rvm.vertical = OLD.vertical
        ) INTO v_has_matching;

        IF v_has_matching THEN
            PERFORM core_ensure_drop_bulk_vertical_stats(
                v_download_id, OLD.vertical, 'review'
            );
            UPDATE drop_bulk_vertical_stats
               SET total = total + 1,
                   open = open + 1,
                   updated_at = NOW()
             WHERE download_id = v_download_id
               AND vertical = OLD.vertical
               AND stage = 'review';
        END IF;

        UPDATE drop_bulk_vertical_stats
           SET total = GREATEST(0, total - 1),
               success = GREATEST(0, success - 1),
               updated_at = NOW()
         WHERE download_id = v_download_id
           AND vertical = OLD.vertical
           AND stage = 'fulfillment';

        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION core_request_vertical_dispositions_bulk_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core_request_vertical_dispositions_bulk_stats() TO PUBLIC;

DROP TRIGGER IF EXISTS request_vertical_dispositions_bulk_stats ON request_vertical_dispositions;
CREATE TRIGGER request_vertical_dispositions_bulk_stats
    AFTER INSERT OR UPDATE OR DELETE ON request_vertical_dispositions
    FOR EACH ROW
    EXECUTE FUNCTION core_request_vertical_dispositions_bulk_stats();

-- Set-based backfill: review and fulfillment counters on the download rollup.
INSERT INTO drop_bulk_process_stats (
    download_id, review_pending, review_approved, fulfill_unset, fulfill_done
)
SELECT
    sub.download_id,
    sub.review_pending,
    sub.review_approved,
    sub.fulfill_unset,
    sub.fulfill_done
  FROM (
    SELECT
        r.bulk_process_download_id AS download_id,
        COUNT(*) FILTER (WHERE ar.status = 'pending')::int AS review_pending,
        COUNT(*) FILTER (WHERE ar.status = 'approved')::int AS review_approved,
        COUNT(*) FILTER (WHERE r.intake_source = 'drop' AND drr.response_status IS NULL)::int
            AS fulfill_unset,
        COUNT(*) FILTER (WHERE r.intake_source = 'drop' AND drr.response_status IS NOT NULL)::int
            AS fulfill_done
      FROM requests r
      LEFT JOIN approval_requests ar
             ON ar.request_id = r.id
            AND ar.action_type = 'matching.review'
      LEFT JOIN drop_raw_requests drr
             ON drr.id = r.raw_record_id
           AND r.intake_source = 'drop'
     WHERE r.bulk_process_download_id IS NOT NULL
     GROUP BY r.bulk_process_download_id
  ) sub
ON CONFLICT (download_id) DO UPDATE
   SET review_pending = EXCLUDED.review_pending,
       review_approved = EXCLUDED.review_approved,
       fulfill_unset = EXCLUDED.fulfill_unset,
       fulfill_done = EXCLUDED.fulfill_done,
       updated_at = NOW();

-- Set-based backfill: data vertical matching from latest matching_attempts.
INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
SELECT
    sub.download_id,
    'data',
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
               WHEN ma.status = 'success' THEN 'success'
               WHEN ma.status = 'in_flight' THEN 'in_flight'
               WHEN ma.status IN (
                   'submit_error', 'outcome_error', 'timeout', 'failed'
               ) THEN 'failed'
               ELSE 'open'
           END AS bucket
      FROM requests r
      LEFT JOIN matching_attempts ma ON ma.request_id = r.id
     WHERE r.bulk_process_download_id IS NOT NULL
     ORDER BY r.id, ma.attempt_number DESC NULLS LAST, ma.attempted_at DESC NULLS LAST
  ) sub
 GROUP BY sub.download_id
ON CONFLICT (download_id, vertical, stage) DO UPDATE
   SET total = EXCLUDED.total,
       open = EXCLUDED.open,
       success = EXCLUDED.success,
       failed = EXCLUDED.failed,
       in_flight = EXCLUDED.in_flight,
       updated_at = NOW();

-- Set-based backfill: external vertical matching snapshots.
INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
SELECT
    r.bulk_process_download_id,
    rvm.vertical,
    'matching',
    COUNT(*)::bigint,
    0,
    COUNT(*)::bigint,
    0,
    0
  FROM request_vertical_matching rvm
  JOIN requests r ON r.id = rvm.request_id
 WHERE r.bulk_process_download_id IS NOT NULL
   AND rvm.vertical IN ('auth0', 'communications', 'people_hr', 'axios_hq', 'axios_headquarters')
 GROUP BY r.bulk_process_download_id, rvm.vertical
ON CONFLICT (download_id, vertical, stage) DO UPDATE
   SET total = EXCLUDED.total,
       open = EXCLUDED.open,
       success = EXCLUDED.success,
       failed = EXCLUDED.failed,
       in_flight = EXCLUDED.in_flight,
       updated_at = NOW();

-- Set-based backfill: external vertical review open (matched but not decided).
INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
SELECT
    r.bulk_process_download_id,
    rvm.vertical,
    'review',
    COUNT(*)::bigint,
    COUNT(*)::bigint,
    0,
    0,
    0
  FROM request_vertical_matching rvm
  JOIN requests r ON r.id = rvm.request_id
 WHERE r.bulk_process_download_id IS NOT NULL
   AND rvm.vertical IN ('auth0', 'communications', 'people_hr', 'axios_hq', 'axios_headquarters')
   AND NOT EXISTS (
       SELECT 1
         FROM request_vertical_dispositions rvd
        WHERE rvd.request_id = rvm.request_id
          AND rvd.vertical = rvm.vertical
   )
 GROUP BY r.bulk_process_download_id, rvm.vertical
ON CONFLICT (download_id, vertical, stage) DO UPDATE
   SET total = EXCLUDED.total,
       open = EXCLUDED.open,
       success = EXCLUDED.success,
       failed = EXCLUDED.failed,
       in_flight = EXCLUDED.in_flight,
       updated_at = NOW();

-- Set-based backfill: external vertical fulfillment decided.
INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
SELECT
    r.bulk_process_download_id,
    rvd.vertical,
    'fulfillment',
    COUNT(*)::bigint,
    0,
    COUNT(*)::bigint,
    0,
    0
  FROM request_vertical_dispositions rvd
  JOIN requests r ON r.id = rvd.request_id
 WHERE r.bulk_process_download_id IS NOT NULL
   AND rvd.vertical IN ('auth0', 'communications', 'people_hr', 'axios_hq', 'axios_headquarters')
 GROUP BY r.bulk_process_download_id, rvd.vertical
ON CONFLICT (download_id, vertical, stage) DO UPDATE
   SET total = EXCLUDED.total,
       open = EXCLUDED.open,
       success = EXCLUDED.success,
       failed = EXCLUDED.failed,
       in_flight = EXCLUDED.in_flight,
       updated_at = NOW();

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON drop_bulk_vertical_stats FROM app_user;
        GRANT SELECT, INSERT, UPDATE ON drop_bulk_vertical_stats TO app_user;

        GRANT EXECUTE ON FUNCTION core_ensure_drop_bulk_vertical_stats(
            BIGINT, VARCHAR, VARCHAR
        ) TO app_user;
        GRANT EXECUTE ON FUNCTION core_drop_bulk_process_review_delta(
            BIGINT, TEXT, TEXT
        ) TO app_user;
        GRANT EXECUTE ON FUNCTION core_drop_bulk_process_fulfill_delta(
            BIGINT, SMALLINT, SMALLINT, INT
        ) TO app_user;
        GRANT EXECUTE ON FUNCTION core_vertical_data_matching_status_bucket(TEXT) TO app_user;
        GRANT EXECUTE ON FUNCTION core_drop_bulk_vertical_data_matching_delta(
            BIGINT, TEXT, TEXT
        ) TO app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS request_vertical_dispositions_bulk_stats ON request_vertical_dispositions;
DROP FUNCTION IF EXISTS core_request_vertical_dispositions_bulk_stats();

DROP TRIGGER IF EXISTS request_vertical_matching_bulk_stats ON request_vertical_matching;
DROP FUNCTION IF EXISTS core_request_vertical_matching_bulk_stats();

DROP TRIGGER IF EXISTS matching_attempts_vertical_data_stats ON matching_attempts;
DROP FUNCTION IF EXISTS core_matching_attempts_vertical_data_stats();
DROP FUNCTION IF EXISTS core_drop_bulk_vertical_data_matching_delta(BIGINT, TEXT, TEXT);
DROP FUNCTION IF EXISTS core_vertical_data_matching_status_bucket(TEXT);

DROP TRIGGER IF EXISTS drop_raw_response_status_bulk_stats ON drop_raw_requests;
DROP FUNCTION IF EXISTS core_drop_raw_response_status_bulk_stats();

DROP TRIGGER IF EXISTS approval_requests_bulk_stats ON approval_requests;
DROP FUNCTION IF EXISTS core_approval_requests_bulk_stats();

DROP FUNCTION IF EXISTS core_drop_bulk_process_fulfill_delta(BIGINT, SMALLINT, SMALLINT, INT);
DROP FUNCTION IF EXISTS core_drop_bulk_process_review_delta(BIGINT, TEXT, TEXT);
DROP FUNCTION IF EXISTS core_ensure_drop_bulk_vertical_stats(BIGINT, VARCHAR, VARCHAR);

-- Restore the original request insert trigger without fulfillment/vertical logic.
CREATE OR REPLACE FUNCTION core_requests_bulk_stats_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
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
    RETURN NEW;
END;
$$;

DROP TABLE IF EXISTS drop_bulk_vertical_stats;

ALTER TABLE drop_bulk_process_stats
    DROP CONSTRAINT IF EXISTS drop_bulk_process_stats_counts_nonneg,
    ADD CONSTRAINT drop_bulk_process_stats_counts_nonneg
        CHECK (
            request_rows >= 0
            AND matching_pending >= 0
            AND matching_claimed >= 0
            AND matching_in_flight >= 0
            AND matching_success >= 0
            AND matching_failed >= 0
            AND matching_abandoned >= 0
            AND matching_none >= 0
        ),
    DROP COLUMN IF EXISTS review_pending,
    DROP COLUMN IF EXISTS review_approved,
    DROP COLUMN IF EXISTS fulfill_unset,
    DROP COLUMN IF EXISTS fulfill_done;
