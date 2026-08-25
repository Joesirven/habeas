-- migrate:up
-- UNIQUE (drop_record_id, list_type) for batch land ON CONFLICT DO NOTHING.
-- Fail closed: refuse the constraint if duplicate groups already exist.
-- Do not delete or collapse duplicates.

DO $$
DECLARE
    dup_groups BIGINT;
BEGIN
    SELECT COUNT(*) INTO dup_groups
    FROM (
        SELECT drop_record_id, list_type
          FROM drop_raw_requests
         GROUP BY drop_record_id, list_type
        HAVING COUNT(*) > 1
    ) dups;

    IF dup_groups > 0 THEN
        RAISE EXCEPTION
            'drop_raw_requests has % duplicate (drop_record_id, list_type) group(s); refusing unique constraint (fail closed, no deletes)',
            dup_groups;
    END IF;
END $$;

ALTER TABLE drop_raw_requests
    ADD CONSTRAINT drop_raw_requests_drop_record_id_list_type_unique
        UNIQUE (drop_record_id, list_type);

-- migrate:down
ALTER TABLE drop_raw_requests
    DROP CONSTRAINT IF EXISTS drop_raw_requests_drop_record_id_list_type_unique;
