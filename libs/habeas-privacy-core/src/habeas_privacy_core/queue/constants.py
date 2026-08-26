"""Shared constants for queue-as-table workers."""

MATCHING_ATTEMPTS_TABLE = "matching_attempts"
MATCHING_STEP = "matching"

HASH_INDEX_REFRESH_ATTEMPTS_TABLE = "hash_index_refresh_attempts"
HASH_INDEX_REFRESH_RUNS_TABLE = "hash_index_refresh_runs"
HASH_INDEX_REFRESH_STEP = "refresh"

DATA_FULFILLMENT_ATTEMPTS_TABLE = "data_fulfillment_attempts"
DATA_FULFILLMENT_STEP_SUPPRESSION = "suppression"
DATA_FULFILLMENT_STEP_REPRODUCTION = "reproduction"

CASSANDRA_ATTEMPTS_TABLE = "cassandra_attempts"

VERTICAL_HASH_REFRESH_ATTEMPTS_TABLE = "vertical_hash_refresh_attempts"
VERTICAL_HASH_REFRESH_RUNS_TABLE = "vertical_hash_refresh_runs"
VERTICAL_HASH_REFRESH_STEP = "refresh"
VERTICAL_HASH_REFRESH_SYSTEMS = frozenset(
    {
        "axios_headquarters",
        "paylocity",
        "lever",
        "auth0",
        "google_sheets",
        "bizdev_contacts",
        "hr_alumni",
    }
)

MAILCHIMP_ATTEMPTS_TABLE = "mailchimp_attempts"
AXIOS_HEADQUARTERS_ATTEMPTS_TABLE = "axios_headquarters_attempts"
PAYLOCITY_ATTEMPTS_TABLE = "paylocity_attempts"
LEVER_ATTEMPTS_TABLE = "lever_attempts"
AUTH0_ATTEMPTS_TABLE = "auth0_attempts"
GOOGLE_SHEETS_ATTEMPTS_TABLE = "google_sheets_attempts"
STEP_MATCHING = "matching"
STEP_SUPPRESSION = "suppression"
