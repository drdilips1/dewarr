"""Review current household access while restored work remains fenced."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select

from app.db.models import (
    AuditEvent,
    Integration,
    Library,
    LibraryGrant,
    LoginSession,
    OidcIdentity,
    Operation,
    PlexIdentity,
    RecoveryFinding,
    User,
)
from app.db.session import session_factory
from app.domain import recovery_reconciliation as reviews
from app.domain.recovery_scans import MAX_RECORDS, ScanHeld, digest

KIND = "recovery.access"


class AccessChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: UUID
    active: bool
    role: Literal["admin", "member", "viewer"]
    can_automate: bool
    permissions: int | None = None
    library_ids: list[UUID] = Field(max_length=10000)

    @model_validator(mode="after")
    def validate_choice(self):
        if len(set(self.library_ids)) != len(self.library_ids):
            raise ValueError("Choose each library once")
        if self.role == "viewer" and self.can_automate:
            raise ValueError("Viewers cannot run acquisition automation")
        return self


def access_state(user, grants):
    from app.domain.permissions import coerce_recovery_permissions

    return {
        "active": user["active"],
        "role": user["role"],
        "can_automate": user["can_automate"],
        "permissions": coerce_recovery_permissions(
            user["role"], user["can_automate"], user.get("permissions")
        ),
        "library_ids": sorted(str(g["library_id"]) for g in grants if g["user_id"] == user["id"]),
    }


def signature(user, grants):
    # The hash binds credential identity without exposing passwords in findings or receipts.
    # Provider subjects are included only after a link, so password-only reviews stay valid.
    payload = {
        "id": user["id"],
        "username": user["username"],
        "password_hash": user["password_hash"],
        **access_state(user, grants),
    }
    if user.get("oidc_subject"):
        payload["oidc_subject"] = user["oidc_subject"]
    if user.get("plex_user_id"):
        payload["plex_user_id"] = user["plex_user_id"]
    return digest(payload)


async def observe(inputs, writer):
    async with session_factory()() as db:
        history = list(
            await db.scalars(
                select(Operation)
                .where(
                    Operation.kind == KIND,
                    Operation.status == "completed",
                    Operation.payload["checkpoint_id"].astext == str(writer.checkpoint_id),
                )
                .order_by(Operation.created_at.desc(), Operation.id.desc())
                .limit(MAX_RECORDS + 1)
            )
        )
    if len(history) > MAX_RECORDS:
        raise ScanHeld("Too much access-review history; operator review is required")
    confirmations = {}
    for operation in history:
        for result in operation.payload.get("results", []):
            confirmations.setdefault(result["user_id"], result["access_digest"])
    integrations = {r["id"]: r for r in inputs["integrations"]}
    libraries = [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "accessible": bool(
                r["accessible"] and integrations.get(r["integration_id"], {}).get("enabled")
            ),
            "last_complete_sync": r["last_complete_sync"],
        }
        for r in inputs["libraries"]
    ]
    for user in inputs["users"]:
        confirmed = confirmations.get(str(user["id"])) == signature(user, inputs["library_grants"])
        await writer.add(
            "review",
            "access-reviewed" if confirmed else "access-ready",
            "Access · " + user["username"],
            "Current local permissions were reviewed; backend access and resume remain separate"
            if confirmed
            else "Review this account's role, automation privilege and library grants",
            entity_id=user["id"],
            evidence={
                "access_schema": 1,
                "user_id": str(user["id"]),
                "username": user["username"],
                "display_name": user["display_name"],
                "operator": user["id"] == writer.owner_id,
                "before": access_state(user, inputs["library_grants"]),
                "libraries": libraries,
            },
        )


async def require_inventory_review(db, checkpoint, scan, library_id):
    library = await db.get(Library, UUID(library_id))
    integration = await db.get(Integration, library.integration_id)
    reviewed = await db.scalar(
        select(Operation)
        .where(
            Operation.kind == reviews.INVENTORY_KIND,
            Operation.status == "completed",
            Operation.payload["checkpoint_id"].astext == str(checkpoint.id),
            Operation.payload["results"].contains(
                [{"integration_id": str(integration.id), "library_ids": [library_id]}]
            ),
        )
        .order_by(Operation.created_at.desc(), Operation.id.desc())
        .limit(1)
    )
    item = (
        next(
            (
                item
                for item in reviewed.payload["items"]
                if item["integration_id"] == str(integration.id)
            ),
            None,
        )
        if reviewed
        else None
    )
    finding = await db.scalar(
        select(RecoveryFinding).where(
            RecoveryFinding.scan_id == scan.id,
            RecoveryFinding.entity_id == integration.id,
            RecoveryFinding.domain == "library",
            RecoveryFinding.state == "inventory-ready",
        )
    )
    if (
        not item
        or not finding
        or item["connection_signature"] != reviews.connection_signature(integration)
        or finding.evidence.get("inventory_digest") != item["inventory_digest"]
    ):
        raise HTTPException(
            409, "Reconcile current backend inventory before adding a library grant"
        )


async def prepare(db, checkpoint, owner_id, scan_id, choices, key):
    changes = sorted(choices, key=lambda c: str(c.finding_id))
    old, scan, command = await reviews.review_inputs(
        db,
        checkpoint,
        owner_id,
        scan_id,
        [c.finding_id for c in changes],
        key,
        kind=KIND,
        extra_command={"changes": [c.model_dump(mode="json") for c in changes]},
    )
    if old:
        return old
    items, seen = [], set()
    for choice in changes:
        finding = await db.get(RecoveryFinding, choice.finding_id)
        if (
            not finding
            or finding.scan_id != scan.id
            or finding.domain != "review"
            or finding.state not in {"access-ready", "access-reviewed"}
            or finding.evidence.get("access_schema") != 1
            or not finding.entity_id
            or finding.entity_id in seen
        ):
            raise HTTPException(409, "Choose each account from the current access observation once")
        user = await db.get(User, finding.entity_id)
        if not user:
            raise HTTPException(409, "The account changed; observe again")
        if user.id == owner_id and (not choice.active or choice.role != "admin"):
            raise HTTPException(
                409, "Keep the designated recovery operator active as administrator"
            )
        evidence = finding.evidence
        available = {r["id"]: r for r in evidence["libraries"]}
        desired = sorted(str(i) for i in choice.library_ids)
        if any(i not in available for i in desired):
            raise HTTPException(409, "A selected library is no longer present")
        for identifier in set(desired) - set(evidence["before"]["library_ids"]):
            library = available[identifier]
            if (
                not library["accessible"]
                or not library["last_complete_sync"]
                or datetime.fromisoformat(library["last_complete_sync"]) < checkpoint.created_at
            ):
                raise HTTPException(
                    409, "Reconcile current backend inventory before adding a library grant"
                )
            await require_inventory_review(db, checkpoint, scan, identifier)
        from app.domain.permissions import coerce_recovery_permissions

        after = {
            "active": choice.active,
            "role": choice.role,
            "can_automate": choice.can_automate,
            "permissions": coerce_recovery_permissions(
                choice.role, choice.can_automate, choice.permissions
            ),
            "library_ids": desired,
        }
        seen.add(user.id)
        items.append(
            {
                "finding_id": str(finding.id),
                "finding_digest": reviews.finding_signature(finding),
                "user_id": str(user.id),
                "username": user.username,
                "operator": user.id == owner_id,
                "before": evidence["before"],
                "after": after,
                "libraries": [
                    {"id": i, "name": available[i]["name"]}
                    for i in sorted(set(desired) | set(evidence["before"]["library_ids"]))
                ],
            }
        )
    return await reviews.save_review(
        db,
        checkpoint,
        owner_id,
        scan,
        command,
        items,
        key,
        kind=KIND,
        message="Review the exact account permissions; acquisition and sign-in remain paused",
    )


async def read_current(identifier, token, payload):
    await reviews.pulse(identifier, token)
    return {item["finding_id"]: None for item in payload["items"]}


async def apply(db, review, item, unused):
    user_id = UUID(item["user_id"])
    user = await db.get(User, user_id, populate_existing=True, with_for_update=True)
    after = item["after"]
    if user_id == review.owner_id and (not after["active"] or after["role"] != "admin"):
        raise HTTPException(409, "The designated recovery operator must remain active")
    user.active, user.role, user.can_automate = (
        after["active"],
        after["role"],
        after["can_automate"],
    )
    user.permissions = after["permissions"]
    user.permission_role_id = None
    if item["before"]["library_ids"] != after["library_ids"]:
        await db.execute(delete(LibraryGrant).where(LibraryGrant.user_id == user_id))
        db.add_all(
            [LibraryGrant(user_id=user_id, library_id=UUID(i)) for i in after["library_ids"]]
        )
    changed = item["before"] != after
    if changed and user_id != review.owner_id:
        await db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
    await db.flush()
    grants = [{"user_id": user_id, "library_id": UUID(i)} for i in after["library_ids"]]
    current = {c.name: getattr(user, c.name) for c in User.__table__.columns}
    identity = await db.scalar(select(OidcIdentity).where(OidcIdentity.user_id == user_id))
    if identity:
        current["oidc_subject"] = identity.subject
    plex_identity = await db.scalar(select(PlexIdentity).where(PlexIdentity.user_id == user_id))
    if plex_identity:
        current["plex_user_id"] = plex_identity.plex_user_id
    result = {
        "user_id": str(user_id),
        "state": "reviewed",
        "changed": changed,
        "access_digest": signature(current, grants),
    }
    db.add(
        AuditEvent(
            actor_id=review.owner_id,
            action="recovery.access.reviewed",
            entity_id=user_id,
            detail={
                "review_id": str(review.id),
                "before": item["before"],
                "after": after,
                **result,
            },
        )
    )
    return result


async def run(identifier):
    await reviews.run_review(
        identifier,
        kind=KIND,
        read=read_current,
        apply=apply,
        message="Account permissions reviewed. Existing requests and files are preserved; "
        "automation remains paused.",
    )
