"""Delete one person's records, respecting database ownership and FK actions.

Stored objects and financial/provider audit records are retained. Object access
still requires an asset record; this operation is not a storage erasure API.
"""

from uuid import UUID

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from lifereel_api.core.database import Base
from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.governance.service import audit
from lifereel_api.modules.identity.models import Person


def _busy() -> None:
    raise ApiError(409, ErrorCode.PERSON_DELETE_BUSY)


def _keys(table, rows):
    return or_(
        *(and_(*(column == row[column.name] for column in table.primary_key)) for row in rows)
    )


def _references(value, identifiers: set[str]) -> bool:
    if isinstance(value, dict):
        return any(_references(item, identifiers) for item in value.values())
    if isinstance(value, list):
        return any(_references(item, identifiers) for item in value)
    return isinstance(value, str) and value in identifiers


def delete_person(db: Session, tenant_id: UUID, person_id: UUID) -> None:
    tables = list(Base.metadata.sorted_tables)
    person = db.scalar(
        select(Person)
        .where(Person.id == person_id, Person.tenant_id == tenant_id)
        .with_for_update()
    )
    if person is None:
        raise ApiError(404, ErrorCode.PERSON_NOT_FOUND)
    selected = {
        Person.__table__: [
            dict(
                db.execute(select(Person.__table__).where(Person.id == person_id)).mappings().one()
            )
        ]
    }
    # Follow CASCADE only. SET NULL references are detached below, never treated
    # as ownership (e.g. another person's derived photo).
    for table in tables:
        if table is Person.__table__:
            continue
        predicates = []
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table
            if foreign_key.ondelete == "CASCADE" and parent in selected:
                values = [row[foreign_key.column.name] for row in selected[parent]]
                predicates.append(foreign_key.parent.in_(values))
        if not predicates:
            continue
        rows = [dict(row) for row in db.execute(select(table).where(or_(*predicates))).mappings()]
        if any(
            row.get("tenant_id") != tenant_id
            or ("subject_id" in row and row["subject_id"] != person_id)
            for row in rows
        ):
            # Refuse inconsistent cross-person links instead of cascading into
            # a different person's records, even within the same account.
            _busy()
        if rows:
            selected[table] = rows

    if db.bind.dialect.name == "postgresql":
        # Child inserts must take a key-share lock on their parent. Lock each
        # selected row with NOWAIT to close the cascade-collection race without
        # blocking unrelated people in this tenant.
        try:
            for table in tables:
                rows = selected.get(table)
                if rows:
                    db.execute(select(table).where(_keys(table, rows)).with_for_update(nowait=True))
        except OperationalError as exc:
            db.rollback()
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                _busy()
            raise

    identifiers = {
        str(value)
        for table, rows in selected.items()
        for row in rows
        for column in table.primary_key
        if column.name != "tenant_id"
        for value in [row[column.name]]
    }
    linked_jobs = {
        row["job_id"] for rows in selected.values() for row in rows if row.get("job_id") is not None
    }
    linked_jobs.update(
        row["latest_job_id"]
        for rows in selected.values()
        for row in rows
        if row.get("latest_job_id") is not None
    )
    jobs = Base.metadata.tables["tasks.jobs"]
    outbox = Base.metadata.tables["tasks.outbox_events"]
    job_rows = list(db.execute(select(jobs).where(jobs.c.tenant_id == tenant_id)).mappings())
    events_by_job: dict[UUID, list[dict]] = {}
    for event in db.execute(
        select(outbox.c.aggregate_id, outbox.c.payload).where(outbox.c.tenant_id == tenant_id)
    ).mappings():
        events_by_job.setdefault(event["aggregate_id"], []).append(event["payload"])
    linked_rows = []
    for job in job_rows:
        if (
            job["id"] in linked_jobs
            or _references(job["payload"], identifiers)
            or any(
                _references(payload, identifiers) for payload in events_by_job.get(job["id"], [])
            )
        ):
            linked_rows.append(job)
            if job["status"] in {"queued", "running"} and job["kind"] != "production.cleanup":
                _busy()

    # Also protect synchronous provider calls that do not create a task row.
    # Their invocation record has no person foreign key, so active calls briefly
    # serialize deletion for the owning account.
    invocations = Base.metadata.tables["model_gateway.model_invocations"]
    if db.execute(
        select(invocations.c.id)
        .where(invocations.c.tenant_id == tenant_id, invocations.c.state == "running")
        .limit(1)
    ).first():
        _busy()
    for name, field, active in (
        ("billing.billing_charges", "status", {"reserved"}),
        ("script.script_generation_receipts", "status", {"running", "processing"}),
    ):
        table = Base.metadata.tables[name]
        if db.execute(
            select(table.c.tenant_id)
            .where(
                table.c.tenant_id == tenant_id,
                table.c[field].in_(active),
            )
            .limit(1)
        ).first():
            _busy()
    for table, rows in selected.items():
        if table.name in {"production_runs", "interview_turn_workflows"}:
            if any(row["status"] not in {"completed", "failed", "cancelled"} for row in rows):
                _busy()
        if table.name == "interview_voice_calls":
            if any(row["status"] not in {"completed", "failed", "ended", "closed"} for row in rows):
                _busy()

    for job in linked_rows:
        if job["status"] == "running":
            _busy()
        # Preserve job/accounting history, but permanently disable retries
        # whose inputs have just been removed.
        db.execute(
            update(jobs)
            .where(jobs.c.id == job["id"], jobs.c.tenant_id == tenant_id)
            .values(
                error_code=ErrorCode.PERSON_DELETED,
                status="cancelled"
                if job["kind"] == "production.cleanup" and job["status"] == "queued"
                else job["status"],
            )
        )

    for table in tables:
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table
            if foreign_key.ondelete != "SET NULL" or parent not in selected:
                continue
            values = [row[foreign_key.column.name] for row in selected[parent]]
            db.execute(
                update(table)
                .where(table.c.tenant_id == tenant_id, foreign_key.parent.in_(values))
                .values({foreign_key.parent.name: None})
            )
    # Explicit child-first deletion also works in SQLite test databases where
    # server-side foreign-key cascading is not enabled.
    for table in reversed(tables):
        if table in selected:
            db.execute(delete(table).where(_keys(table, selected[table])))
    audit(
        db,
        tenant_id,
        "person.deleted",
        "person",
        person_id,
        {"deleted_records": {table.fullname: len(rows) for table, rows in selected.items()}},
    )
    db.commit()
