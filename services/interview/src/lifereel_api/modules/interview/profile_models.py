from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lifereel_api.core.database import Base
from lifereel_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class LifeProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "life_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subject_id", name="uq_life_profile_subject"),
        {"schema": "interview"},
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.persons.id", ondelete="CASCADE"), index=True
    )
    template_version: Mapped[str] = mapped_column(String(80))
    version_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    readiness: Mapped[dict] = mapped_column(JSON, default=dict)


class LifeProfileEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "life_profile_entries"
    __table_args__ = (
        UniqueConstraint("profile_id", "field_key", "record_key", name="uq_profile_entry_key"),
        {"schema": "interview"},
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("interview.life_profiles.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(100))
    record_key: Mapped[str] = mapped_column(String(100), default="single")
    value: Mapped[dict | list | str] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(24), default="filled")
    certainty: Mapped[str] = mapped_column(String(24), default="reported")
    use_scope: Mapped[str] = mapped_column(String(24), default="works")
    source: Mapped[dict] = mapped_column(JSON, default=dict)
    pseudonyms: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    version_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class LifeProfileRevision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "life_profile_revisions"
    __table_args__ = (
        UniqueConstraint("profile_id", "version_number", name="uq_profile_revision_version"),
        UniqueConstraint("profile_id", "request_id", name="uq_profile_revision_request"),
        {"schema": "interview"},
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity.tenants.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("interview.life_profiles.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    actor: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[str] = mapped_column(String(64))
    changes: Mapped[list] = mapped_column(JSON, default=list)
