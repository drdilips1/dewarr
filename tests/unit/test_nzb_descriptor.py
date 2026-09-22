import pytest

from app.adapters.contracts import AdapterError
from app.adapters.nzb_descriptor import inspect_nzb
from tests.nzb_fixture import nzb_bytes


def test_named_nzb_keeps_one_folder_and_ignores_article_identity():
    raw = nzb_bytes()
    descriptor = inspect_nzb(raw)
    assert descriptor.name == "Example Book"
    assert descriptor.files[0].path == "Example Book/Example Book.m4b"
    assert descriptor.files[0].size_bytes == 4096
    assert descriptor.content_bytes == 4096
    assert descriptor.nzb_bytes == len(raw)
    assert "part@example" not in descriptor.model_dump_json()
    assert "hidden@" not in descriptor.model_dump_json()


def test_subject_paths_cannot_escape_the_release_folder():
    raw = nzb_bytes(subject='"../../secret.m4b" yEnc (1/1)')
    descriptor = inspect_nzb(raw)
    assert descriptor.files[0].path == "Example Book/secret.m4b"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not-an-nzb",
        b"<html></html>",
        b"<?xml version='1.0'?><nzb></nzb>",
        b" " * 20 + b"<x/>",
    ],
)
def test_invalid_nzb_is_rejected(raw):
    with pytest.raises(AdapterError, match="NZB"):
        inspect_nzb(raw)


def test_entity_expansion_is_rejected():
    raw = b"""<?xml version="1.0"?>
    <!DOCTYPE nzb [<!ENTITY x "y">]>
    <nzb>
      <file subject="&quot;book.m4b&quot;">
        <segments><segment bytes="1" number="1">&x;</segment></segments>
      </file>
    </nzb>
    """
    with pytest.raises(AdapterError, match="NZB"):
        inspect_nzb(raw)
