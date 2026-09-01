-- migrate:up
-- Wire remaining Email vertical workers into drop_bulk_vertical_stats using
-- attempt queues (not snapshots). Auth0 was fixed in 20260831210000.

CREATE OR REPLACE FUNCTION core_drop_bulk_vertical_matching_delta(
    p_download_id BIGINT,
    p_vertical VARCHAR,
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
    IF p_download_id IS NULL OR p_vertical IS NULL OR btrim(p_vertical) = '' THEN
        RETURN;
    END IF;

    v_old_bucket := core_vertical_data_matching_status_bucket(p_old_status);
    v_new_bucket := core_vertical_data_matching_status_bucket(p_new_status);

    IF v_old_bucket IS NULL AND v_new_bucket IS NULL THEN
        RETURN;
    END IF;

    PERFORM core_ensure_drop_bulk_vertical_stats(p_download_id, p_vertical, 'matching');
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
       AND vertical = p_vertical
       AND stage = 'matching';
END;
$$;

CREATE OR REPLACE FUNCTION core_drop_bulk_vertical_auth0_matching_delta(
    p_download_id BIGINT,
    p_old_status TEXT,
    p_new_status TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM core_drop_bulk_vertical_matching_delta(
        p_download_id, 'auth0', p_old_status, p_new_status
    );
END;
$$;

CREATE OR REPLACE FUNCTION core_latest_external_matching_status(
    p_request_id UUID,
    p_attempts_table TEXT
)
RETURNS TEXT
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_status TEXT;
BEGIN
    IF p_attempts_table NOT IN (
        'paylocity_attempts', 'lever_attempts', 'hr_alumni_attempts'
    ) THEN
        RETURN NULL;
    END IF;

    EXECUTE format(
        'SELECT status
           FROM %I
          WHERE request_id = $1
            AND step = ''matching''
          ORDER BY attempt_number DESC, attempted_at DESC
          LIMIT 1',
        p_attempts_table
    )
    INTO v_status
    USING p_request_id;

    RETURN v_status;
END;
$$;

CREATE OR REPLACE FUNCTION core_people_hr_matching_bucket(
    p_request_id UUID,
    p_override_table TEXT DEFAULT NULL,
    p_override_status TEXT DEFAULT NULL,
    p_exclude_table TEXT DEFAULT NULL
)
RETURNS TEXT
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_tables TEXT[] := ARRAY[
        'paylocity_attempts', 'lever_attempts', 'hr_alumni_attempts'
    ];
    v_table TEXT;
    v_status TEXT;
    v_present BOOLEAN := FALSE;
    v_all_success BOOLEAN := TRUE;
BEGIN
    FOREACH v_table IN ARRAY v_tables
    LOOP
        IF p_exclude_table IS NOT NULL AND v_table = p_exclude_table THEN
            CONTINUE;
        END IF;

        IF p_override_table IS NOT NULL AND v_table = p_override_table THEN
            v_status := p_override_status;
        ELSE
            v_status := core_latest_external_matching_status(p_request_id, v_table);
        END IF;

        IF v_status IS NULL THEN
            CONTINUE;
        END IF;

        v_present := TRUE;

        IF v_status IN ('submit_error', 'outcome_error', 'timeout', 'failed') THEN
            RETURN 'failed';
        END IF;
        IF v_status = 'in_flight' THEN
            RETURN 'in_flight';
        END IF;
        IF core_vertical_data_matching_status_bucket(v_status) = 'open' THEN
            RETURN 'open';
        END IF;
        IF v_status <> 'success' THEN
            v_all_success := FALSE;
        END IF;
    END LOOP;

    IF NOT v_present THEN
        RETURN 'open';
    END IF;
    IF v_all_success THEN
        RETURN 'success';
    END IF;
    RETURN 'open';
END;
$$;

CREATE OR REPLACE FUNCTION core_people_hr_attempts_vertical_stats()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_download_id BIGINT;
    v_is_latest BOOLEAN;
    v_old_bucket TEXT;
    v_new_bucket TEXT;
    v_request_id UUID;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    IF NEW.step <> 'matching' THEN
        RETURN NEW;
    END IF;

    v_request_id := NEW.request_id;

    SELECT r.bulk_process_download_id
      INTO v_download_id
      FROM requests r
     WHERE r.id = v_request_id;

    IF v_download_id IS NULL THEN
        RETURN NEW;
    END IF;

    EXECUTE format(
        'SELECT NOT EXISTS (
             SELECT 1
               FROM %I aa
              WHERE aa.request_id = $1
                AND aa.step = $2
                AND aa.attempt_number > $3
         )',
        TG_TABLE_NAME
    )
    INTO v_is_latest
    USING v_request_id, NEW.step, NEW.attempt_number;

    IF NOT v_is_latest THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_old_bucket := core_people_hr_matching_bucket(
            v_request_id, p_exclude_table := TG_TABLE_NAME
        );
        v_new_bucket := core_people_hr_matching_bucket(v_request_id);
    ELSIF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        v_old_bucket := core_people_hr_matching_bucket(
            v_request_id, TG_TABLE_NAME, OLD.status
        );
        v_new_bucket := core_people_hr_matching_bucket(v_request_id);
    ELSE
        RETURN NEW;
    END IF;

    IF v_old_bucket IS DISTINCT FROM v_new_bucket THEN
        PERFORM core_drop_bulk_vertical_matching_delta(
            v_download_id,
            'people_hr',
            v_old_bucket,
            v_new_bucket
        );
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION core_single_vertical_attempts_stats()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_download_id BIGINT;
    v_vertical VARCHAR;
    v_is_latest BOOLEAN;
    v_prev_status TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    v_vertical := CASE TG_TABLE_NAME
        WHEN 'axios_headquarters_attempts' THEN 'communications'
        WHEN 'bizdev_contacts_attempts' THEN 'bizdev'
        ELSE NULL
    END;

    IF v_vertical IS NULL OR NEW.step <> 'matching' THEN
        RETURN NEW;
    END IF;

    SELECT r.bulk_process_download_id
      INTO v_download_id
      FROM requests r
     WHERE r.id = NEW.request_id;

    IF v_download_id IS NULL THEN
        RETURN NEW;
    END IF;

    EXECUTE format(
        'SELECT NOT EXISTS (
             SELECT 1
               FROM %I aa
              WHERE aa.request_id = $1
                AND aa.step = $2
                AND aa.attempt_number > $3
         )',
        TG_TABLE_NAME
    )
    INTO v_is_latest
    USING NEW.request_id, NEW.step, NEW.attempt_number;

    IF NOT v_is_latest THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.attempt_number > 1 THEN
            EXECUTE format(
                'SELECT aa.status
                   FROM %I aa
                  WHERE aa.request_id = $1
                    AND aa.step = $2
                    AND aa.attempt_number < $3
                  ORDER BY aa.attempt_number DESC
                  LIMIT 1',
                TG_TABLE_NAME
            )
            INTO v_prev_status
            USING NEW.request_id, NEW.step, NEW.attempt_number;
        ELSE
            v_prev_status := 'none';
        END IF;
        PERFORM core_drop_bulk_vertical_matching_delta(
            v_download_id, v_vertical, v_prev_status, NEW.status
        );
    ELSIF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
        PERFORM core_drop_bulk_vertical_matching_delta(
            v_download_id, v_vertical, OLD.status, NEW.status
        );
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION core_people_hr_attempts_vertical_stats() FROM PUBLIC;
REVOKE ALL ON FUNCTION core_single_vertical_attempts_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core_people_hr_attempts_vertical_stats() TO PUBLIC;
GRANT EXECUTE ON FUNCTION core_single_vertical_attempts_stats() TO PUBLIC;

DROP TRIGGER IF EXISTS axios_headquarters_attempts_vertical_stats
    ON axios_headquarters_attempts;
CREATE TRIGGER axios_headquarters_attempts_vertical_stats
    AFTER INSERT OR UPDATE OF status ON axios_headquarters_attempts
    FOR EACH ROW
    EXECUTE FUNCTION core_single_vertical_attempts_stats();

DROP TRIGGER IF EXISTS bizdev_contacts_attempts_vertical_stats
    ON bizdev_contacts_attempts;
CREATE TRIGGER bizdev_contacts_attempts_vertical_stats
    AFTER INSERT OR UPDATE OF status ON bizdev_contacts_attempts
    FOR EACH ROW
    EXECUTE FUNCTION core_single_vertical_attempts_stats();

DROP TRIGGER IF EXISTS paylocity_attempts_vertical_stats ON paylocity_attempts;
CREATE TRIGGER paylocity_attempts_vertical_stats
    AFTER INSERT OR UPDATE OF status ON paylocity_attempts
    FOR EACH ROW
    EXECUTE FUNCTION core_people_hr_attempts_vertical_stats();

DROP TRIGGER IF EXISTS lever_attempts_vertical_stats ON lever_attempts;
CREATE TRIGGER lever_attempts_vertical_stats
    AFTER INSERT OR UPDATE OF status ON lever_attempts
    FOR EACH ROW
    EXECUTE FUNCTION core_people_hr_attempts_vertical_stats();

DROP TRIGGER IF EXISTS hr_alumni_attempts_vertical_stats ON hr_alumni_attempts;
CREATE TRIGGER hr_alumni_attempts_vertical_stats
    AFTER INSERT OR UPDATE OF status ON hr_alumni_attempts
    FOR EACH ROW
    EXECUTE FUNCTION core_people_hr_attempts_vertical_stats();

CREATE OR REPLACE FUNCTION core_seed_email_vertical_matching_open(
    p_download_id BIGINT,
    p_vertical VARCHAR
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM core_ensure_drop_bulk_vertical_stats(p_download_id, p_vertical, 'matching');
    UPDATE drop_bulk_vertical_stats
       SET total = total + 1,
           open = open + 1,
           updated_at = NOW()
     WHERE download_id = p_download_id
       AND vertical = p_vertical
       AND stage = 'matching';
END;
$$;

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
            PERFORM core_seed_email_vertical_matching_open(
                NEW.bulk_process_download_id, 'auth0'
            );
            PERFORM core_seed_email_vertical_matching_open(
                NEW.bulk_process_download_id, 'communications'
            );
            PERFORM core_seed_email_vertical_matching_open(
                NEW.bulk_process_download_id, 'people_hr'
            );
            PERFORM core_seed_email_vertical_matching_open(
                NEW.bulk_process_download_id, 'bizdev'
            );
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

-- Backfill communications (Axios HQ attempts).
DELETE FROM drop_bulk_vertical_stats
 WHERE vertical = 'communications'
   AND stage = 'matching';

INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
SELECT
    sub.download_id,
    'communications',
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
      LEFT JOIN axios_headquarters_attempts aa
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

-- Backfill people_hr (composite paylocity + lever + hr_alumni).
DELETE FROM drop_bulk_vertical_stats
 WHERE vertical = 'people_hr'
   AND stage = 'matching';

INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
SELECT
    sub.download_id,
    'people_hr',
    'matching',
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE sub.bucket = 'open')::bigint,
    COUNT(*) FILTER (WHERE sub.bucket = 'success')::bigint,
    COUNT(*) FILTER (WHERE sub.bucket = 'failed')::bigint,
    COUNT(*) FILTER (WHERE sub.bucket = 'in_flight')::bigint
  FROM (
    SELECT
           r.bulk_process_download_id AS download_id,
           core_people_hr_matching_bucket(r.id) AS bucket
      FROM requests r
      JOIN drop_raw_requests drr
        ON r.intake_source = 'drop'
       AND r.raw_record_id = drr.id
       AND drr.list_type = 'Email'
     WHERE r.bulk_process_download_id IS NOT NULL
  ) sub
 GROUP BY sub.download_id
ON CONFLICT (download_id, vertical, stage) DO UPDATE
   SET total = EXCLUDED.total,
       open = EXCLUDED.open,
       success = EXCLUDED.success,
       failed = EXCLUDED.failed,
       in_flight = EXCLUDED.in_flight,
       updated_at = NOW();

-- Backfill bizdev (Contact Us sheet attempts).
DELETE FROM drop_bulk_vertical_stats
 WHERE vertical = 'bizdev'
   AND stage = 'matching';

INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
SELECT
    sub.download_id,
    'bizdev',
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
      LEFT JOIN bizdev_contacts_attempts aa
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
        GRANT EXECUTE ON FUNCTION core_drop_bulk_vertical_matching_delta(
            BIGINT, VARCHAR, TEXT, TEXT
        ) TO app_user;
        GRANT EXECUTE ON FUNCTION core_latest_external_matching_status(
            UUID, TEXT
        ) TO app_user;
        GRANT EXECUTE ON FUNCTION core_people_hr_matching_bucket(
            UUID, TEXT, TEXT, TEXT
        ) TO app_user;
        GRANT EXECUTE ON FUNCTION core_seed_email_vertical_matching_open(
            BIGINT, VARCHAR
        ) TO app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS hr_alumni_attempts_vertical_stats ON hr_alumni_attempts;
DROP TRIGGER IF EXISTS lever_attempts_vertical_stats ON lever_attempts;
DROP TRIGGER IF EXISTS paylocity_attempts_vertical_stats ON paylocity_attempts;
DROP TRIGGER IF EXISTS bizdev_contacts_attempts_vertical_stats ON bizdev_contacts_attempts;
DROP TRIGGER IF EXISTS axios_headquarters_attempts_vertical_stats ON axios_headquarters_attempts;

DROP FUNCTION IF EXISTS core_single_vertical_attempts_stats();
DROP FUNCTION IF EXISTS core_people_hr_attempts_vertical_stats();
DROP FUNCTION IF EXISTS core_people_hr_matching_bucket(UUID, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS core_latest_external_matching_status(UUID, TEXT);
DROP FUNCTION IF EXISTS core_seed_email_vertical_matching_open(BIGINT, VARCHAR);
DROP FUNCTION IF EXISTS core_drop_bulk_vertical_matching_delta(BIGINT, VARCHAR, TEXT, TEXT);

-- Restore auth0-only request insert from 20260831210000.
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
