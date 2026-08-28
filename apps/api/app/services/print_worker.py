"""Background print worker — processes queued print jobs inside the backend.

Starts automatically on FastAPI app boot. No separate print-agent needed.
"""
import asyncio
import base64
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.db.session import async_session_factory
from app.db.models import PrintJob
from app.services.printer import print_pdf

log = logging.getLogger("msb.print_worker")

POLL_INTERVAL = 5  # seconds between polls
MAX_ATTEMPTS = 3   # max retries per job


async def _process_job(job: PrintJob) -> bool:
    """Decode PDF, send to printer, update status.
    Returns True if job was processed (success or permanent failure).
    """
    try:
        payload = job.payload or {}
        b64 = payload.get("pdf_base64", "")
        printer_config = payload.get("printer", {})

        if not b64:
            await _update_job(job.id, status="failed", error="No PDF in payload")
            return True

        if not printer_config.get("name"):
            await _update_job(job.id, status="failed",
                              error="Принтер не выбран. Админ → Принтер → Найти принтеры → выбрать → Сохранить")
            return True

        pdf_bytes = base64.b64decode(b64)

        # Run blocking print in a thread
        loop = asyncio.get_running_loop()
        mode = await loop.run_in_executor(None, print_pdf, pdf_bytes, printer_config)

        await _update_job(job.id, status="done")
        log.info(f"Job {str(job.id)[:8]} printed via {mode}")
        return True

    except Exception as e:
        attempts = (job.attempts or 0) + 1
        error_msg = str(e)[:500]
        if attempts >= MAX_ATTEMPTS:
            await _update_job(job.id, status="failed", error=f"Failed after {attempts} attempts: {error_msg}")
            log.error(f"Job {str(job.id)[:8]} FAILED after {attempts} attempts: {e}")
        else:
            # Leave as "queued" for retry, but increment attempts
            await _update_job(job.id, status="queued", error=error_msg)
            log.warning(f"Job {str(job.id)[:8]} attempt {attempts}/{MAX_ATTEMPTS}: {e}")
        return attempts >= MAX_ATTEMPTS


async def _update_job(job_id, *, status: str, error: str | None = None):
    async with async_session_factory() as db:
        values = {"status": status, "attempts": PrintJob.attempts + 1}
        if error is not None:
            values["error"] = error
        await db.execute(
            update(PrintJob).where(PrintJob.id == job_id).values(**values)
        )
        await db.commit()


async def print_worker_loop():
    """Main loop: poll for queued jobs and process them."""
    log.info("Print worker started (polling every %ds, max %d retries)", POLL_INTERVAL, MAX_ATTEMPTS)
    while True:
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(PrintJob)
                    .where(PrintJob.status == "queued")
                    .where((PrintJob.attempts or 0) < MAX_ATTEMPTS)
                    .order_by(PrintJob.created_at.asc())
                    .limit(3)
                )
                jobs = list(result.scalars().all())

            for job in jobs:
                # Mark as processing
                await _update_job(job.id, status="processing")
                await _process_job(job)

        except Exception as e:
            log.error(f"Print worker error: {e}")

        await asyncio.sleep(POLL_INTERVAL)
