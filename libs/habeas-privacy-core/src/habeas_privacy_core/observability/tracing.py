"""OpenTelemetry bootstrap for Cloud Trace."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def setup_tracing(*, service_name: str, project_id: str | None, enabled: bool = True) -> None:
    """Configure OpenTelemetry export to Cloud Trace when a GCP project is set."""
    if not enabled or not project_id:
        logger.info(
            "cloud_trace_disabled",
            extra={"service": service_name, "reason": "missing_project_or_disabled"},
        )
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "cloud_trace_unavailable",
            extra={"service": service_name, "reason": "opentelemetry_packages_missing"},
        )
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=project_id)))
    trace.set_tracer_provider(provider)
    logger.info("cloud_trace_enabled", extra={"service": service_name, "project_id": project_id})
