import pytest
from pydantic import ValidationError

from app.config import Settings


def test_extra_browser_addresses_are_allowed_alongside_the_public_url():
    settings = Settings(
        public_url="http://100.93.52.89:8000",
        extra_origins=" http://192.168.31.98:8000/ , http://localhost:8000",
    )
    assert settings.allowed_origins == {
        "http://100.93.52.89:8000",
        "http://192.168.31.98:8000",
        "http://localhost:8000",
    }
    assert Settings(public_url="http://localhost:8000").allowed_origins == {"http://localhost:8000"}


@pytest.mark.parametrize("value", ["192.168.31.98:8000", "http://host:8000/path", "ftp://host"])
def test_extra_addresses_must_be_plain_http_origins(value):
    with pytest.raises(ValidationError):
        Settings(extra_origins=value)
