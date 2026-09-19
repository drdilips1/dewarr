import asyncio
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, SecretStr, model_validator
from sqlalchemy import case, exists, func, or_, select

from app.adapters.catalog_providers import Hardcover, OpenLibrary
from app.adapters.catalog_types import BookData, Provider, SearchPage, SeriesData
from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.hardcover_lists import ChoicePage
from app.api.catalog import WorkInput, WorkView, work_view
from app.api.dependencies import Admin, CurrentUser, Database, Member
from app.api.operations import OperationView
from app.db.models import (
    AssetContains,
    AuditEvent,
    CatalogAccount,
    Integration,
    Library,
    LibraryAsset,
    MetadataSettings,
    Operation,
    ProviderObject,
    User,
    Version,
    Work,
    WorkMetadataSource,
)
from app.domain.availability import availability_for
from app.domain.catalog_bindings import visible_provider_works
from app.domain.catalog_enrichment import TERMINAL, effective_status, proposal, schedule_enrichment
from app.domain.catalog_metadata import (
    FIELDS,
    MetadataPreferences,
    attach_source,
    import_book,
    preferences,
    resolve_fields,
)
from app.domain.catalog_network import CatalogGateway
from app.domain.corrections import revision, source_state
from app.domain.operations import transaction_lock
from app.domain.visibility import visible_library, visible_origin_work, visible_work
from app.domain.work_graph import canonical_work, family_ids
from app.security import decrypt_secrets, encrypt_secrets

router = APIRouter(prefix="/metadata", tags=["metadata"])
MetadataField = Literal[
    "title", "authors", "description", "publication_year", "language", "cover_url"
]


class AccountInput(BaseModel):
    token: SecretStr | None = Field(default=None, min_length=1, max_length=8192)
    enabled: bool = True


class AccountView(BaseModel):
    configured: bool
    enabled: bool
    status: str
    last_error: str | None = None
    last_success_at: datetime | None = None


def account_view(row):
    return AccountView(
        configured=bool(row),
        enabled=bool(row and row.enabled),
        status=row.status if row else "not-configured",
        last_error=row.last_error if row else None,
        last_success_at=row.last_success_at if row else None,
    )


def adapter_http_error(error):
    status = {
        FailureKind.RATE_LIMIT: 429,
        FailureKind.NOT_FOUND: 404,
        FailureKind.AUTHENTICATION: 409,
        FailureKind.PERMISSION: 409,
        FailureKind.PARSER: 502,
    }.get(error.kind, 503)
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    return HTTPException(status, str(error), headers=headers)


async def current_actor(db, user_id, *, edit=False, admin=False):
    user = await db.get(User, user_id, populate_existing=True)
    if not user or not user.active:
        raise HTTPException(401, "Your account is no longer active")
    if (edit and user.role == "viewer") or (admin and user.role != "admin"):
        raise HTTPException(403, "You no longer have permission for this operation")
    return user


async def provider_call(db, user_id, provider, operation, *args, force=False):
    token, generation = None, None
    if provider == "hardcover":
        account = await db.get(CatalogAccount, user_id)
        if not account or not account.enabled:
            raise HTTPException(409, "Connect your Hardcover account in Metadata settings first")
        token, generation = decrypt_secrets(account.encrypted_token)["token"], account.generation
    scope = f"{user_id}:{generation}" if provider == "hardcover" else "public"
    await db.rollback()
    # No request transaction or connection is retained across provider I/O.
    async with CatalogGateway(
        provider,
        scope,
        token,
        force=force,
        cache=operation not in {"list_page", "list_choices", "community_lists", "community_list"},
    ) as gateway:
        adapter = (
            Hardcover(gateway.request) if provider == "hardcover" else OpenLibrary(gateway.request)
        )
        try:
            async with asyncio.timeout(60):
                value = await getattr(adapter, operation)(*args)
        except TimeoutError as error:
            raise AdapterError(
                FailureKind.TIMEOUT, "The catalog lookup took too long. Retry it."
            ) from error
        except AdapterError as error:
            if error.kind == FailureKind.PARSER:
                await gateway.invalidate()
            raise
    await current_actor(db, user_id)
    if provider == "hardcover":
        account = await db.get(CatalogAccount, user_id, populate_existing=True)
        if not account or not account.enabled or account.generation != generation:
            raise HTTPException(
                409, "Your catalog connection changed during this request. Retry it."
            )
    return value, gateway.stale, gateway.warning


@router.get("/account", response_model=AccountView)
async def get_account(user: CurrentUser, db: Database):
    return account_view(await db.get(CatalogAccount, user.id))


@router.put("/account", response_model=AccountView)
async def save_account(body: AccountInput, user: CurrentUser, db: Database):
    await transaction_lock(db, f"catalog-account:{user.id}")
    account = await db.get(CatalogAccount, user.id)
    if not account:
        if not body.token:
            raise HTTPException(422, "Enter your Hardcover API token")
        account = CatalogAccount(user_id=user.id, generation=0)
        db.add(account)
    if body.token:
        account.encrypted_token = encrypt_secrets({"token": body.token.get_secret_value()})
    account.enabled, account.status, account.last_error = body.enabled, "untested", None
    account.last_success_at = None
    account.generation += 1
    db.add(AuditEvent(actor_id=user.id, action="metadata.account.updated", entity_id=user.id))
    await db.commit()
    return account_view(account)


@router.post("/account/test", response_model=AccountView)
async def test_account(user: CurrentUser, db: Database):
    user_id = user.id
    account = await db.get(CatalogAccount, user_id)
    if not account or not account.enabled:
        raise HTTPException(409, "Connect and enable your Hardcover account first")
    generation = account.generation
    try:
        await provider_call(db, user_id, "hardcover", "test", force=True)
        status, message = "connected", None
    except AdapterError as error:
        status, message = error.kind.value, str(error)
    await transaction_lock(db, f"catalog-account:{user_id}")
    account = await db.get(CatalogAccount, user_id, populate_existing=True)
    if not account or account.generation != generation:
        raise HTTPException(409, "Connection settings changed during the test")
    account.status, account.last_error = status, message
    if status == "connected":
        account.last_success_at = datetime.now(UTC)
    await db.commit()
    return account_view(account)


@router.get("/preferences", response_model=MetadataPreferences)
async def get_preferences(user: CurrentUser, db: Database):
    return await preferences(db)


@router.put("/preferences", response_model=MetadataPreferences)
async def save_preferences(body: MetadataPreferences, user: Admin, db: Database):
    await transaction_lock(db, "metadata-preferences")
    row = await db.get(MetadataSettings, 1)
    if not row:
        row = MetadataSettings(id=1)
        db.add(row)
    row.preferences = body.model_dump()
    db.add(AuditEvent(actor_id=user.id, action="metadata.preferences.updated"))
    await db.commit()
    return body


class MetadataSearchPage(SearchPage):
    known_works: dict[str, WorkView] = Field(default_factory=dict)


async def known_works(db, user, provider, external_ids):
    matched = await visible_provider_works(db, user, [(provider, value) for value in external_ids])
    availability = await availability_for(db, user, list({work.id for work in matched.values()}))
    return {
        external_id: work_view(work, availability[work.id])
        for (_, external_id), work in matched.items()
    }


@router.get("/search", response_model=MetadataSearchPage)
async def search(
    user: CurrentUser,
    db: Database,
    q: str = Query(min_length=1, max_length=300),
    provider: Literal["automatic", "hardcover", "openlibrary"] = "automatic",
    page: int = Query(default=1, ge=1, le=100),
):
    if not q.strip():
        raise HTTPException(422, "Enter a title, author or identifier")
    user_id = user.id
    selected = provider
    if provider == "automatic":
        settings = await preferences(db)
        account = await db.get(CatalogAccount, user_id)
        selected = settings.primary if account and account.enabled else "openlibrary"
    warning = None
    try:
        result, stale, warning = await provider_call(
            db, user_id, selected, "search", q.strip(), page
        )
    except AdapterError as error:
        if provider != "automatic" or selected != "hardcover":
            raise adapter_http_error(error) from error
        try:
            result, stale, _ = await provider_call(
                db, user_id, "openlibrary", "search", q.strip(), page
            )
            warning = "Hardcover is unavailable; showing Open Library results. " + str(error)
        except AdapterError as fallback_error:
            raise adapter_http_error(fallback_error) from fallback_error
    user = await current_actor(db, user_id)
    return MetadataSearchPage(
        **result.model_dump(exclude={"stale", "warning"}),
        stale=stale,
        warning=warning,
        known_works=await known_works(
            db, user, result.provider, [book.external_id for book in result.items]
        ),
    )


class BookPreview(BaseModel):
    book: BookData
    stale: bool = False
    warning: str | None = None
    work: WorkView | None = None


@router.get("/books/{provider}/{external_id}", response_model=BookPreview)
async def preview(provider: Provider, external_id: str, user: CurrentUser, db: Database):
    user_id = user.id
    try:
        book, stale, warning = await provider_call(db, user_id, provider, "fetch", external_id)
        user = await current_actor(db, user_id)
        matched = await known_works(db, user, book.provider, [book.external_id])
        return BookPreview(
            book=book, stale=stale, warning=warning, work=matched.get(book.external_id)
        )
    except AdapterError as error:
        raise adapter_http_error(error) from error


@router.post("/books/{provider}/{external_id}/import", response_model=WorkView)
async def add_catalog_book(provider: Provider, external_id: str, user: Member, db: Database):
    user_id = user.id
    try:
        book, _, _ = await provider_call(db, user_id, provider, "fetch", external_id)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    user = await current_actor(db, user_id, edit=True)
    work = await import_book(db, user, book)
    await schedule_enrichment(db, user, work)
    db.add(AuditEvent(actor_id=user_id, action="metadata.book.imported", entity_id=work.id))
    await db.flush()
    availability = (await availability_for(db, user, [work.id]))[work.id]
    await db.commit()
    return work_view(work, availability)


async def accessible_work(db, user, work_id, *, lock=False):
    canonical = await canonical_work(db, work_id)
    query = select(Work).where(
        Work.id == canonical.id, visible_work(user), Work.redirect_to.is_(None)
    )
    if lock:
        query = query.with_for_update()
    work = await db.scalar(query)
    if not work:
        raise HTTPException(404, "Book not found")
    return work


class SourceView(BaseModel):
    id: UUID
    revision: str | None = None
    provider: Provider
    external_id: str
    title: str
    fetched_at: datetime
    cover_url: str | None
    editions_more: bool
    series: list[SeriesData]


class VersionView(BaseModel):
    id: UUID
    medium: str
    title: str | None
    language: str | None
    narrators: list[str]
    publication_year: int | None
    identifiers: dict[str, Any]
    owned: bool
    needs_review: bool


class MetadataView(BaseModel):
    fields: dict[str, Any]
    sources: list[SourceView]
    versions: list[VersionView]
    versions_total: int
    offset: int
    limit: int
    cover_choices: list[str]
    enrichment: OperationView | None = None
    enrichment_retryable: bool = False


@router.get("/works/{work_id}", response_model=MetadataView)
async def work_metadata(
    work_id: UUID,
    user: CurrentUser,
    db: Database,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=100),
):
    work = await accessible_work(db, user, work_id)
    work_id = work.id
    sources = (
        await db.scalars(
            select(WorkMetadataSource)
            .join(Work, WorkMetadataSource.work_id == Work.id)
            .where(
                visible_origin_work(user),
                WorkMetadataSource.work_id.in_(family_ids(work_id)),
                WorkMetadataSource.accepted.is_(True),
            )
            .order_by(WorkMetadataSource.provider, WorkMetadataSource.external_id)
        )
    ).all()
    source_views, covers = [], []
    for source in sources:
        book = BookData.model_validate(source.snapshot)
        source_views.append(
            SourceView(
                id=source.id,
                revision=revision(source_state(work, source)) if user.role == "admin" else None,
                provider=book.provider,
                external_id=book.external_id,
                title=book.title,
                fetched_at=source.fetched_at,
                cover_url=book.cover_url,
                editions_more=book.editions_more,
                series=book.series,
            )
        )
        covers.extend([book.cover_url, *(edition.cover_url for edition in book.editions)])
    # Public catalog editions are visible; an inventory-only version requires a library grant.
    catalog_version = exists(
        select(ProviderObject.id)
        .join(WorkMetadataSource, ProviderObject.metadata_source_id == WorkMetadataSource.id)
        .join(Work, Work.id == WorkMetadataSource.work_id)
        .where(
            visible_origin_work(user),
            ProviderObject.work_id.in_(family_ids(work_id)),
            ProviderObject.version_id == Version.id,
            ProviderObject.kind == "edition",
            WorkMetadataSource.accepted.is_(True),
            WorkMetadataSource.provider.in_(["hardcover", "openlibrary"]),
        )
    )
    accessible_asset = (
        select(LibraryAsset.id)
        .join(Library)
        .join(Integration)
        .join(AssetContains)
        .where(
            LibraryAsset.version_id == Version.id,
            AssetContains.work_id.in_(family_ids(work_id)),
            Library.accessible.is_(True),
            Integration.enabled.is_(True),
            visible_library(user),
        )
    )
    owned = exists(
        accessible_asset.where(
            AssetContains.verified.is_(True),
            LibraryAsset.full_content.is_(True),
            LibraryAsset.state.in_(["present", "stale"]),
        )
    )
    conditions = [Version.work_id.in_(family_ids(work_id))]
    conditions.append(or_(catalog_version, exists(accessible_asset)))
    needs_review = exists(
        select(ProviderObject.id).where(
            ProviderObject.version_id == Version.id, ProviderObject.match_status == "needs-review"
        )
    )
    language = (await preferences(db)).language.casefold()
    preferred_language = case((func.lower(Version.language) == language, 0), else_=1)
    rows = (
        await db.execute(
            select(Version, owned, needs_review)
            .where(*conditions)
            .order_by(preferred_language, Version.medium, Version.publication_year, Version.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total = await db.scalar(select(func.count()).select_from(Version).where(*conditions))
    enrichment = await db.scalar(
        select(Operation)
        .where(
            Operation.kind == "metadata.enrich",
            Operation.payload["work_id"].astext == str(work_id),
            Operation.owner_id == user.id,
        )
        .order_by(Operation.created_at.desc(), Operation.id)
        .limit(1)
    )
    enrichment_view = OperationView.model_validate(enrichment) if enrichment else None
    if enrichment:
        status = await effective_status(db, enrichment)
        enrichment_view = OperationView.model_validate(enrichment)
        if status != enrichment.status:
            enrichment_view = enrichment_view.model_copy(
                update={
                    "status": status,
                    "message": "The metadata worker ended before completion; retry the lookup",
                }
            )
    return MetadataView(
        enrichment=enrichment_view,
        enrichment_retryable=bool(
            user.role == "admin"
            and enrichment
            and enrichment_view.status in TERMINAL
            and await proposal(db, work, await preferences(db))
        ),
        fields=work.metadata_fields.get("fields", {}),
        sources=source_views,
        versions=[
            VersionView(
                id=version.id,
                medium=version.medium,
                title=version.title,
                language=version.language,
                narrators=version.narrators,
                publication_year=version.publication_year,
                identifiers=version.identifiers,
                owned=available,
                needs_review=review,
            )
            for version, available, review in rows
        ],
        versions_total=total or 0,
        offset=offset,
        limit=limit,
        cover_choices=list(dict.fromkeys(value for value in covers if value)),
    )


class MatchInput(BaseModel):
    provider: Provider
    external_id: str = Field(min_length=1, max_length=200)
    confirm_match: bool = False


@router.post("/works/{work_id}/enrichment", response_model=OperationView, status_code=202)
async def retry_enrichment(work_id: UUID, user: Admin, db: Database):
    work = await accessible_work(db, user, work_id, lock=True)
    operation = await schedule_enrichment(db, user, work, retry=True)
    if not operation:
        raise HTTPException(409, "No automatic secondary lookup is needed or enabled for this book")
    await db.commit()
    return operation


@router.post("/works/{work_id}/source", response_model=WorkView)
async def match_source(work_id: UUID, body: MatchInput, user: Admin, db: Database):
    user_id = user.id
    await accessible_work(db, user, work_id)
    if not body.confirm_match:
        linked = await db.scalar(
            select(WorkMetadataSource.id).where(
                WorkMetadataSource.work_id.in_(family_ids(work_id)),
                WorkMetadataSource.provider == body.provider,
                WorkMetadataSource.external_id == body.external_id,
                WorkMetadataSource.accepted.is_(True),
            )
        )
        if not linked:
            raise HTTPException(409, "Preview the catalog result and confirm this book match")
    try:
        book, stale, _ = await provider_call(
            db, user_id, body.provider, "fetch", body.external_id, force=True
        )
        if stale:
            raise HTTPException(
                503,
                "The provider is unavailable. Existing metadata was preserved; "
                "retry the refresh later.",
            )
    except AdapterError as error:
        raise adapter_http_error(error) from error
    user = await current_actor(db, user_id, admin=True)
    work = await accessible_work(db, user, work_id, lock=True)
    await attach_source(db, work, book, explicit=body.confirm_match)
    await schedule_enrichment(db, user, work)
    db.add(
        AuditEvent(
            actor_id=user_id,
            action="metadata.source.matched" if body.confirm_match else "metadata.source.refreshed",
            entity_id=work_id,
        )
    )
    availability = (await availability_for(db, user, [work_id]))[work_id]
    await db.commit()
    return work_view(work, availability)


@router.post("/works/{work_id}/source/editions", response_model=WorkView)
async def load_editions(work_id: UUID, body: MatchInput, user: Admin, db: Database):
    user_id = user.id
    await accessible_work(db, user, work_id)
    source = await db.scalar(
        select(WorkMetadataSource).where(
            WorkMetadataSource.work_id.in_(family_ids(work_id)),
            WorkMetadataSource.provider == body.provider,
            WorkMetadataSource.external_id == body.external_id,
            WorkMetadataSource.accepted.is_(True),
        )
    )
    if not source:
        raise HTTPException(404, "Match this catalog source first")
    offset = source.snapshot.get("next_edition_offset")
    if not isinstance(offset, int) or offset <= 0:
        raise HTTPException(409, "All currently listed editions have been loaded")
    if offset > 10000:
        raise HTTPException(
            409, "This book reached the edition lookup limit. Review its catalog match."
        )
    try:
        book, stale, _ = await provider_call(
            db, user_id, body.provider, "fetch", body.external_id, offset
        )
        if stale:
            raise HTTPException(503, "The provider is unavailable. Retry loading editions later.")
    except AdapterError as error:
        raise adapter_http_error(error) from error
    user = await current_actor(db, user_id, admin=True)
    work = await accessible_work(db, user, work_id, lock=True)
    await attach_source(db, work, book)
    db.add(
        AuditEvent(
            actor_id=user_id,
            action="metadata.editions.loaded",
            entity_id=work_id,
            detail={"provider": body.provider, "offset": offset},
        )
    )
    availability = (await availability_for(db, user, [work_id]))[work_id]
    await db.commit()
    return work_view(work, availability)


class EditValues(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=600)
    authors: list[str] | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=30000)
    language: str | None = Field(default=None, max_length=20)
    publication_year: int | None = Field(default=None, ge=0, le=9999)
    cover_url: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def valid(self):
        if "title" in self.model_fields_set:
            if self.title is None:
                raise ValueError("A title cannot be cleared")
            self.title = WorkInput.title_is_not_blank(self.title)
        if "authors" in self.model_fields_set:
            if self.authors is None:
                raise ValueError("Use an empty author list to clear authors")
            self.authors = WorkInput.validate_authors(self.authors)
        return self


class MetadataEdit(BaseModel):
    values: EditValues = Field(default_factory=EditValues)
    unlock: list[MetadataField] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def distinct(self):
        if set(self.values.model_fields_set) & set(self.unlock):
            raise ValueError("Do not edit and unlock the same field in one operation")
        return self


@router.patch("/works/{work_id}", response_model=WorkView)
async def edit_metadata(work_id: UUID, body: MetadataEdit, user: Admin, db: Database):
    work = await accessible_work(db, user, work_id, lock=True)
    changes = body.values.model_dump(exclude_unset=True)
    if changes.get("cover_url"):
        choices = (await work_metadata(work_id, user, db, 0, 1)).cover_choices
        if changes["cover_url"] not in choices:
            raise HTTPException(422, "Choose a cover from this book's matched catalog sources")
    fields = dict(work.metadata_fields.get("fields", {}))
    before = {name: getattr(work, name) for name in FIELDS}
    for name, value in changes.items():
        setattr(work, name, value)
        fields[name] = {
            "value": value,
            "provider": "manual",
            "locked": True,
            "reason": "Protected user edit",
            "observed_at": datetime.now(UTC).isoformat(),
        }
    for name in body.unlock:
        if name in fields:
            fields[name] = {**fields[name], "locked": False, "reason": "Provider refresh enabled"}
    work.metadata_fields = {**work.metadata_fields, "fields": fields}
    await resolve_fields(db, work, await preferences(db))
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="metadata.fields.edited",
            entity_id=work_id,
            detail={
                "before": before,
                "after": {name: getattr(work, name) for name in FIELDS},
                "unlocked": body.unlock,
            },
        )
    )
    availability = (await availability_for(db, user, [work_id]))[work_id]
    await db.commit()
    return work_view(work, availability)


@router.get("/hardcover-lists", response_model=ChoicePage)
async def hardcover_lists(
    user: Member,
    db: Database,
    mode: Literal["owned", "followed", "public"] = "owned",
    cursor: int = Query(default=0, ge=0, le=2147483647),
):
    try:
        value, _, _ = await provider_call(
            db, user.id, "hardcover", "list_choices", mode, cursor, force=True
        )
        return value
    except AdapterError as error:
        raise adapter_http_error(error) from error
