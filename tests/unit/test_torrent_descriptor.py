import asyncio
import hashlib
import sys
import warnings

import libtorrent as lt
import pytest

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.torrent_descriptor import inspect_torrent
from tests.torrent_fixture import torrent_bytes


async def test_private_series_metadata_yields_identity_and_files_without_tracker_credentials():
    raw = torrent_bytes()
    result = await inspect_torrent(raw)
    assert result.infohash_v1 == hashlib.sha1(lt.bencode(lt.bdecode(raw)[b"info"])).hexdigest()
    assert result.infohash_v2 is None and result.private
    assert result.artifact_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.content_bytes == 24 and result.padding_bytes == 0
    assert [file.path for file in result.files] == [
        "Harbor Stories/01 - Harbor.m4b",
        "Harbor Stories/02 - Roads.m4b",
    ]
    assert "private-fixture-passkey" not in result.model_dump_json()


@pytest.mark.parametrize("flag", [lt.create_torrent.v1_only, lt.create_torrent.v2_only, 0])
@pytest.mark.parametrize(
    "names", [["Book.m4b"], ["Series/First/book.m4b", "Series/Second/book.epub"]]
)
async def test_v1_v2_and_hybrid_single_and_multifile_torrents(flag, names, tmp_path):
    storage = lt.file_storage()
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Original fixture content")
        storage.add_file(name, path.stat().st_size)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        create = lt.create_torrent(storage, 16384, flags=flag)
    lt.set_piece_hashes(create, str(tmp_path))
    document = create.generate()
    raw = lt.bencode(document)
    result = await inspect_torrent(raw)
    encoded_info = lt.bencode(document[b"info"])
    assert result.infohash_v1 == (
        None if flag == lt.create_torrent.v2_only else hashlib.sha1(encoded_info).hexdigest()
    )
    assert result.infohash_v2 == (
        None if flag == lt.create_torrent.v1_only else hashlib.sha256(encoded_info).hexdigest()
    )
    assert sorted(file.path for file in result.files) == sorted(names)
    assert result.content_bytes == 24 * len(names)
    assert result.torrent_bytes == result.content_bytes + result.padding_bytes


@pytest.mark.parametrize("name", [b"..", b"/absolute", b"a/b", b"a\\b", b"a\x00b", b"a:b"])
async def test_raw_path_components_cannot_be_silently_sanitized(name):
    with pytest.raises(AdapterError) as error:
        await inspect_torrent(torrent_bytes(files=[{b"length": 24, b"path": [name]}]))
    assert error.value.kind == FailureKind.PARSER


@pytest.mark.parametrize(
    "raw", [b"", b"<html>private credential</html>", b"d4:infodi5ee", b"x" * (8 * 1024 * 1024 + 1)]
)
async def test_invalid_or_excessive_metadata_has_safe_errors(raw):
    with pytest.raises(AdapterError) as error:
        await inspect_torrent(raw)
    assert error.value.kind == FailureKind.PARSER
    assert "private credential" not in str(error.value)


async def test_duplicates_symlinks_and_zero_content_are_held():
    for files in [
        [{b"length": 12, b"path": [b"same.m4b"]}] * 2,
        [{b"length": 24, b"path": [b"link"], b"attr": b"l", b"symlink path": [b"elsewhere"]}],
        [{b"length": 0, b"path": [b"empty.m4b"]}],
    ]:
        with pytest.raises(AdapterError):
            await inspect_torrent(torrent_bytes(files=files))


async def test_probe_deadline_reaps_the_child(monkeypatch):
    from app.adapters import torrent_descriptor

    real_create = asyncio.create_subprocess_exec
    children = []

    async def capture(*args, **kwargs):
        child = await real_create(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    monkeypatch.setattr(torrent_descriptor, "PROBE_TIMEOUT", 0.0001)
    with pytest.raises(AdapterError) as error:
        await inspect_torrent(torrent_bytes())
    assert error.value.kind == FailureKind.TIMEOUT
    assert children and all(child.returncode is not None for child in children)


async def test_cancelled_inspection_reaps_the_child(monkeypatch):
    real_create = asyncio.create_subprocess_exec
    started = asyncio.Event()
    children = []

    async def capture(*args, **kwargs):
        child = await real_create(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        children.append(child)
        started.set()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    task = asyncio.create_task(inspect_torrent(torrent_bytes()))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert children and all(child.returncode is not None for child in children)
