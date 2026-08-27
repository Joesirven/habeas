-- migrate:up
-- Exact per-download matching rollup (Jose A+D plus B).
-- drop_connector_attempts is terminal-immutable after download success, so
-- counters live on sibling drop_bulk_process_stats keyed by that id.
-- requests.bulk_process_download_id is set only at promote INSERT (fill-once
-- backfill allowed). Counts / timestamps only — no PII.

ALTER TABLE requests
    ADD COLUMN IF NOT EXISTS bulk_process_download_id BIGINT
        REFERENCES drop_connector_attempts (id);

CREATE INDEX IF NOT EXISTS ix_requests_bulk_process_download_id
    ON requests (bulk_process_download_id)
    WHERE bulk_process_download_id IS NOT NULL;

COMMENT ON COLUMN requests.bulk_process_download_id IS
    'Immutable DROP download attempt id (drop_connector_attempts.id). Set at promote INSERT; fill-once backfill only.';

CREATE TABLE drop_bulk_process_stats (
    download_id              BIGINT PRIMARY KEY
        REFERENCES drop_connector_attempts (id),
    request_rows             INT NOT NULL DEFAULT 0,
    matching_pending         INT NOT NULL DEFAULT 0,
    matching_claimed         INT NOT NULL DEFAULT 0,
    matching_in_flight       INT NOT NULL DEFAULT 0,
    matching_success         INT NOT NULL DEFAULT 0,
    matching_failed          INT NOT NULL DEFAULT 0,
    matching_abandoned       INT NOT NULL DEFAULT 0,
    matching_none            INT NOT NULL DEFAULT 0,
    matching_started_at      TIMESTAMPTZ,
    matching_completed_at    TIMESTAMPTZ,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT drop_bulk_process_stats_counts_nonneg
        CHECK (
            request_rows >= 0
            AND matching_pending >= 0
            AND matching_claimed >= 0
            AND matching_in_flight >= 0
            AND matching_success >= 0
            AND matching_failed >= 0
            AND matching_abandoned >= 0
            AND matching_none >= 0
        )
);

COMMENT ON TABLE drop_bulk_process_stats IS
    'Per-download matching counters for pipeline expand. Counts and timestamps only — never PII.';

CREATE OR REPLACE FUNCTION core_forbid_requests_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'requests rows are immutable (id=%)', OLD.id;
    END IF;
    -- Fill-once: NULL → download id. All other columns must stay unchanged.
    IF TG_OP = 'UPDATE'
       AND OLD.bulk_process_download_id IS NULL
       AND NEW.bulk_process_download_id IS NOT NULL
       AND NEW.id IS NOT DISTINCT FROM OLD.id
       AND NEW.received_at IS NOT DISTINCT FROM OLD.received_at
       AND NEW.intake_source IS NOT DISTINCT FROM OLD.intake_source
       AND NEW.raw_record_id IS NOT DISTINCT FROM OLD.raw_record_id
       AND NEW.requestor_state IS NOT DISTINCT FROM OLD.requestor_state
       AND NEW.request_type IS NOT DISTINCT FROM OLD.request_type
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'requests rows are immutable (id=%)', OLD.id;
END;
$$;

CREATE OR REPLACE FUNCTION core_ensure_drop_bulk_process_stats(p_download_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_download_id IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO drop_bulk_process_stats (download_id)
    VALUES (p_download_id)
    ON CONFLICT (download_id) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION core_matching_status_bucket(p_status TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN p_status = 'pending' THEN 'pending'
        WHEN p_status = 'claimed' THEN 'claimed'
        WHEN p_status = 'in_flight' THEN 'in_flight'
        WHEN p_status = 'success' THEN 'success'
        WHEN p_status = 'abandoned' THEN 'abandoned'
        WHEN p_status IN (
            'submit_error', 'outcome_error', 'timeout', 'failed'
        ) THEN 'failed'
        ELSE NULL
    END;
$$;

CREATE OR REPLACE FUNCTION core_drop_bulk_matching_delta(
    p_download_id BIGINT,
    p_status TEXT,
    p_delta INT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_bucket TEXT;
BEGIN
    IF p_download_id IS NULL OR p_delta = 0 THEN
        RETURN;
    END IF;
    v_bucket := core_matching_status_bucket(p_status);
    IF v_bucket IS NULL THEN
        RETURN;
    END IF;
    PERFORM core_ensure_drop_bulk_process_stats(p_download_id);
    UPDATE drop_bulk_process_stats
       SET matching_pending = CASE
               WHEN v_bucket = 'pending'
               THEN GREATEST(0, matching_pending + p_delta) ELSE matching_pending
           END,
           matching_claimed = CASE
               WHEN v_bucket = 'claimed'
               THEN GREATEST(0, matching_claimed + p_delta) ELSE matching_claimed
           END,
           matching_in_flight = CASE
               WHEN v_bucket = 'in_flight'
               THEN GREATEST(0, matching_in_flight + p_delta)
               ELSE matching_in_flight
           END,
           matching_success = CASE
               WHEN v_bucket = 'success'
               THEN GREATEST(0, matching_success + p_delta) ELSE matching_success
           END,
           matching_failed = CASE
               WHEN v_bucket = 'failed'
               THEN GREATEST(0, matching_failed + p_delta) ELSE matching_failed
           END,
           matching_abandoned = CASE
               WHEN v_bucket = 'abandoned'
               THEN GREATEST(0, matching_abandoned + p_delta)
               ELSE matching_abandoned
           END,
           updated_at = NOW()
     WHERE download_id = p_download_id;
    UPDATE drop_bulk_process_stats
       SET matching_none = GREATEST(
               0,
               request_rows
               - matching_pending
               - matching_claimed
               - matching_in_flight
               - matching_success
               - matching_failed
               - matching_abandoned
           ),
           matching_completed_at = CASE
               WHEN request_rows > 0
                AND matching_pending = 0
                AND matching_claimed = 0
                AND matching_in_flight = 0
                AND GREATEST(
                    0,
                    request_rows
                    - matching_pending
                    - matching_claimed
                    - matching_in_flight
                    - matching_success
                    - matching_failed
                    - matching_abandoned
                ) = 0
               THEN COALESCE(matching_completed_at, NOW())
               ELSE NULL
           END,
           updated_at = NOW()
     WHERE download_id = p_download_id;
END;
$$;

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

DROP TRIGGER IF EXISTS requests_bulk_stats_insert ON requests;
CREATE TRIGGER requests_bulk_stats_insert
    AFTER INSERT ON requests
    FOR EACH ROW
    EXECUTE FUNCTION core_requests_bulk_stats_insert();

CREATE OR REPLACE FUNCTION core_matching_attempts_bulk_stats()
RETURNS trigger
LANGUAGE plpgsql
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
            IF v_prev_status IS NOT NULL THEN
                PERFORM core_drop_bulk_matching_delta(
                    v_download_id, v_prev_status, -1
                );
            END IF;
        END IF;
        PERFORM core_drop_bulk_matching_delta(v_download_id, NEW.status, 1);
        UPDATE drop_bulk_process_stats
           SET matching_started_at = COALESCE(matching_started_at, NOW()),
               updated_at = NOW()
         WHERE download_id = v_download_id;
    ELSIF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        PERFORM core_drop_bulk_matching_delta(v_download_id, OLD.status, -1);
        PERFORM core_drop_bulk_matching_delta(v_download_id, NEW.status, 1);
        UPDATE drop_bulk_process_stats
           SET matching_started_at = COALESCE(matching_started_at, NOW()),
               updated_at = NOW()
         WHERE download_id = v_download_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS matching_attempts_bulk_stats ON matching_attempts;
CREATE TRIGGER matching_attempts_bulk_stats
    AFTER INSERT OR UPDATE OF status ON matching_attempts
    FOR EACH ROW
    EXECUTE FUNCTION core_matching_attempts_bulk_stats();

CREATE OR REPLACE FUNCTION core_backfill_drop_bulk_process_stats(p_download_id BIGINT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_gcs_uri TEXT;
    v_membership INT := 0;
    v_request_rows INT := 0;
    v_pending INT := 0;
    v_claimed INT := 0;
    v_in_flight INT := 0;
    v_success INT := 0;
    v_failed INT := 0;
    v_abandoned INT := 0;
    v_none INT := 0;
    v_started TIMESTAMPTZ;
    v_completed TIMESTAMPTZ;
BEGIN
    IF p_download_id IS NULL OR p_download_id < 1 THEN
        RAISE EXCEPTION 'invalid download_id';
    END IF;
    SELECT gcs_uri
      INTO v_gcs_uri
      FROM drop_connector_attempts
     WHERE id = p_download_id
       AND step = 'download';
    IF v_gcs_uri IS NULL OR length(trim(v_gcs_uri)) = 0 THEN
        RAISE EXCEPTION 'download % missing gcs_uri', p_download_id;
    END IF;

    -- One-shot membership walk. Do not run this from HTTP expand.
    UPDATE requests r
       SET bulk_process_download_id = p_download_id
      FROM drop_raw_requests drr
      JOIN drop_ingest_attempts i
        ON i.source_csv_filename = drr.source_csv_filename
       AND i.step = 'land'
       AND i.status = 'success'
       AND i.gcs_uri = v_gcs_uri
     WHERE r.raw_record_id = drr.id
       AND r.intake_source = 'drop'
       AND r.bulk_process_download_id IS NULL;
    GET DIAGNOSTICS v_membership = ROW_COUNT;

    SELECT COUNT(*)::int
      INTO v_request_rows
      FROM requests r
     WHERE r.bulk_process_download_id = p_download_id;

    SELECT
        COUNT(*) FILTER (WHERE lm.status = 'pending')::int,
        COUNT(*) FILTER (WHERE lm.status = 'claimed')::int,
        COUNT(*) FILTER (WHERE lm.status = 'in_flight')::int,
        COUNT(*) FILTER (WHERE lm.status = 'success')::int,
        COUNT(*) FILTER (
            WHERE lm.status IN (
                'submit_error', 'outcome_error', 'timeout', 'failed'
            )
        )::int,
        COUNT(*) FILTER (WHERE lm.status = 'abandoned')::int,
        MIN(lm.attempted_at),
        MAX(lm.completed_at)
      INTO v_pending, v_claimed, v_in_flight, v_success, v_failed,
           v_abandoned, v_started, v_completed
      FROM (
        SELECT DISTINCT ON (ma.request_id)
               ma.status, ma.attempted_at, ma.completed_at
          FROM matching_attempts ma
          JOIN requests r ON r.id = ma.request_id
         WHERE r.bulk_process_download_id = p_download_id
         ORDER BY ma.request_id, ma.attempt_number DESC, ma.attempted_at DESC
      ) lm;

    v_none := GREATEST(
        0,
        v_request_rows - v_pending - v_claimed - v_in_flight
        - v_success - v_failed - v_abandoned
    );

    PERFORM core_ensure_drop_bulk_process_stats(p_download_id);
    UPDATE drop_bulk_process_stats
       SET request_rows = v_request_rows,
           matching_pending = v_pending,
           matching_claimed = v_claimed,
           matching_in_flight = v_in_flight,
           matching_success = v_success,
           matching_failed = v_failed,
           matching_abandoned = v_abandoned,
           matching_none = v_none,
           matching_started_at = v_started,
           matching_completed_at = CASE
               WHEN v_request_rows > 0
                AND v_pending = 0
                AND v_claimed = 0
                AND v_in_flight = 0
                AND v_none = 0
               THEN v_completed
               ELSE NULL
           END,
           updated_at = NOW()
     WHERE download_id = p_download_id;

    -- Counts only — never request ids, hashes, or filenames.
    RETURN jsonb_build_object(
        'download_id', p_download_id,
        'membership_updated', v_membership,
        'request_rows', v_request_rows,
        'matching_pending', v_pending,
        'matching_claimed', v_claimed,
        'matching_in_flight', v_in_flight,
        'matching_success', v_success,
        'matching_failed', v_failed,
        'matching_abandoned', v_abandoned,
        'matching_none', v_none,
        'matching_started_at', v_started,
        'matching_completed_at', CASE
            WHEN v_request_rows > 0
             AND v_pending = 0
             AND v_claimed = 0
             AND v_in_flight = 0
             AND v_none = 0
            THEN v_completed
            ELSE NULL
        END
    );
END;
$$;

REVOKE ALL ON FUNCTION core_backfill_drop_bulk_process_stats(BIGINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core_backfill_drop_bulk_process_stats(BIGINT) TO app_user;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT SELECT, INSERT, UPDATE ON drop_bulk_process_stats TO app_user;
        REVOKE DELETE ON drop_bulk_process_stats FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS matching_attempts_bulk_stats ON matching_attempts;
DROP FUNCTION IF EXISTS core_matching_attempts_bulk_stats();
DROP TRIGGER IF EXISTS requests_bulk_stats_insert ON requests;
DROP FUNCTION IF EXISTS core_requests_bulk_stats_insert();
DROP FUNCTION IF EXISTS core_backfill_drop_bulk_process_stats(BIGINT);
DROP FUNCTION IF EXISTS core_drop_bulk_matching_delta(BIGINT, TEXT, INT);
DROP FUNCTION IF EXISTS core_ensure_drop_bulk_process_stats(BIGINT);
DROP FUNCTION IF EXISTS core_matching_status_bucket(TEXT);

CREATE OR REPLACE FUNCTION core_forbid_requests_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'requests rows are immutable (id=%)', OLD.id;
END;
$$;

DROP TABLE IF EXISTS drop_bulk_process_stats;
DROP INDEX IF EXISTS ix_requests_bulk_process_download_id;
ALTER TABLE requests DROP COLUMN IF EXISTS bulk_process_download_id;
