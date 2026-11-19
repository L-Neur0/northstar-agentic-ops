"""Optional OpenTelemetry export to App Insights (spec 10 §3.7).

Why: on Azure, request traces and logs should reach App Insights without code in every route;
locally and in tests nothing should be exported or slowed down.
What: `configure_telemetry(settings)` sets up Azure Monitor OpenTelemetry once, and only when the
connection string is set; it excludes the health probe. Otherwise it does nothing.
Must not: run at import time or fail the app when telemetry cannot start.
"""

from __future__ import annotations

import logging

from app.core.settings import Settings

_configured = False


def configure_telemetry(settings: Settings) -> bool:
    """Configure export if a connection string is set. Returns True when telemetry is on."""
    global _configured
    if _configured or not settings.applicationinsights_connection_string:
        return _configured
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
            logger_name="app",
            instrumentation_options={"fastapi": {"excluded_urls": "api/health"}},
        )
        _configured = True
    except Exception:  # telemetry must never stop the app
        logging.getLogger("app.telemetry").warning("telemetry not configured", exc_info=True)
    return _configured
