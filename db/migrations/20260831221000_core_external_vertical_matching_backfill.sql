-- migrate:up transaction:false
-- Heavy backfill for external vertical matching stats (split from 20260831220000).
-- Runs outside a transaction so CREATE INDEX CONCURRENTLY is allowed.

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_axios_headquarters_attempts_request_matching
    ON axios_headquarters_attempts (request_id, attempt_number DESC, attempted_at DESC)
    WHERE step = 'matching';

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_paylocity_attempts_request_matching
    ON paylocity_attempts (request_id, attempt_number DESC, attempted_at DESC)
    WHERE step = 'matching';

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lever_attempts_request_matching
    ON lever_attempts (request_id, attempt_number DESC, attempted_at DESC)
    WHERE step = 'matching';

-- Drop legacy axios_headquarters vertical key from snapshot era.
DELETE FROM drop_bulk_vertical_stats
 WHERE vertical IN ('axios_headquarters', 'communications')
   AND stage = 'matching';

INSERT INTO drop_bulk_vertical_stats (
    download_id, vertical, stage, total, open, success, failed, in_flight
)
WITH email_requests AS (
    SELECT r.id AS request_id, r.bulk_process_download_id AS download_id
      FROM requests r
      JOIN drop_raw_requests drr
        ON r.intake_source = 'drop'
       AND r.raw_record_id = drr.id
       AND drr.list_type = 'Email'
     WHERE r.bulk_process_download_id IS NOT NULL
),
latest_ax AS (
    SELECT DISTINCT ON (request_id)
           request_id,
           status
      FROM axios_headquarters_attempts
     WHERE step = 'matching'
     ORDER BY request_id, attempt_number DESC, attempted_at DESC
),
bucketed AS (
    SELECT
        er.download_id,
        CASE
            WHEN ax.status IS NULL THEN 'open'
            WHEN ax.status = 'success' THEN 'success'
            WHEN ax.status = 'in_flight' THEN 'in_flight'
            WHEN ax.status IN (
                'submit_error', 'outcome_error', 'timeout', 'failed'
            ) THEN 'failed'
            ELSE 'open'
        END AS bucket
      FROM email_requests er
      LEFT JOIN latest_ax ax ON ax.request_id = er.request_id
)
SELECT
    download_id,
    'communications',
    'matching',
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE bucket = 'open')::bigint,
    COUNT(*) FILTER (WHERE bucket = 'success')::bigint,
    COUNT(*) FILTER (WHERE bucket = 'failed')::bigint,
    COUNT(*) FILTER (WHERE bucket = 'in_flight')::bigint
  FROM bucketed
 GROUP BY download_id
ON CONFLICT (download_id, vertical, stage) DO UPDATE
   SET total = EXCLUDED.total,
       open = EXCLUDED.open,
       success = EXCLUDED.success,
       failed = EXCLUDED.failed,
       in_flight = EXCLUDED.in_flight,
       updated_at = NOW();

DELETE FROM drop_bulk_vertical_stats
 WHERE vertical = 'people_hr'
   AND stage = 'matching';

DO $$
BEGIN
    IF to_regclass('public.hr_alumni_attempts') IS NOT NULL THEN
        EXECUTE $sql$
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_hr_alumni_attempts_request_matching
                ON hr_alumni_attempts (request_id, attempt_number DESC, attempted_at DESC)
                WHERE step = 'matching'
        $sql$;

        INSERT INTO drop_bulk_vertical_stats (
            download_id, vertical, stage, total, open, success, failed, in_flight
        )
        WITH email_requests AS (
            SELECT r.id AS request_id, r.bulk_process_download_id AS download_id
              FROM requests r
              JOIN drop_raw_requests drr
                ON r.intake_source = 'drop'
               AND r.raw_record_id = drr.id
               AND drr.list_type = 'Email'
             WHERE r.bulk_process_download_id IS NOT NULL
        ),
        latest_pay AS (
            SELECT DISTINCT ON (request_id)
                   request_id, status
              FROM paylocity_attempts
             WHERE step = 'matching'
             ORDER BY request_id, attempt_number DESC, attempted_at DESC
        ),
        latest_lev AS (
            SELECT DISTINCT ON (request_id)
                   request_id, status
              FROM lever_attempts
             WHERE step = 'matching'
             ORDER BY request_id, attempt_number DESC, attempted_at DESC
        ),
        latest_hr AS (
            SELECT DISTINCT ON (request_id)
                   request_id, status
              FROM hr_alumni_attempts
             WHERE step = 'matching'
             ORDER BY request_id, attempt_number DESC, attempted_at DESC
        ),
        bucketed AS (
            SELECT
                er.download_id,
                CASE
                    WHEN pay.status IN (
                        'submit_error', 'outcome_error', 'timeout', 'failed'
                    ) OR lev.status IN (
                        'submit_error', 'outcome_error', 'timeout', 'failed'
                    ) OR hr.status IN (
                        'submit_error', 'outcome_error', 'timeout', 'failed'
                    ) THEN 'failed'
                    WHEN pay.status = 'in_flight'
                      OR lev.status = 'in_flight'
                      OR hr.status = 'in_flight' THEN 'in_flight'
                    WHEN pay.status IS NULL
                     AND lev.status IS NULL
                     AND hr.status IS NULL THEN 'open'
                    WHEN pay.status IN ('pending', 'claimed', 'abandoned')
                      OR lev.status IN ('pending', 'claimed', 'abandoned')
                      OR hr.status IN ('pending', 'claimed', 'abandoned') THEN 'open'
                    WHEN (pay.status IS NULL OR pay.status = 'success')
                     AND (lev.status IS NULL OR lev.status = 'success')
                     AND (hr.status IS NULL OR hr.status = 'success')
                     AND (
                         pay.status IS NOT NULL
                         OR lev.status IS NOT NULL
                         OR hr.status IS NOT NULL
                     ) THEN 'success'
                    ELSE 'open'
                END AS bucket
              FROM email_requests er
              LEFT JOIN latest_pay pay ON pay.request_id = er.request_id
              LEFT JOIN latest_lev lev ON lev.request_id = er.request_id
              LEFT JOIN latest_hr hr ON hr.request_id = er.request_id
        )
        SELECT
            download_id,
            'people_hr',
            'matching',
            COUNT(*)::bigint,
            COUNT(*) FILTER (WHERE bucket = 'open')::bigint,
            COUNT(*) FILTER (WHERE bucket = 'success')::bigint,
            COUNT(*) FILTER (WHERE bucket = 'failed')::bigint,
            COUNT(*) FILTER (WHERE bucket = 'in_flight')::bigint
          FROM bucketed
         GROUP BY download_id
        ON CONFLICT (download_id, vertical, stage) DO UPDATE
           SET total = EXCLUDED.total,
               open = EXCLUDED.open,
               success = EXCLUDED.success,
               failed = EXCLUDED.failed,
               in_flight = EXCLUDED.in_flight,
               updated_at = NOW();
    ELSE
        INSERT INTO drop_bulk_vertical_stats (
            download_id, vertical, stage, total, open, success, failed, in_flight
        )
        WITH email_requests AS (
            SELECT r.id AS request_id, r.bulk_process_download_id AS download_id
              FROM requests r
              JOIN drop_raw_requests drr
                ON r.intake_source = 'drop'
               AND r.raw_record_id = drr.id
               AND drr.list_type = 'Email'
             WHERE r.bulk_process_download_id IS NOT NULL
        ),
        latest_pay AS (
            SELECT DISTINCT ON (request_id)
                   request_id, status
              FROM paylocity_attempts
             WHERE step = 'matching'
             ORDER BY request_id, attempt_number DESC, attempted_at DESC
        ),
        latest_lev AS (
            SELECT DISTINCT ON (request_id)
                   request_id, status
              FROM lever_attempts
             WHERE step = 'matching'
             ORDER BY request_id, attempt_number DESC, attempted_at DESC
        ),
        bucketed AS (
            SELECT
                er.download_id,
                CASE
                    WHEN pay.status IN (
                        'submit_error', 'outcome_error', 'timeout', 'failed'
                    ) OR lev.status IN (
                        'submit_error', 'outcome_error', 'timeout', 'failed'
                    ) THEN 'failed'
                    WHEN pay.status = 'in_flight'
                      OR lev.status = 'in_flight' THEN 'in_flight'
                    WHEN pay.status IS NULL AND lev.status IS NULL THEN 'open'
                    WHEN pay.status IN ('pending', 'claimed', 'abandoned')
                      OR lev.status IN ('pending', 'claimed', 'abandoned') THEN 'open'
                    WHEN (pay.status IS NULL OR pay.status = 'success')
                     AND (lev.status IS NULL OR lev.status = 'success')
                     AND (pay.status IS NOT NULL OR lev.status IS NOT NULL)
                     THEN 'success'
                    ELSE 'open'
                END AS bucket
              FROM email_requests er
              LEFT JOIN latest_pay pay ON pay.request_id = er.request_id
              LEFT JOIN latest_lev lev ON lev.request_id = er.request_id
        )
        SELECT
            download_id,
            'people_hr',
            'matching',
            COUNT(*)::bigint,
            COUNT(*) FILTER (WHERE bucket = 'open')::bigint,
            COUNT(*) FILTER (WHERE bucket = 'success')::bigint,
            COUNT(*) FILTER (WHERE bucket = 'failed')::bigint,
            COUNT(*) FILTER (WHERE bucket = 'in_flight')::bigint
          FROM bucketed
         GROUP BY download_id
        ON CONFLICT (download_id, vertical, stage) DO UPDATE
           SET total = EXCLUDED.total,
               open = EXCLUDED.open,
               success = EXCLUDED.success,
               failed = EXCLUDED.failed,
               in_flight = EXCLUDED.in_flight,
               updated_at = NOW();
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.bizdev_contacts_attempts') IS NULL THEN
        RETURN;
    END IF;

    EXECUTE $sql$
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_bizdev_contacts_attempts_request_matching
            ON bizdev_contacts_attempts (request_id, attempt_number DESC, attempted_at DESC)
            WHERE step = 'matching'
    $sql$;

    DELETE FROM drop_bulk_vertical_stats
     WHERE vertical = 'bizdev'
       AND stage = 'matching';

    INSERT INTO drop_bulk_vertical_stats (
        download_id, vertical, stage, total, open, success, failed, in_flight
    )
    WITH email_requests AS (
        SELECT r.id AS request_id, r.bulk_process_download_id AS download_id
          FROM requests r
          JOIN drop_raw_requests drr
            ON r.intake_source = 'drop'
           AND r.raw_record_id = drr.id
           AND drr.list_type = 'Email'
         WHERE r.bulk_process_download_id IS NOT NULL
    ),
    latest_biz AS (
        SELECT DISTINCT ON (request_id)
               request_id, status
          FROM bizdev_contacts_attempts
         WHERE step = 'matching'
         ORDER BY request_id, attempt_number DESC, attempted_at DESC
    ),
    bucketed AS (
        SELECT
            er.download_id,
            CASE
                WHEN biz.status IS NULL THEN 'open'
                WHEN biz.status = 'success' THEN 'success'
                WHEN biz.status = 'in_flight' THEN 'in_flight'
                WHEN biz.status IN (
                    'submit_error', 'outcome_error', 'timeout', 'failed'
                ) THEN 'failed'
                ELSE 'open'
            END AS bucket
          FROM email_requests er
          LEFT JOIN latest_biz biz ON biz.request_id = er.request_id
    )
    SELECT
        download_id,
        'bizdev',
        'matching',
        COUNT(*)::bigint,
        COUNT(*) FILTER (WHERE bucket = 'open')::bigint,
        COUNT(*) FILTER (WHERE bucket = 'success')::bigint,
        COUNT(*) FILTER (WHERE bucket = 'failed')::bigint,
        COUNT(*) FILTER (WHERE bucket = 'in_flight')::bigint
      FROM bucketed
     GROUP BY download_id
    ON CONFLICT (download_id, vertical, stage) DO UPDATE
       SET total = EXCLUDED.total,
           open = EXCLUDED.open,
           success = EXCLUDED.success,
           failed = EXCLUDED.failed,
           in_flight = EXCLUDED.in_flight,
           updated_at = NOW();
END $$;

-- migrate:down transaction:false
DROP INDEX CONCURRENTLY IF EXISTS ix_bizdev_contacts_attempts_request_matching;
DROP INDEX CONCURRENTLY IF EXISTS ix_hr_alumni_attempts_request_matching;
DROP INDEX CONCURRENTLY IF EXISTS ix_lever_attempts_request_matching;
DROP INDEX CONCURRENTLY IF EXISTS ix_paylocity_attempts_request_matching;
DROP INDEX CONCURRENTLY IF EXISTS ix_axios_headquarters_attempts_request_matching;

DELETE FROM drop_bulk_vertical_stats
 WHERE vertical IN ('communications', 'people_hr', 'bizdev')
   AND stage = 'matching';
