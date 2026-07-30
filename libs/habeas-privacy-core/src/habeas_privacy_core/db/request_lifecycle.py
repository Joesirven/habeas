"""Lifecycle facts off the immutable requests spine: closures and due overrides.

Call sites should prefer these fragments over inventing equivalent SQL.
Open filters may inline the same ``NOT EXISTS (request_closures …)`` predicate;
prefer ``REQUEST_IS_OPEN_SQL`` when building new queries.
"""

from __future__ import annotations

# Open request predicate — alias the requests row as ``r``.
REQUEST_IS_OPEN_SQL = """
NOT EXISTS (
    SELECT 1 FROM request_closures rc WHERE rc.request_id = r.id
)
""".strip()

# Effective due timestamp — alias the requests row as ``r``.
# COALESCE(latest admin override, received_at + lifecycle_days).
EFFECTIVE_DUE_AT_SQL = """
COALESCE(
    (
        SELECT o.due_at
          FROM request_due_overrides o
         WHERE o.request_id = r.id
         ORDER BY o.overridden_at DESC
         LIMIT 1
    ),
    r.received_at + make_interval(
        days => COALESCE(
            (SELECT lifecycle_days FROM legal_sla_settings WHERE id = 1),
            6
        )
    )
)
""".strip()
