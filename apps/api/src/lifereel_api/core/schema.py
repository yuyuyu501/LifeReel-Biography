"""Application namespaces within the existing, single PostgreSQL database."""

from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import DDLCompiler

SERVICE_SCHEMAS = (
    "identity",
    "interview",
    "memory",
    "script",
    "book",
    "media",
    "billing",
    "tasks",
    "model_gateway",
)

# SQLite is a lightweight test backend; real migration tests use PostgreSQL.
SQLITE_SCHEMA_MAP = dict.fromkeys(SERVICE_SCHEMAS)


@compiles(ForeignKeyConstraint, "sqlite")
def compile_sqlite_foreign_key(constraint, compiler, **kwargs):
    # SQLite normally omits cross-schema foreign keys. Our tests flatten all
    # namespaces into one database, so retain those constraints after translation.
    local = constraint.elements[0].parent.table.schema
    remote = constraint.elements[0].column.table.schema
    translated = compiler.schema_translate_map or {}
    if translated.get(local, local) != translated.get(remote, remote):
        return None
    return DDLCompiler.visit_foreign_key_constraint(compiler, constraint, **kwargs)
