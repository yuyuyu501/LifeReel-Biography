"""Observed progress and tenant-local, comparable duration estimates."""

from datetime import UTC, datetime
from math import ceil

from sqlalchemy import select

from lifereel_api.core.config import get_settings
from lifereel_api.modules.interview.models import InterviewTurnWorkflow


def pipeline_signature():
    s = get_settings()
    return [s.llm_provider, *[s.model_for(role) for role in ("interview", "memory", "script")]]


def record_stage(db, workflow, stage, *, commit=True):
    brief = workflow.script_brief or {}
    if brief.get("stage") == stage:
        return
    now = datetime.now(UTC).isoformat()
    workflow.script_brief = {
        **brief,
        "stage": stage,
        "stage_started_at": now,
        "stage_times": {**brief.get("stage_times", {}), stage: now},
    }
    if commit:
        db.commit()


def progress_summary(db, tenant_id, workflow):
    if workflow is None:
        return {}

    def utc(value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    end = workflow.completed_at or datetime.now(UTC)
    samples = db.scalars(
        select(InterviewTurnWorkflow)
        .where(
            InterviewTurnWorkflow.tenant_id == tenant_id,
            InterviewTurnWorkflow.status == "completed",
        )
        .order_by(InterviewTurnWorkflow.completed_at.desc())
        .limit(60)
    )
    keys = ("requested_action", "pipeline_signature", "workload")
    durations = sorted(
        (utc(item.completed_at) - utc(item.created_at)).total_seconds()
        for item in samples
        if item.completed_at
        and item.script_brief.get("stage_times")
        and all(item.script_brief.get(k) == workflow.script_brief.get(k) for k in keys)
        and utc(item.completed_at) > utc(item.created_at)
    )
    result = {
        "stage": workflow.status
        if workflow.status == "failed"
        else workflow.script_brief.get("stage", workflow.status),
        "elapsed_seconds": max(0, int((utc(end) - utc(workflow.created_at)).total_seconds())),
        "sample_count": len(durations),
        "estimated_seconds": None,
    }
    if len(durations) >= 5:
        result["estimated_seconds"] = [
            ceil(durations[len(durations) // 2]),
            ceil(durations[min(len(durations) - 1, int(len(durations) * 0.9))]),
        ]
    return result
