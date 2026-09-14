"""Per-turn retry policy and durable successful memory-stage checkpoints."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.billing.models import UsageEvent
from lifereel_api.modules.billing.usage import current_context
from lifereel_api.modules.interview.models import InterviewTurnWorkflow

VERSION = 1
MAX_RUNS = 3
MAX_RETAIL_NANO = 1_200_000_000  # Stop retries after CNY 1.20 of this policy's AI use.
COOLDOWN_SECONDS = 30


def policy(workflow):
    state = (workflow.script_brief or {}).get("memory_recovery", {})
    return state if state.get("version") == VERSION else {}


def allowed(workflow):
    state = policy(workflow)
    return state.get("runs", 0) < MAX_RUNS and not state.get("budget_exhausted", False)


def retry_after(workflow):
    when = policy(workflow).get("failed_at")
    if not when:
        return 0
    elapsed = (datetime.now(UTC) - datetime.fromisoformat(when)).total_seconds()
    return max(0, int(COOLDOWN_SECONDS - elapsed + 0.999))


def begin(db, workflow):
    if not allowed(workflow):
        raise ApiError(409, ErrorCode.MEMORY_RETRY_LIMIT_REACHED)
    state = policy(workflow)
    state = {
        **state,
        "version": VERSION,
        "runs": state.get("runs", 0) + 1,
        "started_at": state.get("started_at", datetime.now(UTC).isoformat()),
    }
    workflow.script_brief = {**workflow.script_brief, "memory_recovery": state}
    db.commit()


def failure(db, workflow, exc):
    state = policy(workflow)
    if not state:
        return
    events = db.scalars(
        select(UsageEvent).where(
            UsageEvent.tenant_id == workflow.tenant_id,
            UsageEvent.reference == str(workflow.id),
            UsageEvent.created_at >= datetime.fromisoformat(state["started_at"]),
        )
    )
    spent = sum(e.metering.get("retail_nano", 0) for e in events)
    workflow.script_brief = {
        **workflow.script_brief,
        "memory_recovery": {
            **state,
            "failed_at": datetime.now(UTC).isoformat(),
            "spent_nano": spent,
            "budget_exhausted": spent >= MAX_RETAIL_NANO,
            "diagnostic": getattr(exc, "diagnostic", {"reason": exc.code.value}),
        },
    }


def check_call_budget():
    from lifereel_api.core.database import SessionLocal

    context = current_context()
    if not context:
        return
    with SessionLocal() as db:
        workflow = current_workflow(db, context[0])
        if workflow is None or not policy(workflow):
            return
        state = policy(workflow)
        events = db.scalars(select(UsageEvent).where(
            UsageEvent.tenant_id == workflow.tenant_id,
            UsageEvent.reference == str(workflow.id),
            UsageEvent.created_at >= datetime.fromisoformat(state["started_at"]),
        ))
        if sum(e.metering.get("retail_nano", 0) for e in events) >= MAX_RETAIL_NANO:
            raise ApiError(409, ErrorCode.MEMORY_RETRY_LIMIT_REACHED)


def current_workflow(db, tenant_id):
    context = current_context()
    if not context or context[0] != tenant_id or not context[2]:
        return None
    try:
        identity = UUID(context[2])
    except ValueError:
        return None
    return db.scalar(
        select(InterviewTurnWorkflow).where(
            InterviewTurnWorkflow.id == identity,
            InterviewTurnWorkflow.tenant_id == tenant_id,
        )
    )


def fingerprint(claims):
    from lifereel_api.core.config import get_settings

    settings = get_settings()
    source = [(str(c.id), c.claim_text, c.source_quote, c.review_status) for c in claims]
    return hashlib.sha256(
        json.dumps(
            [
                VERSION,
                settings.model_for("memory"),
                settings.openai_compatible_base_url,
                source,
            ],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def completed(workflow, subject_id, stage, digest):
    if workflow is None:
        return False
    key = f"{subject_id}:{stage}"
    return workflow.script_brief.get("memory_checkpoints", {}).get(key) == digest


def save(db, workflow, subject_id, stage, digest):
    if workflow is None:
        return
    workflow.script_brief = {
        **workflow.script_brief,
        "memory_checkpoints": {
            **workflow.script_brief.get("memory_checkpoints", {}),
            f"{subject_id}:{stage}": digest,
        },
    }
    db.commit()
