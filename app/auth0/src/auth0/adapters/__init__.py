"""Auth0 vendor adapters (Management API)."""

from auth0.adapters.management import (
    ManagementApiError,
    ManagementCredentials,
    ManagementExtractAdapter,
)
from auth0.adapters.stub import (
    MatchAdapter,
    MatchResult,
    StubMatchAdapter,
    StubSuppressAdapter,
    SuppressAdapter,
    SuppressResult,
)

__all__ = [
    "ManagementApiError",
    "ManagementCredentials",
    "ManagementExtractAdapter",
    "MatchAdapter",
    "MatchResult",
    "StubMatchAdapter",
    "StubSuppressAdapter",
    "SuppressAdapter",
    "SuppressResult",
]
