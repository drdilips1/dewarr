from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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
    text,
)
from sqlalchemy import (
    Identity as SQLIdentity,
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
    __table_args__ = (
        CheckConstraint("redirect_to IS NULL OR redirect_to != id", name="work_redirect_not_self"),
    )
    title: Mapped[str] = mapped_column(String(600), index=True)
    authors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20))
    cover_url: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    redirect_to: Mapped[UUID | None] = mapped_column(ForeignKey("works.id"), index=True)
    metadata_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    catalog_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    match_key: Mapped[str | None] = mapped_column(String(64), index=True)


class Version(Identity, Base):
    __tablename__ = "versions"
    __table_args__ = (
        CheckConstraint("medium IN ('ebook', 'audio', 'print', 'unknown')", name="version_medium"),
    )
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
    metadata_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("work_metadata_sources.id"), index=True
    )
    pending_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


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


class IdentityChange(Identity, Base):
    __tablename__ = "identity_changes"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('asset_match', 'source_detach', 'version_review', 'work_merge')",
            name="identity_changes_kind_check",
        ),
    )
    sequence: Mapped[int] = mapped_column(BigInteger, SQLIdentity(), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[UUID] = mapped_column(index=True)
    work_id: Mapped[UUID | None] = mapped_column(ForeignKey("works.id"), index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    before: Mapped[dict[str, Any]] = mapped_column(JSONB)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(String(500))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


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


class CatalogAccount(Base):
    __tablename__ = "catalog_accounts"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    encrypted_token: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="untested")
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MetadataSettings(Base):
    __tablename__ = "metadata_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ProviderCache(Base):
    __tablename__ = "provider_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ProviderBudget(Base):
    __tablename__ = "provider_budgets"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    next_request_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkMetadataSource(Identity, Base):
    __tablename__ = "work_metadata_sources"
    __table_args__ = (UniqueConstraint("work_id", "provider", "external_id"),)
    work_id: Mapped[UUID] = mapped_column(ForeignKey("works.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200), index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_match: Mapped[bool] = mapped_column(Boolean, default=False)


class AcquisitionIntent(Identity, Base):
    __tablename__ = "acquisition_intents"
    __table_args__ = (UniqueConstraint("owner_id", "work_id", "fingerprint"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    work_id: Mapped[UUID] = mapped_column(ForeignKey("works.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    specification: Mapped[dict[str, Any]] = mapped_column(JSONB)


class AcquisitionReason(Identity, Base):
    __tablename__ = "acquisition_reasons"
    __table_args__ = (
        UniqueConstraint("intent_id", "kind", "reference"),
        CheckConstraint("kind IN ('manual', 'list')"),
    )
    intent_id: Mapped[UUID] = mapped_column(ForeignKey("acquisition_intents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    list_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("book_lists.id", ondelete="SET NULL"), index=True
    )


class AcquisitionReservation(Identity, Base):
    __tablename__ = "acquisition_reservations"
    __table_args__ = (CheckConstraint("state IN ('planned', 'released')"),)
    work_id: Mapped[UUID] = mapped_column(ForeignKey("works.id"), index=True)
    destination_id: Mapped[UUID | None] = mapped_column(ForeignKey("libraries.id"))
    scope: Mapped[str] = mapped_column(String(80))
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20), default="planned")


class AcquisitionTarget(Identity, Base):
    __tablename__ = "acquisition_targets"
    __table_args__ = (
        UniqueConstraint("intent_id", "slot"),
        CheckConstraint("slot IN ('ebook', 'audio', 'either')"),
        CheckConstraint(
            "state IN ('wanted', 'satisfied', 'awaiting-inventory', 'paused', 'cancelled')"
        ),
    )
    intent_id: Mapped[UUID] = mapped_column(ForeignKey("acquisition_intents.id"), index=True)
    slot: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(30), default="wanted")
    message: Mapped[str] = mapped_column(String(300))
    reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("acquisition_reservations.id"), index=True
    )
    satisfied_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("library_assets.id"))


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB)


class DownloadInspection(Identity, Base):
    __tablename__ = "download_inspections"
    __table_args__ = (CheckConstraint("state IN ('queued', 'running', 'ready', 'failed')"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    operation_id: Mapped[UUID] = mapped_column(ForeignKey("operations.id"), unique=True)
    source_key: Mapped[str] = mapped_column(String(60))
    source_path: Mapped[str] = mapped_column(Text)
    relative_path: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(20), default="queued")
    message: Mapped[str] = mapped_column(String(300), default="Waiting to inspect completed files")
    run_token: Mapped[UUID | None] = mapped_column()
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class InspectionGrouping(Identity, Base):
    __tablename__ = "inspection_groupings"
    __table_args__ = (UniqueConstraint("inspection_id", "position"),)
    inspection_id: Mapped[UUID] = mapped_column(ForeignKey("download_inspections.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    revision: Mapped[str] = mapped_column(String(64))
    previous_revision: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)


class FrozenImportPlan(Identity, Base):
    __tablename__ = "frozen_import_plans"
    __table_args__ = (UniqueConstraint("inspection_id", "revision"),)
    inspection_id: Mapped[UUID] = mapped_column(ForeignKey("download_inspections.id"), index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    revision: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ImportDestination(Identity, Base):
    __tablename__ = "import_destinations"
    __table_args__ = (
        CheckConstraint("medium IN ('ebook', 'audio')"),
        CheckConstraint("mode IN ('hardlink', 'copy')"),
    )
    root_key: Mapped[str] = mapped_column(String(60), unique=True)
    library_id: Mapped[UUID] = mapped_column(ForeignKey("libraries.id"))
    medium: Mapped[str] = mapped_column(String(10))
    backend_path: Mapped[str] = mapped_column(String(1024))
    mode: Mapped[str] = mapped_column(String(10), default="hardlink")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    probe: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    probe_operation_id: Mapped[UUID | None] = mapped_column(ForeignKey("operations.id"))
    probe_token: Mapped[UUID | None] = mapped_column()


class ImportRun(Identity, Base):
    __tablename__ = "import_runs"
    __table_args__ = (UniqueConstraint("owner_id", "command_key"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("frozen_import_plans.id"))
    command_key: Mapped[str] = mapped_column(String(200))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ImportEntry(Identity, Base):
    __tablename__ = "import_entries"
    __table_args__ = (
        UniqueConstraint("run_id", "group_id"),
        CheckConstraint(
            "state IN ('queued', 'publishing', 'awaiting-library', 'confirmed', 'held', 'skipped')"
        ),
        Index(
            "uq_import_reserved_version",
            "destination_id",
            "version_id",
            unique=True,
            postgresql_where=text("reserved"),
        ),
    )
    run_id: Mapped[UUID] = mapped_column(ForeignKey("import_runs.id"), index=True)
    group_id: Mapped[UUID] = mapped_column()
    version_id: Mapped[UUID] = mapped_column(ForeignKey("versions.id"))
    destination_id: Mapped[UUID | None] = mapped_column(ForeignKey("import_destinations.id"))
    operation_id: Mapped[UUID | None] = mapped_column(ForeignKey("operations.id"), unique=True)
    state: Mapped[str] = mapped_column(String(30), default="queued")
    message: Mapped[str] = mapped_column(String(500))
    reserved: Mapped[bool] = mapped_column(Boolean, default=False)
    specification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expected_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    run_token: Mapped[UUID | None] = mapped_column()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("library_assets.id"))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
