"""Estimate from comparable, completed tenant runs with explicit completion timestamps."""

from datetime import UTC, datetime
from math import ceil

from sqlalchemy import select

from lifereel_api.modules.production.models import ProductionRun


def comparable(manifest):
    config = manifest.get("generation_config") or {}
    return [
        config,
        manifest.get("target_duration_seconds"),
        len(manifest.get("segments") or []),
        bool(manifest.get("regeneration")),
        (manifest.get("billing_quote") or {}).get("target_seconds"),
        len((manifest.get("reference_package") or {}).get("image_references") or []),
    ]


def summary(db, run):
    manifest = run.output_manifest or {}

    def utc(value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    end = (
        datetime.fromisoformat(manifest["completed_at"])
        if manifest.get("completed_at")
        else datetime.now(UTC)
    )
    samples = db.scalars(
        select(ProductionRun)
        .where(
            ProductionRun.tenant_id == run.tenant_id,
            ProductionRun.provider == run.provider,
            ProductionRun.status == "completed",
        )
        .order_by(ProductionRun.created_at.desc())
        .limit(60)
    )
    durations = []
    for sample in samples:
        data = sample.output_manifest or {}
        if data.get("completed_at") and comparable(data) == comparable(manifest):
            seconds = (
                utc(datetime.fromisoformat(data["completed_at"])) - utc(sample.created_at)
            ).total_seconds()
            if seconds > 0:
                durations.append(seconds)
    durations.sort()
    return {
        "elapsed_seconds": max(0, int((utc(end) - utc(run.created_at)).total_seconds())),
        "sample_count": len(durations),
        "estimated_seconds": [
            ceil(durations[len(durations) // 2]),
            ceil(durations[min(len(durations) - 1, int(len(durations) * 0.9))]),
        ]
        if len(durations) >= 5
        else None,
    }
