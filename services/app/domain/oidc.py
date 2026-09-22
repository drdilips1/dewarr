"""One confidential OpenID Connect client for Authentik, Pocket ID, and Authelia."""

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from joserfc import jwk, jwt
from joserfc.errors import JoseError
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db.models import AuditEvent, OidcIdentity, OidcProvider, User
from app.security import decrypt_secrets

USERNAME = re.compile(r"^[a-z0-9_.@-]{3,100}$")
CLAIM_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
SCOPE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._~-]{0,79}$")
PUBLIC_JWK_FIELDS = {"kty", "kid", "use", "alg", "n", "e", "crv", "x", "y"}
MAX_BODY = 1_000_000


class OidcRejected(Exception):
    def __init__(self, code: str):
        self.code = code


@dataclass(frozen=True)
class Provider:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    jwks_uri: str
    client_id: str
    client_secret: str
    signing_algorithm: str
    match_existing: str
    auto_register: bool
    default_role: str
    group_claim: str
    group_scope: str
    admin_group: str
    member_group: str
    viewer_group: str
    label: str


def allowed_scheme() -> str:
    return "http" if urlsplit(get_settings().public_url).scheme == "http" else "https"


def redirect_uri() -> str:
    return get_settings().public_url + "/api/auth/oidc/callback"


def _issuer_socket(value: str) -> tuple[str, str, int] | None:
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host:
        return None
    port = parts.port
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return (parts.scheme, host, port)


def same_provider_host(left: str, right: str) -> bool:
    left_socket = _issuer_socket(left)
    return left_socket is not None and left_socket == _issuer_socket(right)


def normalize_issuer(value: str, *, scheme: str | None = None) -> str:
    scheme = scheme or allowed_scheme()
    cleaned = value.strip()
    if not cleaned or any(char in cleaned for char in " \t\r\n\\"):
        raise ValueError("Use the issuer URL from the identity provider")
    parts = urlsplit(cleaned)
    if (
        parts.scheme != scheme
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or ".." in parts.path.split("/")
    ):
        raise ValueError("Use the issuer URL from the identity provider")
    path = parts.path.rstrip("/")
    issuer = urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")
    if len(issuer) > 300:
        raise ValueError("Use the issuer URL from the identity provider")
    return issuer


def same_origin(url: str, issuer: str) -> bool:
    if not isinstance(url, str) or any(char in url for char in " \t\r\n\\"):
        return False
    endpoint, root = urlsplit(url), urlsplit(issuer)
    return (
        endpoint.scheme == root.scheme
        and endpoint.hostname == root.hostname
        and endpoint.port == root.port
        and not endpoint.username
        and not endpoint.password
        and not endpoint.query
        and not endpoint.fragment
        and ".." not in endpoint.path.split("/")
    )


def endpoint(value: str, issuer: str) -> str:
    if not same_origin(value, issuer):
        raise ValueError("Provider endpoints must stay on the issuer address")
    return value


def snapshot(row: OidcProvider | None) -> Provider | None:
    if (
        not row
        or not row.enabled
        or not row.encrypted_secret
        or not row.issuer
        or not row.client_id
        or not all(
            (
                row.authorization_endpoint,
                row.token_endpoint,
                row.userinfo_endpoint,
                row.jwks_uri,
            )
        )
    ):
        return None
    secret = decrypt_secrets(row.encrypted_secret).get("client_secret")
    if not isinstance(secret, str) or not secret:
        return None
    return Provider(
        issuer=row.issuer,
        authorization_endpoint=row.authorization_endpoint,
        token_endpoint=row.token_endpoint,
        userinfo_endpoint=row.userinfo_endpoint,
        jwks_uri=row.jwks_uri,
        client_id=row.client_id,
        client_secret=secret,
        signing_algorithm=row.signing_algorithm,
        match_existing=row.match_existing,
        auto_register=row.auto_register,
        default_role=row.default_role,
        group_claim=row.group_claim,
        group_scope=row.group_scope,
        admin_group=row.admin_group,
        member_group=row.member_group,
        viewer_group=row.viewer_group,
        label=row.label,
    )


def authorization_url(provider: Provider, *, state: str, nonce: str, verifier: str) -> str:
    scopes = "openid profile email"
    if provider.group_scope:
        scopes += " " + provider.group_scope
    query = urlencode(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri(),
            "scope": scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": create_s256_code_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in provider.authorization_endpoint else "?"
    return provider.authorization_endpoint + separator + query


def same_secret(left: object, right: object) -> bool:
    if not isinstance(left, str) or not isinstance(right, str) or len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


async def fetch_json(
    method: str,
    url: str,
    *,
    origin: str,
    data: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not same_origin(url, origin):
        raise OidcRejected("rejected")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.request(method, url, data=data, auth=auth, headers=headers)
    except httpx.HTTPError:
        raise OidcRejected("unavailable") from None
    if response.is_redirect or response.status_code >= 500 or response.status_code == 429:
        raise OidcRejected("unavailable")
    if response.status_code >= 400 or len(response.content) > MAX_BODY:
        raise OidcRejected("rejected" if response.status_code < 500 else "unavailable")
    try:
        body = response.json()
    except ValueError:
        raise OidcRejected("unavailable") from None
    if not isinstance(body, dict):
        raise OidcRejected("unavailable")
    return body


async def discover(issuer: str) -> dict[str, str]:
    root = normalize_issuer(issuer)
    document = await fetch_json("GET", root + "/.well-known/openid-configuration", origin=root)
    announced = document.get("issuer")
    if not isinstance(announced, str) or announced.rstrip("/") != root:
        raise OidcRejected("rejected")
    found = {"issuer": root}
    for name in (
        "authorization_endpoint",
        "token_endpoint",
        "userinfo_endpoint",
        "jwks_uri",
    ):
        value = document.get(name)
        if not isinstance(value, str) or not same_origin(value, root):
            raise OidcRejected("rejected")
        found[name] = value
    algorithms = document.get("id_token_signing_alg_values_supported") or ["RS256"]
    if not isinstance(algorithms, list):
        raise OidcRejected("rejected")
    if "RS256" in algorithms:
        found["signing_algorithm"] = "RS256"
    elif "ES256" in algorithms:
        found["signing_algorithm"] = "ES256"
    else:
        raise OidcRejected("rejected")
    return found


def public_jwks(document: dict[str, Any]) -> dict[str, list]:
    keys = document.get("keys")
    if not isinstance(keys, list) or not keys:
        raise OidcRejected("rejected")
    public = []
    for key in keys:
        if not isinstance(key, dict) or key.get("kty") not in {"RSA", "EC"}:
            continue
        if any(part in key for part in ("d", "k", "p", "q")):
            continue
        public.append({name: key[name] for name in PUBLIC_JWK_FIELDS if name in key})
    if not public:
        raise OidcRejected("rejected")
    return {"keys": public}


def unverified(value: object) -> bool:
    if value is False or value == 0:
        return True
    return isinstance(value, str) and value.strip().lower() in {"false", "0"}


def email_is_verified(claims: dict[str, Any]) -> bool:
    value = claims.get("email_verified")
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() == "true"


async def identity_claims(
    provider: Provider, *, code: str, verifier: str, nonce: str
) -> dict[str, Any]:
    token = await fetch_json(
        "POST",
        provider.token_endpoint,
        origin=provider.issuer,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
            "code_verifier": verifier,
        },
        auth=(provider.client_id, provider.client_secret),
    )
    id_token, access_token = token.get("id_token"), token.get("access_token")
    if not isinstance(id_token, str) or not isinstance(access_token, str):
        raise OidcRejected("rejected")
    jwks = public_jwks(await fetch_json("GET", provider.jwks_uri, origin=provider.issuer))
    try:
        decoded = jwt.decode(
            id_token, jwk.KeySet.import_key_set(jwks), algorithms=[provider.signing_algorithm]
        )
        jwt.JWTClaimsRegistry(
            leeway=60,
            iss={"essential": True, "value": provider.issuer},
            aud={"essential": True, "value": provider.client_id},
            exp={"essential": True},
            iat={"essential": True},
            nonce={"essential": True, "value": nonce},
            sub={"essential": True},
        ).validate(decoded.claims)
    except (JoseError, ValueError):
        raise OidcRejected("rejected") from None
    claims = dict(decoded.claims)
    audience = claims.get("aud")
    if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != provider.client_id:
        raise OidcRejected("rejected")
    userinfo = await fetch_json(
        "GET",
        provider.userinfo_endpoint,
        origin=provider.issuer,
        headers={"Authorization": "Bearer " + access_token},
    )
    if unverified(claims.get("email_verified")) or unverified(userinfo.get("email_verified")):
        raise OidcRejected("rejected")
    merged = merge_identity(claims, userinfo)
    subject = merged.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 300:
        raise OidcRejected("rejected")
    return merged


def merge_identity(claims: dict[str, Any], userinfo: dict[str, Any]) -> dict[str, Any]:
    subject = claims.get("sub")
    if not isinstance(userinfo.get("sub"), str) or userinfo.get("sub") != subject:
        raise OidcRejected("rejected")
    token_email, info_email = email_of(claims), email_of(userinfo)
    if token_email and info_email and token_email != info_email:
        raise OidcRejected("rejected")
    merged = dict(userinfo)
    merged.update({key: value for key, value in claims.items() if value is not None})
    email = email_of(merged)
    sources = []
    if token_email and token_email == email:
        sources.append(claims)
    if info_email and info_email == email:
        sources.append(userinfo)
    if not any(source.get("email_verified") is not None for source in sources):
        merged.pop("email_verified", None)
    return merged


def email_of(claims: dict[str, Any]) -> str | None:
    value = claims.get("email")
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if "@" not in value or len(value) > 254:
        return None
    return value


def exact_username(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if USERNAME.fullmatch(value) else None


def sanitize_username(preferred: object, subject: str) -> str:
    raw = preferred.strip().lower() if isinstance(preferred, str) else ""
    cleaned = re.sub(r"[^a-z0-9_.@-]", "", raw)
    if len(cleaned) < 3:
        cleaned = "reader-" + hashlib.sha256(subject.encode()).hexdigest()[:8]
    return cleaned[:100]


def display_name(claims: dict[str, Any], username: str) -> str:
    value = claims.get("name")
    text_value = value if isinstance(value, str) and value.strip() else username
    return " ".join(text_value.split())[:120] or username


def role_from_groups(
    groups: object,
    *,
    admin_group: str,
    member_group: str,
    viewer_group: str,
    default: str,
) -> str:
    values = groups if isinstance(groups, list) else [groups]
    names = {item for item in values if isinstance(item, str) and item}
    if admin_group and admin_group in names:
        return "admin"
    if member_group and member_group in names:
        return "member"
    if viewer_group and viewer_group in names:
        return "viewer"
    return default


async def _remember_email(db, user: User, email: str | None) -> None:
    if not email or user.email:
        return
    taken = await db.scalar(select(User.id).where(User.email == email, User.id != user.id))
    if not taken:
        user.email = email


async def _sync_role(db, user: User, provider: Provider, claims: dict[str, Any]) -> None:
    # Provider groups do not change an account that still has a local password.
    if not provider.group_claim or user.password_hash:
        return
    role = role_from_groups(
        claims.get(provider.group_claim),
        admin_group=provider.admin_group,
        member_group=provider.member_group,
        viewer_group=provider.viewer_group,
        default=provider.default_role,
    )
    if user.role == "admin" and role != "admin":
        others = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.active.is_(True), User.id != user.id)
        )
        if not others:
            return
    user.role = role
    if role == "viewer":
        user.can_automate = False


async def _match_existing(db, provider: Provider, claims: dict[str, Any]) -> User | None:
    if provider.match_existing == "email":
        email = email_of(claims) if email_is_verified(claims) else None
        if not email:
            return None
        found = await db.scalar(select(User).where(User.email == email))
        if found:
            return found
        return await db.scalar(select(User).where(User.username == email, User.email.is_(None)))
    if provider.match_existing == "username":
        username = exact_username(claims.get("preferred_username") or claims.get("username"))
        if not username:
            return None
        found = await db.scalar(select(User).where(User.username == username))
        if found is not None and found.role == "admin":
            raise OidcRejected("rejected")
        return found
    return None


async def _unused_username(db, preferred: object, subject: str) -> str:
    base = sanitize_username(preferred, subject)
    candidate = base
    for count in range(2, 51):
        if not await db.scalar(select(User.id).where(User.username == candidate)):
            return candidate
        suffix = f"-{count}"
        candidate = base[: 100 - len(suffix)] + suffix
    raise OidcRejected("rejected")


async def resolve_user(db, provider: Provider, claims: dict[str, Any]) -> User:
    subject = claims["sub"]
    email = email_of(claims) if email_is_verified(claims) else None
    await db.execute(text("SELECT pg_advisory_xact_lock(720002)"))
    await db.execute(text("SELECT pg_advisory_xact_lock(720003)"))
    identity = await db.scalar(
        select(OidcIdentity).where(
            OidcIdentity.issuer == provider.issuer, OidcIdentity.subject == subject
        )
    )
    if identity:
        user = await db.get(User, identity.user_id)
        if not user or not user.active:
            raise OidcRejected("rejected")
        await _remember_email(db, user, email)
        await _sync_role(db, user, provider, claims)
        return user
    matched = await _match_existing(db, provider, claims)
    if matched:
        if not matched.active:
            raise OidcRejected("rejected")
        linked = await db.scalar(select(OidcIdentity).where(OidcIdentity.user_id == matched.id))
        if linked:
            raise OidcRejected("rejected")
        db.add(OidcIdentity(user_id=matched.id, issuer=provider.issuer, subject=subject))
        await _remember_email(db, matched, email)
        db.add(
            AuditEvent(
                actor_id=matched.id,
                action="oidc.linked",
                entity_id=matched.id,
                detail={"issuer": provider.issuer},
            )
        )
        await _sync_role(db, matched, provider, claims)
        return matched
    if not provider.auto_register:
        raise OidcRejected("rejected")
    username = await _unused_username(db, claims.get("preferred_username"), subject)
    user = User(
        username=username,
        display_name=display_name(claims, username),
        password_hash=None,
        email=email,
        role=provider.default_role,
        can_automate=False,
    )
    db.add(user)
    await db.flush()
    if email:
        taken = await db.scalar(select(User.id).where(User.email == email, User.id != user.id))
        if taken:
            user.email = None
    db.add(OidcIdentity(user_id=user.id, issuer=provider.issuer, subject=subject))
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="oidc.registered",
            entity_id=user.id,
            detail={"issuer": provider.issuer},
        )
    )
    await _sync_role(db, user, provider, claims)
    return user
