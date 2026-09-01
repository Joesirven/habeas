"""HR Alumni Cloud Run worker — matching + hash refresh + chunk drain."""

from __future__ import annotations

from dataclasses import replace

from habeas_privacy_core.queue.constants import HR_ALUMNI_ATTEMPTS_TABLE
from habeas_privacy_core.sheet_worker import HR_ALUMNI_CONFIG, SheetWorkerSettings, create_sheet_worker_app

_CONFIG = replace(HR_ALUMNI_CONFIG, attempts_table=HR_ALUMNI_ATTEMPTS_TABLE)
settings = SheetWorkerSettings(
    service_name=_CONFIG.service_name,
    worker_id="hr-alumni-dev",
)
app = create_sheet_worker_app(_CONFIG, settings=settings)
