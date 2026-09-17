import hashlib
import os
import time
import zipfile
from pathlib import Path

import pytest

from app.importing import inspection
from app.importing.filesystem import InspectionError, beneath, directory, enumerate_files
from app.importing.inspection import inspect_download, probe_audio
from tests.media_fixtures import audio, epub


def test_real_epub_audio_pack_preserves_bytes_and_separates_recordings(tmp_path):
    root = tmp_path.resolve()
    epub(root / "pack/First Harbor.epub")
    epub(root / "pack/Second Harbor.epub", title="Second Harbor")
    audio(root / "pack/First Harbor/Jordan/Disc 1/01.mp3")
    audio(root / "pack/First Harbor/Jordan/Disc 1/02.mp3", track=2)
    audio(root / "pack/First Harbor/Casey/book.m4b", narrator="Casey Reed")
    originals = {
        str(path.relative_to(root / "pack")): path.read_bytes()
        for path in (root / "pack").rglob("*")
        if path.is_file()
    }
    snapshot = inspect_download(root, "pack")
    assert len(snapshot["files"]) == 5
    assert len(snapshot["groups"]) == 4
    tracks = next(group for group in snapshot["groups"] if len(group["files"]) == 2)
    assert tracks["narrators"] == ["Jordan Lee"]
    assert [(file["disc"], file["track"]) for file in tracks["files"]] == [(1, 1), (1, 2)]
    assert all(group["identity"] == "unresolved" for group in snapshot["groups"])
    assert all(group["full_content"] == "unverified" for group in snapshot["groups"])
    for file in snapshot["files"]:
        assert file["state"] == "inspected", file
        assert file["sha256"] == hashlib.sha256(originals[file["path"]]).hexdigest()
        assert (root / "pack" / file["path"]).read_bytes() == originals[file["path"]]
    assert not snapshot["publication_available"]
    assert snapshot == inspect_download(root, "pack")


@pytest.mark.parametrize("kind", ["file-link", "directory-link", "fifo"])
def test_links_and_special_files_cannot_escape_download_tree(tmp_path, kind):
    root = tmp_path.resolve()
    (root / "pack").mkdir()
    epub(root / "outside/book.epub")
    target = root / "pack/escape"
    if kind == "fifo":
        os.mkfifo(target)
    else:
        target.symlink_to(root / ("outside/book.epub" if kind == "file-link" else "outside"))
    with pytest.raises(InspectionError, match="symlink or special"):
        inspect_download(root, "pack")


def test_root_ancestor_link_and_relative_traversal_refused(tmp_path):
    root = tmp_path.resolve()
    epub(root / "actual/pack/book.epub")
    (root / "link").symlink_to(root / "actual")
    with pytest.raises(OSError):
        inspect_download(root / "link", "pack")
    with pytest.raises(ValueError):
        inspect_download(root, "../outside")
    with directory(root) as fd, pytest.raises(ValueError):
        with beneath(fd, "/etc/passwd"):
            pass


def test_invalid_epub_and_unsupported_archive_are_held_independently(tmp_path):
    root = tmp_path.resolve()
    epub(root / "pack/good.epub")
    epub(root / "pack/incomplete.epub", chapter=False)
    (root / "pack/fake.mp3").write_text("not audio")
    (root / "pack/collection.zip").write_bytes(b"archive")
    result = inspect_download(root, "pack")
    assert len(result["groups"]) == 1
    bad = {file["path"]: file for file in result["files"] if file["state"] == "held"}
    assert len(bad) == 3
    assert "missing or empty" in bad["incomplete.epub"]["reason"]
    assert "extraction" in bad["collection.zip"]["reason"]


def test_epub_entity_and_duplicate_metadata_are_not_read(tmp_path):
    root = tmp_path.resolve()
    epub(
        root / "pack/entity.epub",
        metadata="<!DOCTYPE package [<!ENTITY secret SYSTEM "
        '"file:///etc/passwd">]><package>&secret;</package>',
    )
    epub(root / "pack/duplicate.epub")
    epub(root / "pack/encrypted.epub")
    with zipfile.ZipFile(root / "pack/encrypted.epub", "a") as archive:
        archive.writestr("META-INF/encryption.xml", "<encryption />")
    with pytest.warns(UserWarning), zipfile.ZipFile(root / "pack/duplicate.epub", "a") as archive:
        archive.writestr("mimetype", "bad")
    result = inspect_download(root, "pack")
    assert not result["groups"]
    assert all(file["state"] == "held" for file in result["files"])
    assert not any("root:" in str(file) for file in result["files"])


def test_inspection_detects_file_mutation_during_probe(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    epub(root / "pack/book.epub")
    original = inspection.inspect_file

    def change(fd, path, deadline):
        result = original(fd, path, deadline)
        (root / "pack/book.epub").write_bytes(b"changed")
        return result

    monkeypatch.setattr(inspection, "inspect_file", change)
    with pytest.raises(InspectionError, match="changed while"):
        inspect_download(root, "pack")


def test_limits_stop_large_or_deep_inspection(tmp_path):
    root = tmp_path.resolve()
    epub(root / "pack/book.epub")
    with pytest.raises(InspectionError, match="byte budget"):
        inspect_download(root, "pack", max_bytes=1)
    with pytest.raises(InspectionError, match="time budget"):
        inspect_download(root, "pack", timeout=-1)
    with directory(root) as fd, pytest.raises(InspectionError, match="entry count"):
        enumerate_files(fd, max_entries=1)


def test_audio_probe_output_and_timeout_are_bounded(tmp_path):
    root = tmp_path.resolve()
    source = root / "file.mp3"
    source.write_bytes(b"test")
    for behavior, expected in [
        ("import time; time.sleep(1)", "timed out"),
        ("import sys; sys.stdout.write('x' * 1100000)", "supported size"),
    ]:
        fake = root / "fake-probe"
        import sys

        fake.write_text(f"#!{sys.executable}\n{behavior}\n")
        fake.chmod(0o700)
        with source.open("rb") as file, pytest.raises(InspectionError, match=expected):
            probe_audio(file.fileno(), "mp3", time.monotonic() + 0.3, executable=str(fake))


def test_audio_disc_folder_and_tags_conflict_is_held():
    files = [
        {
            "state": "inspected",
            "medium": "audio",
            "path": "Book/Disc 2/01.mp3",
            "extension": "mp3",
            "technical": {"tags": {"album": "Book", "disc": "1", "track": "1"}},
        }
    ]
    assert inspection.suggest_groups(files) == []
    assert files[0]["state"] == "held"


def test_download_root_cannot_be_filesystem_root():
    with pytest.raises(InspectionError, match="filesystem root"):
        with directory(Path("/")):
            pass
