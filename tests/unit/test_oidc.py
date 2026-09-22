from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.api.dependencies import client_host
from app.config import get_settings
from app.domain.oidc import (
    OidcRejected,
    Provider,
    authorization_url,
    email_is_verified,
    exact_username,
    merge_identity,
    normalize_issuer,
    role_from_groups,
    same_origin,
    same_provider_host,
    sanitize_username,
    unverified,
)
from app.domain.recovery_access import signature


def test_signature_changes_only_after_an_oidc_link():
    user = {
        "id": "user",
        "username": "admin",
        "password_hash": "hash",
        "active": True,
        "role": "admin",
        "can_automate": True,
    }
    plain = signature(user, [])
    assert plain == signature({**user, "email": None}, [])
    assert plain != signature({**user, "oidc_subject": "subject-1"}, [])


def test_issuer_stays_on_one_origin():
    issuer = normalize_issuer("http://id.example/application/o/dewarr/", scheme="http")
    assert issuer == "http://id.example/application/o/dewarr"
    assert same_origin("http://id.example/application/o/dewarr/token", issuer)
    for value in (
        "https://id.example",
        "http://user:pass@id.example",
        "http://id.example/../admin",
        "javascript:alert(1)",
    ):
        try:
            normalize_issuer(value, scheme="http")
        except ValueError:
            continue
        raise AssertionError(value)
    assert not same_origin("http://evil.example/token", issuer)


def test_group_mapping_prefers_administrator():
    assert (
        role_from_groups(
            ["readers", "admins"],
            admin_group="admins",
            member_group="readers",
            viewer_group="guests",
            default="member",
        )
        == "admin"
    )
    assert (
        role_from_groups(
            "guests",
            admin_group="admins",
            member_group="readers",
            viewer_group="guests",
            default="member",
        )
        == "viewer"
    )
    assert (
        role_from_groups(
            [],
            admin_group="",
            member_group="",
            viewer_group="",
            default="member",
        )
        == "member"
    )


def test_only_an_explicit_true_verifies_email():
    assert email_is_verified({"email_verified": True})
    assert email_is_verified({"email_verified": "true"})
    assert not email_is_verified({})
    assert not email_is_verified({"email_verified": False})
    assert not email_is_verified({"email_verified": "false"})
    assert unverified(False)
    assert unverified("False")
    assert unverified(0)
    assert not unverified(None)
    assert not unverified(True)


def _provider(**overrides):
    values = {
        "issuer": "https://id.example",
        "authorization_endpoint": "https://id.example/authorize",
        "token_endpoint": "https://id.example/token",
        "userinfo_endpoint": "https://id.example/userinfo",
        "jwks_uri": "https://id.example/jwks",
        "client_id": "dewarr",
        "client_secret": "secret",
        "signing_algorithm": "RS256",
        "match_existing": "off",
        "auto_register": False,
        "default_role": "member",
        "group_claim": "",
        "group_scope": "",
        "admin_group": "",
        "member_group": "",
        "viewer_group": "",
        "label": "Pocket ID",
    }
    values.update(overrides)
    return Provider(**values)


def _scope(provider):
    url = authorization_url(provider, state="state", nonce="nonce", verifier="verifier-value")
    return parse_qs(urlsplit(url).query)["scope"][0]


def test_group_scope_is_requested_only_when_set():
    assert _scope(_provider(group_claim="groups")) == "openid profile email"
    assert _scope(_provider(group_scope="groups")) == "openid profile email groups"


def test_userinfo_verification_stays_with_its_email():
    verified = merge_identity(
        {"sub": "user", "email": "person@example.com"},
        {"sub": "user", "email": "person@example.com", "email_verified": True},
    )
    assert verified["email_verified"] is True
    unrelated = merge_identity(
        {"sub": "user", "email": "person@example.com"},
        {"sub": "user", "email_verified": True},
    )
    assert "email_verified" not in unrelated
    with pytest.raises(OidcRejected):
        merge_identity({"sub": "user"}, {"email_verified": True, "groups": ["admins"]})
    with pytest.raises(OidcRejected):
        merge_identity(
            {"sub": "user", "email": "a@example.com"},
            {"sub": "user", "email": "b@example.com", "email_verified": True},
        )


def test_provider_links_follow_the_socket():
    assert same_provider_host(
        "https://id.example/application/o/dewarr", "https://ID.Example:443/realms/dewarr"
    )
    assert not same_provider_host(
        "https://id.example/application/o/dewarr", "http://id.example:8443/realms/other"
    )
    assert not same_provider_host("https://id.example", "http://id.example")
    assert not same_provider_host("http://id.example", "http://other.example")
    assert not same_provider_host("", "http://id.example")


class _Headers:
    def __init__(self, **headers):
        self._headers = headers

    def get(self, name, default=""):
        values = self._headers.get(name, [])
        if isinstance(values, str):
            return values or default
        return values[0] if values else default

    def getlist(self, name):
        values = self._headers.get(name, [])
        if isinstance(values, str):
            return [values] if values else []
        return list(values)


def _request(host, forwarded="", real="", token=""):
    return SimpleNamespace(
        client=SimpleNamespace(host=host),
        headers=_Headers(
            **{
                "x-forwarded-for": forwarded,
                "x-real-ip": real,
                "x-dewarr-proxy-token": token,
            }
        ),
    )


def test_forwarded_client_requires_the_proxy_token(monkeypatch):
    monkeypatch.delenv("BOOK_PROXY_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        assert client_host(_request("10.0.0.2", forwarded="1.1.1.1", token="secret")) == "10.0.0.2"
        monkeypatch.setenv("BOOK_PROXY_TOKEN", "secret")
        get_settings.cache_clear()
        assert (
            client_host(_request("10.0.0.2", forwarded="198.51.100.4, 1.1.1.1", token="secret"))
            == "1.1.1.1"
        )
        agreed = _request(
            "10.0.0.2", forwarded="198.51.100.4, 1.1.1.1", real="1.1.1.1", token="secret"
        )
        assert client_host(agreed) == "1.1.1.1"
        assert (
            client_host(_request("10.0.0.2", forwarded="1.1.1.1", real="8.8.8.8", token="secret"))
            == "10.0.0.2"
        )
        assert client_host(_request("10.0.0.2", real="8.8.8.8", token="secret")) == "8.8.8.8"
        repeated = _request(
            "10.0.0.2",
            forwarded=["1.2.3.4", "198.51.100.4, 8.8.8.8"],
            real=["1.2.3.4", "8.8.8.8"],
            token=["wrong", "secret"],
        )
        assert client_host(repeated) == "8.8.8.8"
        appended = _request(
            "10.0.0.2",
            forwarded=["1.2.3.4", "8.8.8.8"],
            real="1.2.3.4",
            token="secret",
        )
        assert client_host(appended) == "10.0.0.2"
        assert client_host(_request("1.1.1.1", forwarded="8.8.8.8", token="secret")) == "8.8.8.8"
        assert client_host(_request("10.0.0.2", forwarded="1.1.1.1", token="nope")) == "10.0.0.2"
        assert (
            client_host(_request("10.0.0.2", forwarded="not-an-ip", token="secret")) == "10.0.0.2"
        )
    finally:
        get_settings.cache_clear()


def test_usernames_are_normalized():
    assert exact_username("Reader") == "reader"
    assert exact_username("no") is None
    assert sanitize_username("Ada Lovelace", "subject") == "adalovelace"
    assert sanitize_username("a", "subject").startswith("reader-")
