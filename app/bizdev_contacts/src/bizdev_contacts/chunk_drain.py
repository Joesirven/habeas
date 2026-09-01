"""Contact Us matching chunk drain — Cloud Run Job loop for ``bizdev_contacts_attempts``.

Re-exports core chunk-drain helpers bound to this worker's config. Job entrypoint:
``python -m bizdev_contacts.chunk_drain``.

Never logs emails, hashes, or vendor ids.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from habeas_privacy_core.sheet_worker.chunk_drain import run_job_task

from bizdev_contacts.main import CONFIG

logger = logging.getLogger(__name__)


def main() -> None:
    """Cloud Run Job entrypoint: ``python -m bizdev_contacts.chunk_drain``."""
    import asyncpg

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required for bizdev_contacts drain Job tasks")

    async def _run() -> dict[str, Any]:
        conn = await asyncpg.connect(database_url)
        try:
            return await run_job_task(conn, CONFIG)
        finally:
            await conn.close()

    result = asyncio.run(_run())
    logger.info(
        "bizdev_contacts_drain_job_task_result",
        extra={"event": "bizdev_contacts_drain_job_task_result", **result},
    )


if __name__ == "__main__":
    main()
