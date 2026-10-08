from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from lifereel_api.core.config import get_settings
from lifereel_api.core.database import Base
from lifereel_api.core.schema import SERVICE_SCHEMAS
from lifereel_api.modules.auth import models as auth_models  # noqa: F401
from lifereel_api.modules.billing import models as billing_models  # noqa: F401
from lifereel_api.modules.book import models as book_models  # noqa: F401
from lifereel_api.modules.evidence import models as evidence_models  # noqa: F401
from lifereel_api.modules.governance import models as governance_models  # noqa: F401
from lifereel_api.modules.identity import models as identity_models  # noqa: F401
from lifereel_api.modules.interview import models as interview_models  # noqa: F401
from lifereel_api.modules.interview import profile_models as profile_models  # noqa: F401
from lifereel_api.modules.jobs import events as job_events  # noqa: F401
from lifereel_api.modules.jobs import models as job_models  # noqa: F401
from lifereel_api.modules.memory import models as memory_models  # noqa: F401
from lifereel_api.modules.orchestration import service as orchestration_service  # noqa: F401
from lifereel_api.modules.production import models as production_models  # noqa: F401
from lifereel_api.modules.production import (
    reference_models as production_reference_models,  # noqa: F401
)
from lifereel_api.modules.publication import models as publication_models  # noqa: F401
from lifereel_api.modules.restoration import models as restoration_models  # noqa: F401
from lifereel_api.modules.script import models as script_models  # noqa: F401
from lifereel_api.providers import models as provider_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ConfigParser interpolates percent signs, including URL-encoded passwords.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata
application_tables = {table.name for table in target_metadata.tables.values()}


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in (None, "public", *SERVICE_SCHEMAS)
    if type_ == "table":
        # Do not propose deleting unrelated user or extension tables.
        return name in application_tables
    return True


def migration_options():
    postgres = get_settings().database_url.startswith("postgresql")
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        "include_schemas": postgres,
        "include_name": include_name,
        "version_table_schema": "public" if postgres else None,
    }


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **migration_options(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, **migration_options())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
