-- migrate:up
-- Operator identity (IAP email) + request comments (replaces ops.comment audit-thread v0).

CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    email           VARCHAR(320) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_email_not_blank CHECK (char_length(trim(email)) > 0),
    CONSTRAINT users_email_unique UNIQUE (email)
);

CREATE TABLE request_comments (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL REFERENCES requests(id),
    author_user_id  BIGINT NOT NULL REFERENCES users(id),
    body            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT request_comments_body_not_empty CHECK (char_length(trim(body)) > 0)
);

CREATE INDEX ix_request_comments_request_created
    ON request_comments (request_id, created_at ASC);

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        REVOKE UPDATE, DELETE ON request_comments FROM app_user;
    END IF;
END $$;

-- migrate:down
DROP TABLE IF EXISTS request_comments;
DROP TABLE IF EXISTS users;
