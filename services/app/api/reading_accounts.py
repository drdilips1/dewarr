"""Account-level shelf discovery layered over durable list subscriptions."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.adapters import goodreads_profile
from app.adapters.contracts import AdapterError
from app.api.dependencies import Database, Member
from app.api.list_subscriptions import SubscriptionView
from app.api.list_subscriptions import view as subscription_view
from app.api.metadata import adapter_http_error, current_actor, provider_call
from app.config import get_settings
from app.db.models import AuditEvent, BookList, GoodreadsAccount, ListSubscription
from app.domain.list_subscriptions import begin
from app.domain.operations import transaction_lock
from app.security import decrypt_secrets, encrypt_secrets

router = APIRouter(prefix="/reading-accounts", tags=["reading-accounts"])


class GoodreadsConnect(BaseModel):
    profile: str = Field(min_length=1, max_length=2000)

    @field_validator("profile")
    @classmethod
    def valid_profile(cls, value):
        goodreads_profile.profile_input(value)
        return value


class GoodreadsShelf(BaseModel):
    external_id: str
    name: str
    count: int | None


class GoodreadsAccountView(BaseModel):
    user_id: str
    name: str
    profile_url: str
    selected: str | None
    shelves: list[GoodreadsShelf]
    discovered_at: datetime
    warning: str | None


class ReadingSubscription(BaseModel):
    list_id: UUID
    name: str
    external_id: str
    account_id: str | None
    subscription: SubscriptionView


class FollowReadingList(BaseModel):
    provider: Literal["goodreads", "hardcover"]
    external_id: str = Field(min_length=1, max_length=200)
    interval_minutes: int = Field(default=60, ge=30, le=1440)


class ReadingFollowResult(BaseModel):
    list_id: UUID
    reused: bool


def account_view(row):
    config = decrypt_secrets(row.encrypted_config)
    return GoodreadsAccountView(
        user_id=config["user_id"],
        name=config["name"],
        profile_url=f"https://www.goodreads.com/user/show/{config['user_id']}",
        selected=config.get("selected"),
        shelves=config["shelves"],
        discovered_at=row.discovered_at,
        warning=config.get("warning"),
    )


@router.get("/goodreads", response_model=GoodreadsAccountView | None)
async def goodreads_account(user: Member, db: Database):
    row = await db.get(GoodreadsAccount, user.id)
    return account_view(row) if row else None


async def save_discovery(db, user, config, expected=None):
    user_id = user.id
    await db.rollback()
    try:
        result = await goodreads_profile.discover(config)
    except AdapterError as error:
        raise adapter_http_error(error) from error
    await transaction_lock(db, f"goodreads-account:{user_id}")
    user = await current_actor(db, user_id, edit=True)
    row = await db.get(GoodreadsAccount, user_id, populate_existing=True)
    if expected is not None and (not row or row.encrypted_config != expected):
        raise HTTPException(409, "Your Goodreads connection changed. Reload before checking again.")
    if not row:
        row = GoodreadsAccount(user_id=user.id)
        db.add(row)
    row.encrypted_config = encrypt_secrets(result)
    row.discovered_at = datetime.now(UTC)
    db.add(AuditEvent(actor_id=user.id, action="goodreads.account.connected", entity_id=user.id))
    await db.commit()
    return account_view(row)


@router.put("/goodreads", response_model=GoodreadsAccountView)
async def connect_goodreads(body: GoodreadsConnect, user: Member, db: Database):
    return await save_discovery(db, user, goodreads_profile.profile_input(body.profile))


@router.post("/goodreads/discover", response_model=GoodreadsAccountView)
async def discover_goodreads(user: Member, db: Database):
    row = await db.get(GoodreadsAccount, user.id)
    if not row:
        raise HTTPException(409, "Connect Goodreads first")
    expected = row.encrypted_config
    return await save_discovery(db, user, decrypt_secrets(expected), expected)


@router.get("/subscriptions", response_model=list[ReadingSubscription])
async def subscriptions(user: Member, db: Database):
    rows = (
        await db.execute(
            select(BookList, ListSubscription)
            .join(ListSubscription, ListSubscription.list_id == BookList.id)
            .where(BookList.owner_id == user.id)
            .order_by(BookList.created_at, BookList.id)
        )
    ).all()
    results = []
    for item, sub in rows:
        config = decrypt_secrets(sub.encrypted_config)
        if sub.provider == "goodreads":
            source = goodreads_profile.profile_input(config["url"])
            account_id, external_id = source["user_id"], source["selected"] or "all"
        else:
            account_id, external_id = None, config["external_id"]
        results.append(
            ReadingSubscription(
                list_id=item.id,
                name=item.name,
                account_id=account_id,
                external_id=external_id,
                subscription=await subscription_view(db, sub),
            )
        )
    await db.commit()
    return results


@router.post("/follow", response_model=ReadingFollowResult)
async def follow(body: FollowReadingList, user: Member, db: Database):
    user_id = user.id
    if get_settings().recovery_mode:
        raise HTTPException(409, "New list observations are paused during recovery")
    if body.provider == "goodreads":
        account = await db.get(GoodreadsAccount, user.id)
        if not account:
            raise HTTPException(409, "Connect Goodreads first")
        config = decrypt_secrets(account.encrypted_config)
        choice = next((s for s in config["shelves"] if s["external_id"] == body.external_id), None)
        if not choice:
            raise HTTPException(422, "Find your Goodreads shelves again before following this one")
        name = choice["name"]
        source_config = {"url": goodreads_profile.shelf_url(config, body.external_id)}
        identity = f"{config['user_id']}:{body.external_id}"
        lock = f"goodreads-follow:{user.id}:{identity}"
    else:
        if (
            not body.external_id.isascii()
            or not body.external_id.isdigit()
            or not (0 < int(body.external_id) <= 2147483647)
        ):
            raise HTTPException(422, "Invalid Hardcover list ID")
        try:
            page, _, _ = await provider_call(
                db, user.id, "hardcover", "list_page", body.external_id, 0, force=True
            )
        except AdapterError as error:
            raise adapter_http_error(error) from error
        user = await current_actor(db, user_id, edit=True)
        name = page.info["name"]
        source_config = {"external_id": body.external_id, "name": name}
        identity = body.external_id
        # Serialize with the existing community-list follow entry point too.
        lock = f"community-follow:{user.id}:{identity}"
    await transaction_lock(db, lock)
    rows = (
        await db.execute(
            select(BookList, ListSubscription)
            .join(ListSubscription, ListSubscription.list_id == BookList.id)
            .where(BookList.owner_id == user.id, ListSubscription.provider == body.provider)
        )
    ).all()
    for item, subscription in rows:
        saved = decrypt_secrets(subscription.encrypted_config)
        if body.provider == "goodreads":
            source = goodreads_profile.profile_input(saved["url"])
            saved_identity = f"{source['user_id']}:{source['selected']}"
        else:
            saved_identity = saved["external_id"]
        if saved_identity == identity:
            return ReadingFollowResult(list_id=item.id, reused=True)
    item = BookList(owner_id=user.id, name=name[:200], shared=False)
    db.add(item)
    await db.flush()
    subscription = ListSubscription(
        list_id=item.id,
        provider=body.provider,
        encrypted_config=encrypt_secrets(source_config),
        interval_minutes=body.interval_minutes,
        enabled=True,
        next_sync_at=datetime.now(UTC),
    )
    db.add(subscription)
    await db.flush()
    await begin(db, user, item.id, f"reading-follow:{uuid4()}")
    db.add(AuditEvent(actor_id=user.id, action="reading.list.followed", entity_id=item.id))
    await db.commit()
    return ReadingFollowResult(list_id=item.id, reused=False)
