from lifereel_api.core.database import SessionLocal
from lifereel_api.core.seed import seed_foundation


def main() -> None:
    from lifereel_api.architecture.metadata import register_models
    register_models()
    with SessionLocal() as db:
        seed_foundation(db)


if __name__ == "__main__":
    main()
