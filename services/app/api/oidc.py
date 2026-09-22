import logging
import secrets

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from app.api.auth import FINISH, enforce_auth_budget, start_session, write_handoff
from app.api.dependencies import Admin, Database, client_host
from app.config import get_settings
from app.db.models import OidcIdentity, OidcProvider
from app.domain.oidc import (
    CLAIM_NAME,
    SCOPE_NAME,
    OidcRejected,
    authorization_url,
    discover,
    endpoint,
    identity_claims,
    normalize_issuer,
    redirect_uri,
    resolve_user,
    same_provider_host,
    same_secret,
    snapshot,
)
from app.security import decrypt_secrets, encrypt_secrets, token_hash

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)
OIDC_COOKIE = "book_oidc"
OIDC_PATH = "/api/auth/oidc"
ERRORS = {
    "denied": "Your identity provider did not sign you in.",
    "mismatch": "That sign-in attempt expired. Try again.",
    "rejected": "This account cannot sign in with the identity provider.",
    "unavailable": "The identity provider could not be reached.",
    "paused": "Sign-in is paused during recovery review.",
    "limited": "Too many sign-in attempts. Try again in ten minutes.",
}


class OidcPublicView(BaseModel):
    enabled: bool
    label: str | None = None


class OidcSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    label: str = Field(default="your identity provider", min_length=1, max_length=80)
    issuer: str = Field(default="", max_length=300)
    authorization_endpoint: str = Field(default="", max_length=500)
    token_endpoint: str = Field(default="", max_length=500)
    userinfo_endpoint: str = Field(default="", max_length=500)
    jwks_uri: str = Field(default="", max_length=500)
    client_id: str = Field(default="", max_length=200)
    client_secret: SecretStr | None = None
    signing_algorithm: str = "RS256"
    match_existing: str = "off"
    auto_register: bool = False
    default_role: str = "member"
    group_claim: str = Field(default="", max_length=80)
    group_scope: str = Field(default="", max_length=80)
    admin_group: str = Field(default="", max_length=120)
    member_group: str = Field(default="", max_length=120)
    viewer_group: str = Field(default="", max_length=120)

    @field_validator("client_secret", mode="before")
    @classmethod
    def blank_secret(cls, value):
        if value == "":
            return None
        return value

    @field_validator("label", "admin_group", "member_group", "viewer_group")
    @classmethod
    def trim(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("client_secret")
    @classmethod
    def secret_length(cls, value: SecretStr | None):
        if value is not None and not 8 <= len(value.get_secret_value()) <= 500:
            raise ValueError("Use the client secret from the identity provider")
        return value


class OidcSettingsView(BaseModel):
    enabled: bool
    label: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    jwks_uri: str
    client_id: str
    signing_algorithm: str
    match_existing: str
    auto_register: bool
    default_role: str
    group_claim: str
    group_scope: str
    admin_group: str
    member_group: str
    viewer_group: str
    secret_set: bool
    redirect_uri: str


class DiscoverInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str = Field(min_length=1, max_length=300)


class DiscoveryView(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    jwks_uri: str
    signing_algorithm: str


def settings_view(row: OidcProvider | None) -> OidcSettingsView:
    return OidcSettingsView(
        enabled=bool(row and row.enabled),
        label=row.label if row else "your identity provider",
        issuer=row.issuer if row else "",
        authorization_endpoint=row.authorization_endpoint if row else "",
        token_endpoint=row.token_endpoint if row else "",
        userinfo_endpoint=row.userinfo_endpoint if row else "",
        jwks_uri=row.jwks_uri if row else "",
        client_id=row.client_id if row else "",
        signing_algorithm=row.signing_algorithm if row else "RS256",
        match_existing=row.match_existing if row else "off",
        auto_register=bool(row and row.auto_register),
        default_role=row.default_role if row else "member",
        group_claim=row.group_claim if row else "",
        group_scope=row.group_scope if row else "",
        admin_group=row.admin_group if row else "",
        member_group=row.member_group if row else "",
        viewer_group=row.viewer_group if row else "",
        secret_set=bool(row and row.encrypted_secret),
        redirect_uri=redirect_uri(),
    )


def validate_settings(body: OidcSettingsInput) -> str:
    if body.signing_algorithm not in {"RS256", "ES256"}:
        raise HTTPException(422, "Choose RS256 or ES256")
    if body.match_existing not in {"off", "email", "username"}:
        raise HTTPException(422, "Choose how existing accounts are matched")
    if body.default_role not in {"member", "viewer"}:
        raise HTTPException(422, "New accounts start as members or viewers")
    if body.group_claim and not CLAIM_NAME.fullmatch(body.group_claim):
        raise HTTPException(422, "Use a group claim name such as groups")
    if body.group_scope and not SCOPE_NAME.fullmatch(body.group_scope):
        raise HTTPException(422, "Use a group scope such as groups")
    if ":" in body.client_id:
        raise HTTPException(422, "Use the client ID from the identity provider")
    try:
        issuer = normalize_issuer(body.issuer) if body.issuer else ""
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    endpoints = {
        "authorization_endpoint": body.authorization_endpoint,
        "token_endpoint": body.token_endpoint,
        "userinfo_endpoint": body.userinfo_endpoint,
        "jwks_uri": body.jwks_uri,
    }
    if body.enabled and (
        not issuer or not body.client_id or any(not value for value in endpoints.values())
    ):
        raise HTTPException(422, "Discover the provider and enter its client ID before enabling")
    if any(endpoints.values()) and not issuer:
        raise HTTPException(422, "Enter the issuer URL before its endpoints")
    if issuer:
        try:
            for value in endpoints.values():
                if value:
                    endpoint(value, issuer)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
    return issuer


def client_address(request: Request) -> str:
    return token_hash(client_host(request))


def clear_transaction(response: RedirectResponse) -> None:
    response.delete_cookie(
        OIDC_COOKIE, path=OIDC_PATH, secure=get_settings().cookie_secure, samesite="lax"
    )


def fail(code: str) -> RedirectResponse:
    response = RedirectResponse(f"/?oidc_error={code}", status_code=303)
    clear_transaction(response)
    logger.info("OIDC sign-in did not complete (%s)", code)
    return response


def read_transaction(request: Request) -> dict | None:
    raw = request.cookies.get(OIDC_COOKIE)
    if not raw:
        return None
    try:
        payload = decrypt_secrets(raw)
    except (InvalidToken, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


async def provider_row(db: Database) -> OidcProvider | None:
    return await db.get(OidcProvider, 1)


@router.get("/oidc", response_model=OidcPublicView, response_model_exclude_none=True)
async def oidc_status(db: Database) -> OidcPublicView:
    row = await provider_row(db)
    ready = snapshot(row)
    if not ready:
        return OidcPublicView(enabled=False)
    return OidcPublicView(enabled=True, label=ready.label)


@router.get("/oidc/settings", response_model=OidcSettingsView)
async def oidc_settings(admin: Admin, db: Database) -> OidcSettingsView:
    return settings_view(await provider_row(db))


@router.put("/oidc/settings", response_model=OidcSettingsView)
async def save_oidc_settings(body: OidcSettingsInput, admin: Admin, db: Database):
    issuer = validate_settings(body)
    row = await provider_row(db)
    if body.enabled and body.client_secret is None and not (row and row.encrypted_secret):
        raise HTTPException(422, "A client secret is required")
    if row is not None and row.issuer and issuer and row.issuer != issuer:
        identities = OidcIdentity.issuer == row.issuer
        if same_provider_host(row.issuer, issuer):
            await db.execute(update(OidcIdentity).where(identities).values(issuer=issuer))
        else:
            await db.execute(delete(OidcIdentity).where(identities))
    if row is None:
        row = OidcProvider(id=1)
        db.add(row)
    row.enabled = body.enabled
    row.label = body.label
    row.issuer = issuer
    row.authorization_endpoint = body.authorization_endpoint
    row.token_endpoint = body.token_endpoint
    row.userinfo_endpoint = body.userinfo_endpoint
    row.jwks_uri = body.jwks_uri
    row.client_id = body.client_id
    row.signing_algorithm = body.signing_algorithm
    row.match_existing = body.match_existing
    row.auto_register = body.auto_register
    row.default_role = body.default_role
    row.group_claim = body.group_claim
    row.group_scope = body.group_scope
    row.admin_group = body.admin_group
    row.member_group = body.member_group
    row.viewer_group = body.viewer_group
    if body.client_secret is not None:
        row.encrypted_secret = encrypt_secrets(
            {"client_secret": body.client_secret.get_secret_value()}
        )
    await db.commit()
    return settings_view(row)


@router.post("/oidc/discover", response_model=DiscoveryView)
async def discover_provider(body: DiscoverInput, admin: Admin, db: Database):
    await enforce_auth_budget(db, "oidc-discover")
    try:
        found = await discover(body.issuer)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except OidcRejected as error:
        raise HTTPException(
            422 if error.code == "rejected" else 502, ERRORS.get(error.code, ERRORS["unavailable"])
        ) from None
    return found


@router.get("/oidc/start")
async def start(request: Request, db: Database):
    try:
        await enforce_auth_budget(db, "oidc-start:" + client_address(request))
    except HTTPException as error:
        if error.status_code == 429:
            return fail("limited")
        raise
    row = await provider_row(db)
    provider = snapshot(row)
    await db.rollback()
    if not provider:
        raise HTTPException(404, "Identity provider sign-in is not enabled")
    verifier = secrets.token_urlsafe(64)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    response = RedirectResponse(
        authorization_url(provider, state=state, nonce=nonce, verifier=verifier), status_code=302
    )
    response.set_cookie(
        OIDC_COOKIE,
        encrypt_secrets({"state": state, "nonce": nonce, "verifier": verifier}),
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=600,
        path=OIDC_PATH,
    )
    return response


@router.get("/oidc/callback")
async def callback(request: Request, db: Database):
    try:
        await enforce_auth_budget(db, "oidc-callback:" + client_address(request))
    except HTTPException as error:
        if error.status_code == 429:
            return fail("limited")
        raise
    if request.query_params.get("error"):
        return fail("denied")
    saved = read_transaction(request)
    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    if (
        not saved
        or len(state) > 200
        or not same_secret(saved.get("state"), state)
        or not isinstance(saved.get("nonce"), str)
        or not isinstance(saved.get("verifier"), str)
        or not code
        or len(code) > 2048
    ):
        return fail("mismatch")
    provider = snapshot(await provider_row(db))
    await db.rollback()
    if not provider:
        return fail("denied")
    try:
        claims = await identity_claims(
            provider, code=code, verifier=saved["verifier"], nonce=saved["nonce"]
        )
        user = await resolve_user(db, provider, claims)
    except OidcRejected as error:
        await db.rollback()
        return fail(error.code if error.code in ERRORS else "rejected")
    except IntegrityError:
        await db.rollback()
        return fail("rejected")
    try:
        token = await start_session(user, db)
    except HTTPException as error:
        if error.status_code == 423:
            return fail("paused")
        raise
    response = RedirectResponse(FINISH, status_code=303)
    clear_transaction(response)
    write_handoff(response, token)
    return response
