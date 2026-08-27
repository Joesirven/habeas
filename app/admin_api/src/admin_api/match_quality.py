"""Match-quality rates by parameter from ``matching_parameter_stats``.

Counts and rates only — no ``consumer_id``, hashes, or emails.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from admin_api.drop_pipeline import SuperAdminPrincipal, _require_database
from habeas_privacy_core.db.pool import get_pool

try:
    from habeas_privacy_core.db.match_stats import fetch_drop_match_totals
except ImportError:  # I4 helpers not on this tree
    fetch_drop_match_totals = None

router = APIRouter(prefix="/ops/drop", tags=["drop-pipeline"])

ZERO_HIT_FLOOR_MIN_REQUESTS = 1000
BREACH_CODE_ZERO_HIT_FLOOR = "zero_hit_floor"
DROP_INTAKE_SOURCE = "drop"

# Rollup integers only. Never project identifiers or hashed identifiers.
_PARAMETER_STATS_SQL = """
SELECT parameter,
       SUM(requests)::bigint AS requests,
       SUM(exact_single)::bigint AS exact_single,
       SUM(any_hit)::bigint AS any_hit,
       SUM(multi_hit)::bigint AS multi_hit,
       SUM(zero_hit)::bigint AS zero_hit
  FROM matching_parameter_stats
 WHERE intake_source = $1
 GROUP BY parameter
 ORDER BY parameter
"""

_COUNT_KEYS = ("requests", "exact_single", "any_hit", "multi_hit", "zero_hit")


class ParameterQuality(BaseModel):
    parameter: str
    requests: int
    exact_single: int
    any_hit: int
    multi_hit: int
    zero_hit: int
    exact_rate: float
    any_hit_rate: float


class MatchQualityBreach(BaseModel):
    code: str
    parameter: str
    requests: int
    any_hit_rate: float


class MatchQualityResponse(BaseModel):
    by_parameter: list[ParameterQuality] = Field(default_factory=list)
    breaches: list[MatchQualityBreach] = Field(default_factory=list)


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return getattr(row, key, default)


def _as_int(row: Any, key: str) -> int:
    raw = _row_get(row, key, 0)
    if raw is None:
        return 0
    return int(raw)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


async def load_parameter_stat_rows(conn: Any) -> list[Any]:
    """Read rollup rows — I4 ``fetch_drop_match_totals`` when present."""
    if fetch_drop_match_totals is not None:
        rollup = await fetch_drop_match_totals(conn)
        return list(rollup.get("by_parameter") or [])
    return list(await conn.fetch(_PARAMETER_STATS_SQL, DROP_INTAKE_SOURCE))


def aggregate_match_quality(rows: list[Any]) -> MatchQualityResponse:
    """Sum count columns by ``parameter`` and flag zero-hit floors."""
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {key: 0 for key in _COUNT_KEYS}
    )
    for row in rows:
        intake_source = _row_get(row, "intake_source")
        if intake_source is not None and str(intake_source) != DROP_INTAKE_SOURCE:
            continue
        parameter = str(_row_get(row, "parameter") or "").strip()
        if not parameter:
            continue
        bucket = totals[parameter]
        for key in _COUNT_KEYS:
            bucket[key] += _as_int(row, key)

    by_parameter: list[ParameterQuality] = []
    breaches: list[MatchQualityBreach] = []
    for parameter in sorted(totals):
        counts = totals[parameter]
        requests = counts["requests"]
        exact_rate = _rate(counts["exact_single"], requests)
        any_hit_rate = _rate(counts["any_hit"], requests)
        by_parameter.append(
            ParameterQuality(
                parameter=parameter,
                requests=requests,
                exact_single=counts["exact_single"],
                any_hit=counts["any_hit"],
                multi_hit=counts["multi_hit"],
                zero_hit=counts["zero_hit"],
                exact_rate=exact_rate,
                any_hit_rate=any_hit_rate,
            )
        )
        if any_hit_rate == 0 and requests >= ZERO_HIT_FLOOR_MIN_REQUESTS:
            breaches.append(
                MatchQualityBreach(
                    code=BREACH_CODE_ZERO_HIT_FLOOR,
                    parameter=parameter,
                    requests=requests,
                    any_hit_rate=any_hit_rate,
                )
            )
    return MatchQualityResponse(by_parameter=by_parameter, breaches=breaches)


async def collect_match_quality(conn: Any) -> MatchQualityResponse:
    rows = await load_parameter_stat_rows(conn)
    return aggregate_match_quality(rows)


@router.get("/match-quality")
async def drop_match_quality(_principal: SuperAdminPrincipal) -> MatchQualityResponse:
    """Rates by matching parameter. Super_admin like other ``/ops/drop`` routes."""
    _require_database()
    pool = get_pool()
    async with pool.acquire() as conn:
        return await collect_match_quality(conn)
