from lifereel_api.core.database import SessionLocal
from lifereel_api.core.seed import seed_foundation


def main() -> None:
    with SessionLocal() as db:
        seed_foundation(db)


if __name__ == "__main__":
    main()
