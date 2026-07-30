"""Live / payload builder for Cassandra ``restricted_person_id`` suppression.

Vendor vocabulary stays in this adapter only (ACL). Never log raw DWIDs or PII.
"""

from __future__ import annotations

import logging
import os
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Settled with MDR suppression owners (2026-07-30).
DEFAULT_SOURCE_OF_RESTRICTION = "Habeas"
DEFAULT_TYPE_OF_RESTRICTION = "person"
TABLE_NAME = "restricted_person_id"

# Env defaults — override per Cloud Run service.
DEFAULT_HOST = "broker-db.example.internal"
DEFAULT_USER = "dprwrk"


@dataclass(frozen=True)
class CassandraEnvConfig:
    """Connection + target table for one DPAP environment."""

    host: str
    port: int
    keyspace: str
    username: str
    password: str
    ssl_ca_path: str
    source_of_restriction: str = DEFAULT_SOURCE_OF_RESTRICTION
    type_of_restriction: str = DEFAULT_TYPE_OF_RESTRICTION

    @property
    def qualified_table(self) -> str:
        return f"{self.keyspace}.{TABLE_NAME}"

    @property
    def insert_cql(self) -> str:
        return f"""
INSERT INTO {self.qualified_table} (
    dwid,
    date_of_restriction,
    insert_timestamp,
    source_of_restriction,
    type_of_restriction
) VALUES (?, ?, ?, ?, ?)
""".strip()


def config_from_env() -> CassandraEnvConfig:
    """Build config from process environment / Secret Manager mounts.

    Expected secrets (mounted as files or env):
      CASSANDRA_PASSWORD or CASSANDRA_PASSWORD_FILE
      CASSANDRA_SSL_CA (path to PEM)
    Env-specific:
      CASSANDRA_PORT — 9041 (dev) or 9042 (prod)
      CASSANDRA_KEYSPACE — person_db_dev (dev) or person_db (prod)
    """
    password_file = os.environ.get("CASSANDRA_PASSWORD_FILE")
    if password_file:
        password = Path(password_file).read_text(encoding="utf-8").strip()
    else:
        password = (os.environ.get("CASSANDRA_PASSWORD") or "").strip()
    if not password:
        raise RuntimeError("CASSANDRA_PASSWORD or CASSANDRA_PASSWORD_FILE is required")

    ssl_ca = (os.environ.get("CASSANDRA_SSL_CA") or "").strip()
    if not ssl_ca or not Path(ssl_ca).is_file():
        raise RuntimeError("CASSANDRA_SSL_CA must point to the INF CA PEM file")

    port = int(os.environ.get("CASSANDRA_PORT", "9041"))
    keyspace = os.environ.get("CASSANDRA_KEYSPACE", "person_db_dev").strip()
    return CassandraEnvConfig(
        host=os.environ.get("CASSANDRA_HOST", DEFAULT_HOST).strip(),
        port=port,
        keyspace=keyspace,
        username=os.environ.get("CASSANDRA_USER", DEFAULT_USER).strip(),
        password=password,
        ssl_ca_path=ssl_ca,
        source_of_restriction=os.environ.get(
            "CASSANDRA_SOURCE_OF_RESTRICTION", DEFAULT_SOURCE_OF_RESTRICTION
        ).strip(),
        type_of_restriction=os.environ.get(
            "CASSANDRA_TYPE_OF_RESTRICTION", DEFAULT_TYPE_OF_RESTRICTION
        ).strip(),
    )


def parse_dwid(raw: str | int) -> int:
    """MDR ``dwid`` is Cassandra bigint."""
    text = str(raw).strip()
    if not text:
        raise ValueError("empty_dwid")
    return int(text)


def build_request_payload(
    dwid: int,
    *,
    keyspace: str,
    source: str = DEFAULT_SOURCE_OF_RESTRICTION,
    restriction_type: str = DEFAULT_TYPE_OF_RESTRICTION,
    date_of_restriction: str | None = None,
    insert_timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Queue-safe audit payload — no raw DWID (R25)."""
    ts = insert_timestamp or datetime.now(UTC)
    day = date_of_restriction or ts.date().isoformat()
    return {
        "keyspace": keyspace,
        "table": TABLE_NAME,
        "column_set": [
            "dwid",
            "date_of_restriction",
            "insert_timestamp",
            "source_of_restriction",
            "type_of_restriction",
        ],
        "source_of_restriction": source,
        "type_of_restriction": restriction_type,
        "date_of_restriction": day,
        "insert_timestamp": ts.isoformat(),
        "dwid_fingerprint": f"bigint:len={len(str(dwid))}",
    }


def suppress_restricted_person_id_live(
    dwid_raw: str | int,
    *,
    config: CassandraEnvConfig | None = None,
) -> dict[str, Any]:
    """Idempotent INSERT into env keyspace ``restricted_person_id`` (minimal columns)."""
    # Import driver here so package name cassandra_worker does not shadow it at module load
    # for stub-only tests.
    from cassandra.auth import PlainTextAuthProvider
    from cassandra.cluster import Cluster
    from cassandra.policies import WhiteListRoundRobinPolicy

    cfg = config or config_from_env()
    dwid = parse_dwid(dwid_raw)
    now = datetime.now(UTC)
    day = now.date().isoformat()
    payload = build_request_payload(
        dwid,
        keyspace=cfg.keyspace,
        source=cfg.source_of_restriction,
        restriction_type=cfg.type_of_restriction,
        date_of_restriction=day,
        insert_timestamp=now,
    )

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    ssl_context.check_hostname = True
    ssl_context.load_verify_locations(cfg.ssl_ca_path)

    auth = PlainTextAuthProvider(username=cfg.username, password=cfg.password)
    cluster = Cluster(
        contact_points=[cfg.host],
        port=cfg.port,
        auth_provider=auth,
        ssl_context=ssl_context,
        ssl_options={"server_hostname": cfg.host},
        load_balancing_policy=WhiteListRoundRobinPolicy([cfg.host]),
        protocol_version=4,
    )
    try:
        session = cluster.connect()
        prepared = session.prepare(cfg.insert_cql)
        session.execute(
            prepared,
            (
                dwid,
                day,
                now,
                cfg.source_of_restriction,
                cfg.type_of_restriction,
            ),
        )
    finally:
        cluster.shutdown()

    logger.info(
        "cassandra_restricted_person_id_insert",
        extra={
            "event": "cassandra_restricted_person_id_insert",
            "keyspace": cfg.keyspace,
            "port": cfg.port,
            "source_of_restriction": cfg.source_of_restriction,
            "type_of_restriction": cfg.type_of_restriction,
            # no dwid
        },
    )
    return {
        "adapter": "restricted_person_id",
        "table": TABLE_NAME,
        "keyspace": cfg.keyspace,
        "method": "restricted_person_id",
        "inserted": True,
        "request_payload": payload,
    }
