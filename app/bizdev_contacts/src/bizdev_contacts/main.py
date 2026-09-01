"""BizDev Contact Us Cloud Run worker — matching + hash refresh + chunk drain."""

from __future__ import annotations

from dataclasses import replace

from habeas_privacy_core.queue.constants import BIZDEV_CONTACTS_ATTEMPTS_TABLE
from habeas_privacy_core.sheet_worker import create_sheet_worker_app
from habeas_privacy_core.sheet_worker.app import SheetWorkerSettings
from habeas_privacy_core.sheet_worker.config import BIZDEV_CONTACTS_CONFIG

CONFIG = replace(BIZDEV_CONTACTS_CONFIG, attempts_table=BIZDEV_CONTACTS_ATTEMPTS_TABLE)
settings = SheetWorkerSettings(
    service_name=CONFIG.service_name,
    worker_id="bizdev-contacts-dev",
)
app = create_sheet_worker_app(CONFIG, settings=settings)
