-- migrate:up
-- KTD9: allow hard-delete of request_documents for uploader/admin via admin_api.

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        GRANT DELETE ON request_documents TO app_user;
    END IF;
END $$;

-- migrate:down
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE DELETE ON request_documents FROM app_user;
    END IF;
END $$;
