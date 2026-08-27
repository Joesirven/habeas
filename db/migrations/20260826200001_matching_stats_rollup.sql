-- migrate:up
-- Latest matching outcome per request + parameter rollup.
-- Integers and enums only — no consumer_id, hashes, or other PII.
-- Trigger writers are SECURITY DEFINER, owned by the migration role
-- (table owner / postgres on Cloud SQL). That lets AFTER INSERT on
-- matching_results upsert these tables after REVOKE UPDATE, DELETE
-- from app_user. No ALTER OWNER — the create role is the owner.

CREATE TABLE matching_results_latest (
    request_id   UUID PRIMARY KEY REFERENCES requests (id),
    matched      BOOLEAN NOT NULL,
    match_count  INT NOT NULL,
    matched_via  VARCHAR(50) NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE matching_results_latest IS
    'Newest matching_results row per request. Outcome flags and counts only — never PII.';

CREATE TABLE matching_parameter_stats (
    intake_source    VARCHAR(20) NOT NULL,
    parameter        VARCHAR(50) NOT NULL,
    requestor_state  VARCHAR(2) NOT NULL,
    requests         BIGINT NOT NULL DEFAULT 0,
    exact_single     BIGINT NOT NULL DEFAULT 0,
    any_hit          BIGINT NOT NULL DEFAULT 0,
    multi_hit        BIGINT NOT NULL DEFAULT 0,
    zero_hit         BIGINT NOT NULL DEFAULT 0,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (intake_source, parameter, requestor_state)
);

COMMENT ON TABLE matching_parameter_stats IS
    'Latest-outcome counters keyed by intake source, matched_via, and requestor state. Integers only — never PII.';

COMMENT ON COLUMN matching_parameter_stats.parameter IS
    'matched_via from the current latest outcome (e.g. drop_hash_email).';

CREATE OR REPLACE FUNCTION matching_parameter_stats_apply(
    p_intake_source VARCHAR(20),
    p_parameter VARCHAR(50),
    p_requestor_state VARCHAR(2),
    p_match_count INT,
    p_delta BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF p_intake_source IS NULL
       OR p_parameter IS NULL
       OR p_requestor_state IS NULL
       OR p_delta = 0 THEN
        RETURN;
    END IF;

    INSERT INTO matching_parameter_stats (
        intake_source, parameter, requestor_state
    ) VALUES (
        p_intake_source, p_parameter, p_requestor_state
    )
    ON CONFLICT (intake_source, parameter, requestor_state) DO NOTHING;

    UPDATE matching_parameter_stats
       SET requests = GREATEST(0, requests + p_delta),
           exact_single = GREATEST(
               0,
               exact_single + CASE WHEN p_match_count = 1 THEN p_delta ELSE 0 END
           ),
           any_hit = GREATEST(
               0,
               any_hit + CASE WHEN p_match_count > 0 THEN p_delta ELSE 0 END
           ),
           multi_hit = GREATEST(
               0,
               multi_hit + CASE WHEN p_match_count > 1 THEN p_delta ELSE 0 END
           ),
           zero_hit = GREATEST(
               0,
               zero_hit + CASE WHEN p_match_count = 0 THEN p_delta ELSE 0 END
           ),
           updated_at = NOW()
     WHERE intake_source = p_intake_source
       AND parameter = p_parameter
       AND requestor_state = p_requestor_state;
END;
$$;

CREATE OR REPLACE FUNCTION matching_results_latest_on_insert()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_old_match_count INT;
    v_old_matched_via VARCHAR(50);
    v_old_recorded_at TIMESTAMPTZ;
    v_intake_source VARCHAR(20);
    v_requestor_state VARCHAR(2);
    v_had_latest BOOLEAN;
BEGIN
    SELECT l.match_count, l.matched_via, l.recorded_at
      INTO v_old_match_count, v_old_matched_via, v_old_recorded_at
      FROM matching_results_latest l
     WHERE l.request_id = NEW.request_id;

    v_had_latest := FOUND;

    IF v_had_latest AND NEW.recorded_at <= v_old_recorded_at THEN
        RETURN NEW;
    END IF;

    IF v_had_latest THEN
        UPDATE matching_results_latest
           SET matched = NEW.matched,
               match_count = NEW.match_count,
               matched_via = NEW.matched_via,
               recorded_at = NEW.recorded_at
         WHERE request_id = NEW.request_id;
    ELSE
        INSERT INTO matching_results_latest (
            request_id, matched, match_count, matched_via, recorded_at
        ) VALUES (
            NEW.request_id,
            NEW.matched,
            NEW.match_count,
            NEW.matched_via,
            NEW.recorded_at
        );
    END IF;

    SELECT r.intake_source, r.requestor_state
      INTO v_intake_source, v_requestor_state
      FROM requests r
     WHERE r.id = NEW.request_id;

    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    IF v_had_latest THEN
        PERFORM matching_parameter_stats_apply(
            v_intake_source,
            v_old_matched_via,
            v_requestor_state,
            v_old_match_count,
            -1
        );
    END IF;

    PERFORM matching_parameter_stats_apply(
        v_intake_source,
        NEW.matched_via,
        v_requestor_state,
        NEW.match_count,
        1
    );

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION matching_parameter_stats_apply(
    VARCHAR, VARCHAR, VARCHAR, INT, BIGINT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION matching_results_latest_on_insert() FROM PUBLIC;
-- Inserter must be able to fire the trigger (PG 13 and earlier).
GRANT EXECUTE ON FUNCTION matching_results_latest_on_insert() TO PUBLIC;

DROP TRIGGER IF EXISTS matching_results_latest_on_insert ON matching_results;
CREATE TRIGGER matching_results_latest_on_insert
    AFTER INSERT ON matching_results
    FOR EACH ROW
    EXECUTE FUNCTION matching_results_latest_on_insert();

-- Prod-scale backfill: one DISTINCT ON pass, then one aggregate. No loops.
INSERT INTO matching_results_latest (
    request_id, matched, match_count, matched_via, recorded_at
)
SELECT DISTINCT ON (request_id)
    request_id,
    matched,
    match_count,
    matched_via,
    recorded_at
  FROM matching_results
 ORDER BY request_id, recorded_at DESC, id DESC;

INSERT INTO matching_parameter_stats (
    intake_source,
    parameter,
    requestor_state,
    requests,
    exact_single,
    any_hit,
    multi_hit,
    zero_hit,
    updated_at
)
SELECT
    r.intake_source,
    l.matched_via,
    r.requestor_state,
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE l.match_count = 1)::bigint,
    COUNT(*) FILTER (WHERE l.match_count > 0)::bigint,
    COUNT(*) FILTER (WHERE l.match_count > 1)::bigint,
    COUNT(*) FILTER (WHERE l.match_count = 0)::bigint,
    NOW()
  FROM matching_results_latest l
  JOIN requests r ON r.id = l.request_id
 GROUP BY r.intake_source, l.matched_via, r.requestor_state;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON matching_results_latest FROM app_user;
        REVOKE UPDATE, DELETE ON matching_parameter_stats FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TRIGGER IF EXISTS matching_results_latest_on_insert ON matching_results;
DROP FUNCTION IF EXISTS matching_results_latest_on_insert();
DROP FUNCTION IF EXISTS matching_parameter_stats_apply(
    VARCHAR, VARCHAR, VARCHAR, INT, BIGINT
);
DROP TABLE IF EXISTS matching_parameter_stats;
DROP TABLE IF EXISTS matching_results_latest;
