from lifereel_api.core.database import SessionLocal
from lifereel_api.core.seed import seed_foundation


def main() -> None:
    from lifereel_api.architecture.metadata import register_models

    register_models()
    with SessionLocal() as db:
        seed_foundation(db)
        from sqlalchemy import select

        from lifereel_api.modules.identity.models import Person
        from lifereel_api.modules.interview.profile_service import ensure

        people = list(db.scalars(select(Person)))
        for person in people:
            ensure(db, person.tenant_id, person.id)


if __name__ == "__main__":
    main()
