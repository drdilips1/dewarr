import errno
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.importing import publication
from app.importing.inspection import inspect_download
from app.importing.naming import fingerprint
from app.importing.publication import (
    PublicationBusy,
    PublicationError,
    PublicationSpec,
    PublishFile,
    probe_destination,
    publish_item,
)
from tests.media_fixtures import epub


@pytest.fixture
def specification(tmp_path):
    base = tmp_path.resolve()
    source, library, staging = (base / name for name in ("downloads", "library", "staging"))
    epub(source / "pack/book.epub")
    library.mkdir()
    staging.mkdir(mode=0o700)
    snapshot = inspect_download(source, "pack")
    file = snapshot["files"][0]
    return PublicationSpec(
        entry_id=uuid4(),
        plan_revision=fingerprint({"test": True}),
        source_root=source,
        source_relative="pack",
        source_directory=snapshot["directory_identity"],
        destination_root=library,
        staging_root=staging,
        folder="Alex Morgan/First Harbor",
        files=[
            PublishFile(
                source="book.epub",
                name="First Harbor.epub",
                sha256=file["sha256"],
                identity=file["identity"],
            )
        ],
        sidecars={"metadata.opf": "<package/>"},
    )


@pytest.mark.parametrize("mode", ["hardlink", "copy"])
def test_publication_preserves_original_and_keeps_receipts_outside_library(specification, mode):
    spec = specification.model_copy(update={"mode": mode})
    original = spec.source_root / "pack/book.epub"
    before, before_stat = original.read_bytes(), original.stat()
    receipt = publish_item(spec)
    published = spec.destination_root / spec.folder / "First Harbor.epub"
    assert published.read_bytes() == before == original.read_bytes()
    assert (published.stat().st_ino == original.stat().st_ino) == (mode == "hardlink")
    assert original.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert receipt["state"] == "published"
    assert (spec.destination_root / spec.folder / "metadata.opf").read_text() == "<package/>"
    assert not list(spec.destination_root.rglob("*.json"))
    assert publish_item(spec) == receipt


@pytest.mark.parametrize(
    "mode,point",
    [
        ("hardlink", "stage-created"),
        ("hardlink", "file-staged"),
        ("hardlink", "prepared"),
        ("hardlink", "published-before-receipt"),
        ("copy", "copy-created"),
        ("copy", "file-staged"),
        ("copy", "prepared"),
        ("copy", "published-before-receipt"),
    ],
)
def test_interrupted_publication_resumes_without_duplicate_or_partial_item(
    specification, mode, point
):
    spec = specification.model_copy(update={"mode": mode})

    def crash(phase):
        if phase == point:
            raise RuntimeError("simulated process interruption")

    with pytest.raises(RuntimeError, match="interruption"):
        publish_item(spec, checkpoint=crash)
    folder = spec.destination_root / spec.folder
    assert folder.exists() == (point == "published-before-receipt")
    receipt = publish_item(spec)
    assert receipt["state"] == "published"
    assert sorted(path.name for path in folder.iterdir()) == ["First Harbor.epub", "metadata.opf"]
    assert len(list(spec.destination_root.rglob("*.epub"))) == 1


def test_retry_recognizes_published_item_even_if_download_was_later_removed(specification):
    spec = specification
    publish_item(spec)
    (spec.source_root / "pack/book.epub").unlink()
    assert publish_item(spec)["state"] == "published"


@pytest.mark.parametrize("contents", [None, "unrelated"])
def test_existing_destination_never_replaced_or_adopted(specification, contents):
    spec = specification
    destination = spec.destination_root / spec.folder
    destination.mkdir(parents=True)
    if contents:
        (destination / "existing.txt").write_text(contents)
    before = destination.stat().st_ino
    with pytest.raises(PublicationError, match="another item"):
        publish_item(spec)
    assert destination.stat().st_ino == before
    if contents:
        assert (destination / "existing.txt").read_text() == contents


def test_source_change_cannot_publish_a_stale_manifest(specification):
    spec = specification
    (spec.source_root / "pack/book.epub").write_bytes(b"changed")
    with pytest.raises(PublicationError, match="changed"):
        publish_item(spec)
    assert not (spec.destination_root / spec.folder).exists()


def test_casefold_collision_and_parent_media_are_held(specification):
    spec = specification
    (spec.destination_root / "alex morgan").mkdir()
    with pytest.raises(PublicationError, match="case variant"):
        publish_item(spec)
    (spec.destination_root / "alex morgan").rename(spec.destination_root / "Alex Morgan")
    (spec.destination_root / "Alex Morgan/old.mp3").write_bytes(b"existing")
    with pytest.raises(PublicationError, match="already contains files"):
        publish_item(spec)
    assert (spec.destination_root / "Alex Morgan/old.mp3").read_bytes() == b"existing"


def test_symlink_destination_parent_cannot_escape(specification, tmp_path):
    spec = specification
    outside = tmp_path.resolve() / "outside"
    outside.mkdir()
    (spec.destination_root / "Alex Morgan").symlink_to(outside)
    with pytest.raises(OSError):
        publish_item(spec)
    assert not list(outside.iterdir())


def test_destination_parent_move_before_rename_is_detected(specification):
    spec = specification

    def move(phase):
        if phase == "before-publish":
            (spec.destination_root / "Alex Morgan").rename(spec.destination_root / "Moved")
            (spec.destination_root / "Alex Morgan").mkdir()

    with pytest.raises(PublicationError, match="parent moved"):
        publish_item(spec, checkpoint=move)
    assert not list(spec.destination_root.rglob("*.epub"))


def test_unknown_staging_file_is_not_deleted_to_make_manifest_fit(specification):
    spec = specification

    def stop(phase):
        if phase == "stage-created":
            raise RuntimeError("stop")

    with pytest.raises(RuntimeError):
        publish_item(spec, checkpoint=stop)
    journal = json.loads((spec.staging_root / f"{spec.entry_id}.json").read_text())
    extra = spec.staging_root / journal["stage_name"] / "unrelated.txt"
    extra.write_text("preserve me")
    with pytest.raises(PublicationError, match="unplanned files"):
        publish_item(spec)
    assert extra.read_text() == "preserve me"


def test_actual_link_and_rename_probe_cleans_only_its_artifacts(specification):
    spec = specification
    source = spec.source_root / "pack/book.epub"
    before = source.read_bytes()
    result = probe_destination(
        spec.source_root,
        spec.source_relative,
        spec.files[0],
        spec.destination_root,
        spec.staging_root,
    )
    assert result["hardlink"] and result["no_replace"]
    assert source.read_bytes() == before
    assert not list(spec.staging_root.iterdir()) and not list(spec.destination_root.iterdir())


def test_probe_cross_device_link_does_not_silently_choose_copy(specification, monkeypatch):
    spec = specification

    def cross_device(*args, **kwargs):
        raise OSError(errno.EXDEV, "test mount boundary")

    monkeypatch.setattr(os, "link", cross_device)
    result = probe_destination(
        spec.source_root,
        spec.source_relative,
        spec.files[0],
        spec.destination_root,
        spec.staging_root,
    )
    assert not result["hardlink"] and result["hardlink_error"] == "EXDEV"
    assert result["no_replace"]


def test_probe_collision_does_not_remove_preexisting_folder(specification, monkeypatch):
    spec = specification

    @dataclass
    class Fixed:
        hex: str = "collision"

    monkeypatch.setattr(publication, "uuid4", Fixed)
    existing = spec.destination_root / ".book-search-probe-collision"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        probe_destination(
            spec.source_root,
            spec.source_relative,
            spec.files[0],
            spec.destination_root,
            spec.staging_root,
        )
    assert existing.is_dir()
    assert not list(spec.staging_root.iterdir())


def test_private_staging_and_root_separation_required(specification):
    spec = specification
    spec.staging_root.chmod(0o755)
    with pytest.raises(PublicationError, match="private"):
        publish_item(spec)
    with pytest.raises(ValueError, match="overlap"):
        PublicationSpec.model_validate(
            {**spec.model_dump(), "staging_root": spec.destination_root / "stage"}
        )


def test_probe_preserves_replaced_destination_during_cleanup(specification, monkeypatch):
    spec = specification
    original = publication.no_replace
    replacements = []

    def replace_after_publish(source_fd, source_name, destination_fd, destination_name):
        original(source_fd, source_name, destination_fd, destination_name)
        destination = spec.destination_root / destination_name
        destination.rename(spec.destination_root / "moved-original-probe")
        destination.mkdir()
        replacements.append(destination)

    monkeypatch.setattr(publication, "no_replace", replace_after_publish)
    with pytest.raises(PublicationError, match="unrecognized replacement preserved"):
        probe_destination(
            spec.source_root,
            spec.source_relative,
            spec.files[0],
            spec.destination_root,
            spec.staging_root,
        )
    assert replacements and replacements[0].is_dir()
    assert (spec.destination_root / "moved-original-probe").is_dir()
    assert not list(spec.staging_root.iterdir())


def test_concurrent_publishers_cannot_create_two_items(specification):
    def run():
        try:
            return publish_item(specification)["state"]
        except PublicationBusy:
            return "busy"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert "published" in results
    assert set(results) <= {"published", "busy"}
    assert len(list(specification.destination_root.rglob("*.epub"))) == 1


def test_deleted_or_changed_published_item_is_not_replaced(specification):
    spec = specification
    publish_item(spec)
    published = spec.destination_root / spec.folder / "First Harbor.epub"
    published.unlink()
    with pytest.raises(PublicationError, match="unplanned files"):
        publish_item(spec)
    assert not published.exists()


@pytest.fixture(params=["book.epub", "nested/book.epub"])
def file_spec(specification, request):
    spec = specification
    relative = request.param
    selected = spec.source_root / relative
    selected.parent.mkdir(exist_ok=True)
    (spec.source_root / "pack/book.epub").rename(selected)
    epub(spec.source_root / "neighbor.epub", title="Unrelated download")
    snapshot = inspect_download(spec.source_root, relative)
    file = snapshot["files"][0]
    return PublicationSpec.model_validate(
        {
            **spec.model_dump(),
            "source_kind": "file",
            "source_relative": relative,
            "source_directory": snapshot["directory_identity"],
            "files": [
                {
                    "source": file["path"],
                    "name": "First Harbor.epub",
                    "identity": file["identity"],
                    "sha256": file["sha256"],
                }
            ],
        }
    )


@pytest.mark.parametrize("mode", ["hardlink", "copy"])
def test_file_scoped_publication_is_source_preserving_and_resumable(file_spec, mode):
    spec = file_spec.model_copy(update={"mode": mode})
    selected = spec.source_root / spec.source_relative
    before = selected.read_bytes()
    neighbor = (spec.source_root / "neighbor.epub").read_bytes()

    def crash(phase):
        if phase == "file-staged":
            raise RuntimeError("Synthetic interrupted file import")

    with pytest.raises(RuntimeError, match="interrupted"):
        publish_item(spec, checkpoint=crash)
    epub(selected.parent / "new-download.epub", title="Concurrent download")
    assert publish_item(spec)["state"] == "published"
    published = spec.destination_root / spec.folder / "First Harbor.epub"
    assert before == selected.read_bytes() == published.read_bytes()
    assert (selected.stat().st_ino == published.stat().st_ino) == (mode == "hardlink")
    assert (spec.source_root / "neighbor.epub").read_bytes() == neighbor
    assert len(list(spec.destination_root.rglob("*.epub"))) == 1
    selected.unlink()
    assert publish_item(spec)["state"] == "published"


def test_file_scope_cannot_expand_to_a_different_or_additional_file(file_spec):
    original = file_spec.model_dump()
    for files in (
        [{**original["files"][0], "source": "neighbor.epub"}],
        [
            *original["files"],
            {**original["files"][0], "source": "neighbor.epub", "name": "Extra.epub"},
        ],
    ):
        with pytest.raises(ValueError, match="only its inspected file"):
            PublicationSpec.model_validate({**original, "files": files})


def test_file_scope_cannot_publish_a_replaced_source(file_spec):
    selected = file_spec.source_root / file_spec.source_relative
    selected.rename(selected.with_suffix(".old"))
    epub(selected)
    with pytest.raises(PublicationError, match="changed"):
        publish_item(file_spec)
    assert not (file_spec.destination_root / file_spec.folder).exists()


def test_directory_receipt_fingerprint_remains_backward_compatible(specification):
    old_document = specification.model_dump(mode="json")
    old_document.pop("source_kind")
    old_document.pop("binary_sidecars")
    assert publication.specification_fingerprint(specification) == fingerprint(old_document)
