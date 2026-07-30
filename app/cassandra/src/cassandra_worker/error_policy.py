"""Cassandra-specific vendor error classification."""

from __future__ import annotations

from typing import Any

from habeas_privacy_core.workflow.error_policy import ErrorDisposition


class CassandraErrorClassifier:
    """Map Cassandra / CQL error codes to shared dispositions."""

    terminal_success = frozenset({"already_suppressed", "dwid_not_found"})
    retryable = frozenset({"cassandra_timeout", "unavailable", "write_timeout"})
    terminal_error = frozenset({"auth_failed", "invalid_dwid", "schema_mismatch"})

    def classify(
        self,
        error_code: str,
        error_payload: dict[str, Any] | None = None,
    ) -> ErrorDisposition:
        del error_payload
        if error_code in self.terminal_success:
            return ErrorDisposition.TERMINAL_SUCCESS
        if error_code in self.retryable:
            return ErrorDisposition.RETRYABLE
        if error_code in self.terminal_error:
            return ErrorDisposition.TERMINAL_ERROR
        return ErrorDisposition.ABANDON
