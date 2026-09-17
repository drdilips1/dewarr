from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Identity, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'member', 'viewer')"),)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="member")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    can_automate: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    resets_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Work(Identity, Base):
    __tablename__ = "works"
    title: Mapped[str] = mapped_column(String(600), index=True)
    authors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20))
    cover_url: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    redirect_to: Mapped[UUID | None] = mapped_column(ForeignKey("works.id"))
    metadata_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    catalog_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    match_key: Mapped[str | None] = mapped_column(String(64), index=True)


class Version(Identity, Base):
    __tablename__ = "versions"
    __table_args__ = (CheckConstraint("medium IN ('ebook', 'audio')"),)
    work_id: Mapped[UUID] = mapped_column(ForeignKey("works.id"), index=True)
    medium: Mapped[str] = mapped_column(String(10))
    title: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20))
    narrators: Mapped[list[str]] = mapped_column(JSONB, default=list)
    abridged: Mapped[bool | None] = mapped_column(Boolean)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Representation(Identity, Base):
    __tablename__ = "representations"
    version_id: Mapped[UUID] = mapped_column(ForeignKey("versions.id"), index=True)
    format: Mapped[str] = mapped_column(String(40))
    technical: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ProviderObject(Identity, Base):
    __tablename__ = "provider_objects"
    __table_args__ = (UniqueConstraint("provider", "kind", "external_id"),)
    provider: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(300))
    work_id: Mapped[UUID | None] = mapped_column(ForeignKey("works.id"), index=True)
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("versions.id"))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    match_status: Mapped[str] = mapped_column(String(30), default="unresolved")
    manual_lock: Mapped[bool] = mapped_column(Boolean, default=False)


class Integration(Identity, Base):
    __tablename__ = "integrations"
    kind: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    base_url: Mapped[str] = mapped_column(Text)
    encrypted_secrets: Mapped[str] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(40), default="untested")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_generation: Mapped[int] = mapped_column(Integer, default=0)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    last_error: Mapped[str | None] = mapped_column(String(500))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Library(Identity, Base):
    __tablename__ = "libraries"
    __table_args__ = (UniqueConstraint("integration_id", "external_id"),)
    integration_id: Mapped[UUID] = mapped_column(ForeignKey("integrations.id"))
    external_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    last_complete_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation: Mapped[int] = mapped_column(Integer, default=0)
    accessible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    scope_fingerprint: Mapped[str | None] = mapped_column(String(64))


class LibraryGrant(Base):
    __tablename__ = "library_grants"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    library_id: Mapped[UUID] = mapped_column(ForeignKey("libraries.id"), primary_key=True)


class LibraryAsset(Identity, Base):
    __tablename__ = "library_assets"
    __table_args__ = (
        UniqueConstraint("library_id", "external_id", "medium"),
        CheckConstraint("medium IN ('ebook', 'audio')"),
    )
    library_id: Mapped[UUID] = mapped_column(ForeignKey("libraries.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("versions.id"))
    medium: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(40), default="stale")
    full_content: Mapped[bool] = mapped_column(Boolean, default=False)
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_generation: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(String(600))
    match_status: Mapped[str] = mapped_column(
        String(40), default="unresolved", server_default="unresolved"
    )
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )


class AssetContains(Base):
    __tablename__ = "asset_contains"
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("library_assets.id"), primary_key=True)
    work_id: Mapped[UUID] = mapped_column(ForeignKey("works.id"), primary_key=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class BookList(Identity, Base):
    __tablename__ = "book_lists"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)


class ListEntry(Identity, Base):
    __tablename__ = "list_entries"
    __table_args__ = (UniqueConstraint("list_id", "work_id"),)
    list_id: Mapped[UUID] = mapped_column(ForeignKey("book_lists.id", ondelete="CASCADE"))
    work_id: Mapped[UUID] = mapped_column(ForeignKey("works.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)


class Operation(Identity, Base):
    __tablename__ = "operations"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    message: Mapped[str] = mapped_column(Text, default="Waiting for a worker")
    job_id: Mapped[int | None] = mapped_column(Integer)
    integration_id: Mapped[UUID | None] = mapped_column(ForeignKey("integrations.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEvent(Identity, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[UUID | None] = mapped_column(index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class InventoryRun(Identity, Base):
    __tablename__ = "inventory_runs"
    integration_id: Mapped[UUID] = mapped_column(ForeignKey("integrations.id"), index=True)
    operation_id: Mapped[UUID] = mapped_column(ForeignKey("operations.id"), index=True)
    credential_generation: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="collecting")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryObservation(Base):
    __tablename__ = "inventory_observations"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_runs.id", ondelete="CASCADE"), primary_key=True
    )
    library_external_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    item_external_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)


Index(
    "ix_works_title_trgm",
    Work.title,
    postgresql_using="gin",
    postgresql_ops={"title": "gin_trgm_ops"},
)
