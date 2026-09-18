from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import select

from app.adapters.contracts import AdapterError
from app.adapters.http import configured_url
from app.adapters.qbittorrent import absolute_path
from app.api.dependencies import Admin, Database
from app.api.metadata import adapter_http_error
from app.db.models import AuditEvent, Integration
from app.domain import downloaders
from app.domain.downloaders import DownloadMapping
from app.domain.operations import transaction_lock
from app.domain.source_network import check_actor
from app.security import decrypt_secrets, encrypt_secrets

router = APIRouter(prefix="/downloaders", tags=["downloaders"])


class DownloaderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="qBittorrent", min_length=1, max_length=120)
    base_url: str = Field(max_length=2000)
    username: SecretStr | None = Field(default=None, min_length=1, max_length=300)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=1000)
    save_path: str = Field(max_length=2000)
    category: str = Field(default="book-search", pattern=r"^[A-Za-z0-9_-]{1,100}$")
    mappings: list[DownloadMapping] = Field(min_length=1, max_length=20)
    enabled: bool = True
    expected_generation: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def name_value(cls, value):
        if not value.strip():
            raise ValueError("Enter a connection name")
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value):
        return configured_url(value)

    @field_validator("save_path")
    @classmethod
    def path(cls, value):
        return absolute_path(value)

    @model_validator(mode="after")
    def credentials(self):
        if bool(self.username) != bool(self.password):
            raise ValueError("Enter both username and password when replacing credentials")
        return self


class DownloaderMappingView(DownloadMapping):
    worker_path: str


class DownloaderView(BaseModel):
    id: UUID
    name: str
    base_url: str
    enabled: bool
    has_credentials: bool
    generation: int
    status: str
    last_error: str | None
    last_success_at: datetime | None
    version: str | None
    save_path: str
    category: str
    mappings: list[DownloaderMappingView]
    mappings_current: bool
    dispatch_available: bool = False


class PathPreviewInput(BaseModel):
    path: str = Field(max_length=2000)
    expected_generation: int = Field(ge=1)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value):
        return absolute_path(value)


class PathPreviewView(BaseModel):
    download_path: str
    source_key: str
    relative_path: str
    worker_path: str
    filesystem_verified: bool = False


def view(row):
    return DownloaderView(
        id=row.id,
        name=row.name,
        base_url=row.base_url,
        enabled=row.enabled,
        has_credentials=bool(row.encrypted_secrets),
        generation=row.credential_generation,
        status=row.status,
        last_error=row.last_error,
        last_success_at=row.last_success_at,
        version=row.capabilities.get("version"),
        save_path=row.config["save_path"],
        category=row.config["category"],
        mappings=[
            DownloaderMappingView(
                download_root=mapping["download_root"],
                source_key=mapping["source_key"],
                worker_path=mapping["source_path"],
            )
            for mapping in row.config["mappings"]
        ],
        mappings_current=downloaders.mappings_current(row),
    )


@router.get("", response_model=list[DownloaderView])
async def connections(admin: Admin, db: Database):
    rows = await db.scalars(
        select(Integration)
        .where(Integration.kind == "qbittorrent", Integration.owner_id.is_(None))
        .order_by(Integration.name, Integration.id)
    )
    return [view(row) for row in rows]


async def save(body, admin, db, connection_id=None):
    await transaction_lock(db, downloaders.SETTINGS_LOCK)
    await check_actor(db, admin.id, admin=True)
    row = await downloaders.connection_or_404(db, connection_id) if connection_id else None
    if (row.credential_generation if row else 0) != body.expected_generation:
        raise HTTPException(409, "Downloader settings changed. Reload before saving.")
    if (not row or row.base_url != body.base_url) and not body.password:
        raise HTTPException(422, "Enter new credentials when connecting a new downloader endpoint")
    duplicate = await db.scalar(
        select(Integration).where(
            Integration.kind == "qbittorrent", Integration.base_url == body.base_url
        )
    )
    if duplicate and (not row or duplicate.id != row.id):
        raise HTTPException(409, "This downloader endpoint already has a connection")
    mappings = downloaders.bind_mappings(body.mappings, body.save_path)
    secrets = decrypt_secrets(row.encrypted_secrets) if row else {}
    if body.username and body.password:
        secrets = {
            "username": body.username.get_secret_value(),
            "password": body.password.get_secret_value(),
        }
    if not row:
        row = Integration(kind="qbittorrent", credential_generation=0)
        db.add(row)
    row.name, row.base_url, row.enabled = body.name, body.base_url, body.enabled
    row.encrypted_secrets = encrypt_secrets(secrets)
    row.config = {"save_path": body.save_path, "category": body.category, "mappings": mappings}
    row.credential_generation += 1
    row.capabilities = {}
    row.status, row.last_error, row.last_success_at = "untested", None, None
    # Preserve active diagnostic leases and cooldowns across configuration edits.
    await db.flush()
    db.add(AuditEvent(actor_id=admin.id, action="downloader.saved", entity_id=row.id))
    await db.commit()
    return view(row)


@router.post("", response_model=DownloaderView, status_code=201)
async def create_connection(body: DownloaderInput, admin: Admin, db: Database):
    return await save(body, admin, db)


@router.put("/{connection_id}", response_model=DownloaderView)
async def update_connection(connection_id: UUID, body: DownloaderInput, admin: Admin, db: Database):
    return await save(body, admin, db, connection_id)


@router.post("/{connection_id}/test", response_model=DownloaderView)
async def test_connection(connection_id: UUID, admin: Admin, db: Database):
    user_id = admin.id
    await db.rollback()
    try:
        await downloaders.test_connection(user_id, connection_id)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    return view(await downloaders.connection_or_404(db, connection_id))


@router.post("/{connection_id}/preview-path", response_model=PathPreviewView)
async def preview_path(connection_id: UUID, body: PathPreviewInput, admin: Admin, db: Database):
    row = await downloaders.connection_or_404(db, connection_id)
    if row.credential_generation != body.expected_generation:
        raise HTTPException(409, "Downloader settings changed. Reload before previewing.")
    return PathPreviewView(**downloaders.mapped_path(row, body.path))
