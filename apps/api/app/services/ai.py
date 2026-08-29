"""AI provider abstraction (OpenAI-compatible API).

The rest of the app talks to `predict_eta()` / `weekly_summary()` — never to a
specific vendor. When no API key is configured (MVP), we fall back to a
statistics-based estimator and clearly flag the source + confidence. Every run
is logged to `ai_runs` for audit.
"""
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import utcnow
from app.db.models import AIRun, Repair


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _log_run(
    db: AsyncSession, kind: str, input_: dict, output: dict, model: str, latency_ms: int
) -> None:
    db.add(
        AIRun(
            kind=kind,
            input=input_,
            output=output,
            model=model,
            latency_ms=latency_ms,
        )
    )
    await db.commit()


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


async def _stats_eta(db: AsyncSession, device_type: str, brand: str | None) -> dict | None:
    """Estimate ETA from historical ready repairs of the same type/brand."""
    q = select(Repair).where(
        Repair.device_type == device_type, Repair.ready_at.isnot(None)
    )
    if brand:
        q = q.where(Repair.brand == brand)
    rows = (await db.execute(q)).scalars().all()
    if len(rows) < 3:
        return None
    days = [
        (r.ready_at - r.accepted_at).total_seconds() / 86400.0 for r in rows
    ]
    med = _median(days)
    return {"eta_days": int(round(med or 0)), "n": len(rows), "confidence": 0.6}


async def predict_eta(
    db: AsyncSession,
    device_type: str,
    brand: str | None = None,
    fault: str | None = None,
    city_id: str | None = None,
) -> dict:
    start = time.monotonic()
    input_ = {
        "device_type": device_type,
        "brand": brand,
        "fault": fault,
        "city_id": city_id,
    }

    # If a real AI provider is configured, use it.
    if settings.AI_API_KEY and settings.AI_BASE_URL:
        result = await _provider_eta(input_)
        await _log_run(
            db, "predict_eta", input_, result, settings.AI_MODEL or "openai_compat",
            int((time.monotonic() - start) * 1000),
        )
        return result

    # Fallback: honest statistics-based estimate (anti-hallucination).
    est = await _stats_eta(db, device_type, brand)
    if est is None:
        result = {
            "eta_days": None,
            "source": "stats",
            "confidence": None,
            "message": "мало данных",
            "n": 0,
        }
    else:
        result = {
            "eta_days": est["eta_days"],
            "source": "stats",
            "confidence": est["confidence"],
            "message": None,
            "n": est["n"],
        }
    await _log_run(
        db, "predict_eta", input_, result, "stats-fallback",
        int((time.monotonic() - start) * 1000),
    )
    return result


async def _provider_eta(input_: dict) -> dict:
    """Call OpenAI-compatible chat completion (structured JSON out)."""
    import json

    import httpx

    prompt = (
        "Ты — система оценки сроков ремонта бытовой техники. "
        "Дай прогноз срока ремонта в днях в формате JSON: "
        '{"eta_days": <int>, "confidence": <0..1>, "reason": "<кратко>"}. '
        f"Данные: {json.dumps(input_, ensure_ascii=False)}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{settings.AI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {settings.AI_API_KEY}"},
            json={
                "model": settings.AI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
        )
        r.raise_for_status()
        data = r.json()
    content = data["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"eta_days": None, "confidence": None, "reason": content}
    return {
        "eta_days": parsed.get("eta_days"),
        "confidence": parsed.get("confidence"),
        "reason": parsed.get("reason"),
        "source": "ai",
        "n": None,
    }


async def weekly_summary(db: AsyncSession) -> dict:
    """Week summary: volumes + master breakdown + anomalies."""
    start = time.monotonic()
    from sqlalchemy import func

    week_ago = utcnow() - timedelta(days=7)

    accepted_week = (
        await db.execute(
            select(func.count(Repair.id)).where(Repair.accepted_at >= week_ago)
        )
    ).scalar_one()
    ready_week = (
        await db.execute(
            select(func.count(Repair.id)).where(Repair.ready_at >= week_ago)
        )
    ).scalar_one()

    masters = {}
    row = await db.execute(
        select(Repair.master_id, func.count(Repair.id))
        .where(Repair.master_id.isnot(None), Repair.accepted_at >= week_ago)
        .group_by(Repair.master_id)
    )
    from app.db.models import User

    for mid, cnt in row.all():
        u = await db.get(User, mid)
        masters[u.name if u else str(mid)] = cnt

    summary = {
        "accepted_week": accepted_week,
        "ready_week": ready_week,
        "masters_week": masters,
        "note": None,
    }

    # If a real AI provider is configured, enrich with a natural-language take.
    if settings.AI_API_KEY and settings.AI_BASE_URL:
        try:
            import json

            import httpx

            prompt = (
                "Краткий (2–3 предложения) аналитический разбор недели сервисного центра "
                "на русском языке по этим данным: "
                + json.dumps(summary, ensure_ascii=False)
            )
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{settings.AI_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.AI_API_KEY}"},
                    json={
                        "model": settings.AI_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                    },
                )
                r.raise_for_status()
                data = r.json()
            summary["note"] = data["choices"][0]["message"]["content"]
            await _log_run(
                db, "weekly_summary", summary, summary, settings.AI_MODEL or "openai_compat",
                int((time.monotonic() - start) * 1000),
            )
        except Exception:
            summary["note"] = None

    return summary
