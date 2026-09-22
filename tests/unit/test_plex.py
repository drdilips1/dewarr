from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from app.config import Settings, get_settings
from app.domain.plex import PICKER_LIMIT, servers_from
from app.domain.recovery_access import signature


def test_signature_changes_only_after_a_plex_link():
    user = {
        "id": "user",
        "username": "admin",
        "password_hash": "hash",
        "active": True,
        "role": "admin",
        "can_automate": True,
    }
    plain = signature(user, [])
    assert plain == signature({**user, "plex_user_id": ""}, [])
    assert plain != signature({**user, "plex_user_id": "42"}, [])


def test_servers_keep_media_servers_only():
    servers = servers_from(
        [
            {
                "name": "Home",
                "provides": "server",
                "clientIdentifier": "abcdef1234",
                "accessToken": "secret",
            },
            {"name": "Player", "provides": "player", "clientIdentifier": "abcdef1234"},
            {"name": "Bad", "provides": "server", "clientIdentifier": "../etc"},
            {
                "name": "  Shared shelf  ",
                "provides": "server,player",
                "clientIdentifier": "shared1234",
            },
        ]
    )
    assert servers == [
        {"name": "Home", "machine_id": "abcdef1234"},
        {"name": "Shared shelf", "machine_id": "shared1234"},
    ]
    assert "secret" not in str(servers)


def test_owned_servers_stay_available_past_the_picker():
    shared = [
        {
            "name": f"Share {index}",
            "provides": "server",
            "clientIdentifier": f"share{index:04d}xx",
            "owned": False,
        }
        for index in range(31)
    ]
    servers = servers_from(
        shared
        + [{"name": "Home", "provides": "server", "clientIdentifier": "abcdef1234", "owned": True}]
    )
    assert servers[0] == {"name": "Home", "machine_id": "abcdef1234"}
    assert len(servers) == 32
    assert servers[-1]["machine_id"] == "share0030xx"
    assert len(servers[:PICKER_LIMIT]) == PICKER_LIMIT
    assert servers[:PICKER_LIMIT][0]["machine_id"] == "abcdef1234"


def test_https_site_rejects_an_http_plex_origin(monkeypatch):
    monkeypatch.setenv("BOOK_PUBLIC_URL", "https://books.example")
    monkeypatch.setenv("BOOK_PLEX_API_ORIGIN", "http://plex.example")
    monkeypatch.setenv("BOOK_SECRET_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    try:
        try:
            Settings()
        except ValidationError:
            return
        raise AssertionError("http Plex origin was accepted")
    finally:
        get_settings.cache_clear()


def test_settings_accept_explicit_https_plex_origins():
    settings = Settings.model_validate(
        {
            "public_url": "https://books.example",
            "secret_key": SecretStr(Fernet.generate_key().decode()),
            "plex_api_origin": "https://plex.tv",
            "plex_auth_origin": "https://app.plex.tv",
        }
    )
    assert settings.plex_api_origin == "https://plex.tv"
