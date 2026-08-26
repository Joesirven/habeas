import json
import logging
from unittest.mock import AsyncMock

from habeas_privacy_core.db.pool import reset_statement_timeout, set_local_statement_timeout
from habeas_privacy_core.health import health_payload, ready_payload
from habeas_privacy_core.observability.logging import CloudLoggingJsonFormatter, configure_logging


def test_health_payload():
    assert health_payload() == {"status": "ok"}
    assert health_payload(service="reaper") == {"status": "ok", "service": "reaper"}


async def test_ready_payload_ok():
    async def ok_check() -> bool:
        return True

    payload = await ready_payload(service="reaper", db_check=ok_check)
    assert payload["status"] == "ok"
    assert payload["checks"]["database"] == "ok"


async def test_ready_payload_failed():
    async def fail_check() -> bool:
        raise RuntimeError("db down")

    payload = await ready_payload(service="reaper", db_check=fail_check)
    assert payload["status"] == "unavailable"
    assert payload["checks"]["database"] == "failed"


def test_json_logging_formatter():
    configure_logging(service_name="test-service", level="INFO")
    formatter = CloudLoggingJsonFormatter()
    record = logging.LogRecord(
        name="test-service",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="reaper_started",
        args=(),
        exc_info=None,
    )
    record.service = "reaper"
    record.event = "service_start"
    payload = json.loads(formatter.format(record))
    assert payload["severity"] == "INFO"
    assert payload["message"] == "reaper_started"
    assert payload["service"] == "reaper"
    assert payload["event"] == "service_start"


async def test_set_local_statement_timeout_defaults_to_4000():
    conn = AsyncMock()
    await set_local_statement_timeout(conn)
    conn.execute.assert_awaited_once_with(
        "SELECT set_config('statement_timeout', $1, true)",
        "4000",
    )


async def test_set_local_statement_timeout_passes_custom_ms_as_string():
    conn = AsyncMock()
    await set_local_statement_timeout(conn, 2500)
    conn.execute.assert_awaited_once_with(
        "SELECT set_config('statement_timeout', $1, true)",
        "2500",
    )


async def test_reset_statement_timeout_sets_zero_session_wide():
    conn = AsyncMock()
    await reset_statement_timeout(conn)
    conn.execute.assert_awaited_once_with(
        "SELECT set_config('statement_timeout', '0', false)",
    )


async def test_set_then_reset_statement_timeout():
    conn = AsyncMock()
    await set_local_statement_timeout(conn)
    await reset_statement_timeout(conn)
    assert conn.execute.await_count == 2
    assert conn.execute.await_args_list[0].args == (
        "SELECT set_config('statement_timeout', $1, true)",
        "4000",
    )
    assert conn.execute.await_args_list[1].args == (
        "SELECT set_config('statement_timeout', '0', false)",
    )
