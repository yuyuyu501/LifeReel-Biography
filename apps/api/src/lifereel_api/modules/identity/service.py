from __future__ import annotations

from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifereel_api.core.errors import ApiError, ErrorCode
from lifereel_api.modules.identity.models import Person
from lifereel_api.modules.identity.schemas import PersonCreate, PersonUpdate


def list_persons(db: Session, tenant_id: UUID) -> list[Person]:
    return list(
        db.scalars(
            select(Person).where(Person.tenant_id == tenant_id).order_by(Person.created_at.desc())
        )
    )


def get_person(db: Session, tenant_id: UUID, person_id: UUID) -> Person:
    person = db.scalar(select(Person).where(Person.id == person_id, Person.tenant_id == tenant_id))
    if person is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.PERSON_NOT_FOUND)
    return person


def create_person(db: Session, tenant_id: UUID, payload: PersonCreate) -> Person:
    person = Person(tenant_id=tenant_id, **payload.model_dump())
    db.add(person)
    db.commit()
    db.refresh(person)
    return person


def update_person(db: Session, tenant_id: UUID, person_id: UUID, payload: PersonUpdate) -> Person:
    person = get_person(db, tenant_id, person_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    db.commit()
    db.refresh(person)
    return person
