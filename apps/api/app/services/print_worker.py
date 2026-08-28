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

POLL_INTERVAL = 3  # seconds between polls


async def _process_job(job: PrintJob) -> None:
    """Decode PDF, send to printer, update status."""
    try:
        payload = job.payload or {}
        b64 = payload.get("pdf_base64", "")
        printer_config = payload.get("printer", {})

        if not b64:
            async with async_session_factory() as db:
                await db.execute(
                    update(PrintJob).where(PrintJob.id == job.id).values(
                        status="failed", error="No PDF in payload"
                    )
                )
                await db.commit()
            return

        pdf_bytes = base64.b64decode(b64)

        # Run blocking print in a thread
        loop = asyncio.get_running_loop()
        mode = await loop.run_in_executor(None, print_pdf, pdf_bytes, printer_config)

        async with async_session_factory() as db:
            await db.execute(
                update(PrintJob).where(PrintJob.id == job.id).values(
                    status="done", attempts=PrintJob.attempts + 1
                )
            )
            await db.commit()
        log.info(f"Job {str(job.id)[:8]} printed via {mode}")

    except Exception as e:
        log.error(f"Job {str(job.id)[:8]} failed: {e}")
        async with async_session_factory() as db:
            await db.execute(
                update(PrintJob).where(PrintJob.id == job.id).values(
                    status="failed",
                    error=str(e)[:500],
                    attempts=PrintJob.attempts + 1,
                )
            )
            await db.commit()


async def print_worker_loop():
    """Main loop: poll for queued jobs and process them."""
    log.info("Print worker started (polling every %ds)", POLL_INTERVAL)
    while True:
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(PrintJob)
                    .where(PrintJob.status == "queued")
                    .order_by(PrintJob.created_at.asc())
                    .limit(5)
                )
                jobs = result.scalars().all()

            for job in jobs:
                # Mark as processing
                async with async_session_factory() as db:
                    await db.execute(
                        update(PrintJob).where(PrintJob.id == job.id).values(
                            status="processing"
                        )
                    )
                    await db.commit()

                await _process_job(job)

        except Exception as e:
            log.error(f"Print worker error: {e}")

        await asyncio.sleep(POLL_INTERVAL)
