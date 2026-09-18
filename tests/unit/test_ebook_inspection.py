import struct
import sys
import time
import zipfile

import pytest
from pypdf import PdfWriter

from app.importing import ebook_probe
from app.importing.book_containers import check_zip_directory
from app.importing.filesystem import InspectionError
from app.importing.grouping import ReviewedFile, ReviewedGroup, regroup
from app.importing.inspection import inspect_download
from app.importing.probe import probe_output
from tests.media_fixtures import audio, cbz, cover_bytes, epub, pdf


def test_pdf_and_cbz_inspection_preserves_content_and_requires_identity_review(tmp_path):
    root = tmp_path.resolve()
    pdf(root / "pack/book.pdf")
    cbz(root / "pack/book.cbz")
    originals = {file.name: file.read_bytes() for file in (root / "pack").iterdir()}
    result = inspect_download(root, "pack")
    assert len(result["groups"]) == 2
    for file in result["files"]:
        assert file["state"] == "inspected", file
        assert file["metadata"]["title"] == "First Harbor"
        assert file["metadata"]["authors"] == ["Alex Morgan"]
        assert file["metadata"]["pages"] == 2
        assert (root / "pack" / file["path"]).read_bytes() == originals[file["path"]]
    assert all(group["full_content"] == "unverified" for group in result["groups"])
    assert all(group["identity"] == "unresolved" for group in result["groups"])


@pytest.mark.parametrize("kind", ["encrypted", "empty-password", "blank", "truncated", "fake"])
def test_pdf_unreadable_or_encrypted_content_is_held_without_private_diagnostics(tmp_path, kind):
    root = tmp_path.resolve()
    target = root / "pack/book.pdf"
    pdf(target, title="PRIVATE TITLE", password="secret" if kind == "encrypted" else None)
    if kind == "empty-password":
        pdf(target, password="")
    elif kind == "blank":
        writer = PdfWriter()
        writer.add_blank_page(width=360, height=540)
        writer.write(target)
    elif kind == "truncated":
        target.write_bytes(target.read_bytes()[:100])
    elif kind == "fake":
        target.write_bytes(b"not a PDF PRIVATE TITLE")
    result = inspect_download(root, "pack")
    assert not result["groups"]
    file = result["files"][0]
    assert file["state"] == "held"
    assert "PRIVATE" not in file["reason"] and "secret" not in file["reason"]
    if kind in {"encrypted", "empty-password"}:
        assert "Encrypted" in file["reason"]


@pytest.mark.parametrize(
    "kind", ["traversal", "symlink", "duplicate", "invalid", "entity", "animation"]
)
def test_cbz_rejects_unsafe_or_unreadable_entries(tmp_path, kind):
    root = tmp_path.resolve()
    target = root / "pack/book.cbz"
    cbz(target)
    if kind == "entity":
        with zipfile.ZipFile(target, "w") as book:
            book.writestr("pages/001.png", cover_bytes())
    with zipfile.ZipFile(target, "a") as book:
        if kind == "traversal":
            book.writestr("../escape.png", cover_bytes())
        elif kind == "symlink":
            entry = zipfile.ZipInfo("linked.png")
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            book.writestr(entry, "/etc/passwd")
        elif kind == "duplicate":
            with pytest.warns(UserWarning):
                book.writestr("pages/001.png", cover_bytes())
        elif kind == "invalid":
            book.writestr("pages/003.jpg", b"not an image")
        elif kind == "entity":
            book.writestr(
                "ComicInfo.xml",
                '<!DOCTYPE ComicInfo [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                "<ComicInfo><Title>&x;</Title></ComicInfo>",
            )
        else:
            from PIL import Image

            book.writestr(
                "pages/003.png",
                cover_bytes(save_all=True, append_images=[Image.new("RGB", (240, 360), "red")]),
            )
    result = inspect_download(root, "pack")
    assert not result["groups"] and result["files"][0]["state"] == "held"
    assert "root:" not in str(result)


def test_book_container_budgets_are_checked_before_decoding(tmp_path, monkeypatch):
    target = tmp_path / "book.cbz"
    cbz(target)
    monkeypatch.setattr(ebook_probe, "MAX_PIXELS", 10)
    with target.open("rb") as source, pytest.raises(InspectionError, match="dimensions"):
        ebook_probe.inspect_cbz(source.fileno())
    monkeypatch.setattr(ebook_probe, "MAX_PAGE_BYTES", 10)
    with target.open("rb") as source, pytest.raises(InspectionError, match="expanded"):
        ebook_probe.inspect_cbz(source.fileno())
    data = bytearray(target.read_bytes())
    end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<L", data, end + 12, 100 * 1024 * 1024)
    target.write_bytes(data)
    with target.open("rb") as source, pytest.raises(InspectionError, match="directory"):
        check_zip_directory(source.fileno(), "CBZ")
    cbz(target)
    data = target.read_bytes()
    end = data.rfind(b"PK\x05\x06")
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, 0, 1)
    target.write_bytes(data[:end] + locator + data[end:])
    with target.open("rb") as source, pytest.raises(InspectionError, match="ZIP64"):
        check_zip_directory(source.fileno(), "CBZ")


def test_pdf_page_and_expansion_limits(tmp_path, monkeypatch):
    target = tmp_path / "book.pdf"
    pdf(target)
    monkeypatch.setattr(ebook_probe, "MAX_PAGES", 1)
    with target.open("rb") as source, pytest.raises(InspectionError, match="page count"):
        ebook_probe.inspect_pdf(source.fileno())
    monkeypatch.setattr(ebook_probe, "MAX_PAGES", 100)
    monkeypatch.setattr(ebook_probe, "MAX_EXPANDED", 1)
    with target.open("rb") as source, pytest.raises(InspectionError, match="budget"):
        ebook_probe.inspect_pdf(source.fileno())


def test_child_probe_receives_only_pinned_descriptor_and_bounds_execution(tmp_path):
    path = tmp_path / "book"
    path.write_bytes(b"original")
    with path.open("rb") as source:
        path.unlink()
        path.write_bytes(b"replacement")
        command = [
            sys.executable,
            "-c",
            f"import os; print(os.read({source.fileno()}, 50).decode())",
        ]
        assert (
            probe_output(command, source.fileno(), time.monotonic() + 2, label="PDF")
            == b"original\n"
        )
        for code, message in [
            ("import time; time.sleep(2)", "timed out"),
            ("print('x' * 100)", "supported size"),
        ]:
            with pytest.raises(InspectionError, match=message):
                probe_output(
                    [sys.executable, "-c", code],
                    source.fileno(),
                    time.monotonic() + 0.2,
                    label="PDF",
                    max_output=50,
                )


def test_same_edition_formats_need_confirmation_and_use_metadata_consensus(tmp_path):
    root = tmp_path.resolve()
    epub(root / "pack/book.epub")
    pdf(root / "pack/book.pdf", title="Different embedded title")
    snapshot = inspect_download(root, "pack")
    group = ReviewedGroup(files=[ReviewedFile(path=file["path"]) for file in snapshot["files"]])
    with pytest.raises(ValueError, match="same complete edition"):
        regroup(snapshot, [group], [])
    group.same_edition = True
    reviewed = regroup(snapshot, [group], []).groups[0]
    assert reviewed.same_edition and reviewed.medium == "ebook"
    assert reviewed.title is None and reviewed.authors == ["Alex Morgan"]
    assert len(reviewed.files) == 2 and reviewed.full_content == "unverified"
    assert regroup(snapshot, [group], []).groups[0].key == reviewed.key


def test_same_format_ebooks_are_distinct_books_not_tracks(tmp_path):
    root = tmp_path.resolve()
    pdf(root / "pack/one.pdf")
    pdf(root / "pack/two.pdf")
    snapshot = inspect_download(root, "pack")
    group = ReviewedGroup(
        files=[ReviewedFile(path=file["path"]) for file in snapshot["files"]],
        same_edition=True,
    )
    with pytest.raises(ValueError, match="same file format"):
        regroup(snapshot, [group], [])


def test_pdf_companion_is_not_a_second_book_or_an_audio_track(tmp_path):
    root = tmp_path.resolve()
    audio(root / "pack/book.mp3")
    pdf(root / "pack/companion.pdf", title="Supporting notes", author="Different contributor")
    snapshot = inspect_download(root, "pack")
    group = ReviewedGroup(files=[ReviewedFile(path="book.mp3"), ReviewedFile(path="companion.pdf")])
    with pytest.raises(ValueError, match="separate groups"):
        regroup(snapshot, [group], [])
    group.files[1].role = "supplement"
    reviewed = regroup(snapshot, [group], []).groups[0]
    assert reviewed.medium == "audio" and reviewed.title == "First Harbor"
    assert reviewed.authors == ["Alex Morgan"] and reviewed.narrators == ["Jordan Lee"]
    assert reviewed.files[1].role == "supplement"
    group.files[1].track = 1
    with pytest.raises(ValueError, match="only to audio"):
        regroup(snapshot, [group], [])


def test_companions_need_actual_audio_and_cannot_disguise_complete_epubs(tmp_path):
    root = tmp_path.resolve()
    epub(root / "pack/book.epub")
    pdf(root / "pack/companion.pdf")
    snapshot = inspect_download(root, "pack")
    group = ReviewedGroup(
        files=[
            ReviewedFile(path="book.epub"),
            ReviewedFile(path="companion.pdf", role="supplement"),
        ]
    )
    with pytest.raises(ValueError, match="attached to an audiobook"):
        regroup(snapshot, [group], [])
    group.files[0].role = "supplement"
    with pytest.raises(ValueError, match="separate groups"):
        regroup(snapshot, [group], [])
