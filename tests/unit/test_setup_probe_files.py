import errno
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.importing import publication


@pytest.fixture
def roots(tmp_path):
    values = [tmp_path.resolve() / name for name in ("downloads", "library", "staging")]
    for root in values:
        root.mkdir(mode=0o700)
    return values


def test_concurrent_empty_root_probes_clean_only_their_own_objects(roots):
    source, target, stage = roots
    (source / "keep.bin").write_bytes(b"existing torrent file")
    before = (source / "keep.bin").stat()
    with ThreadPoolExecutor(max_workers=3) as pool:
        reports = list(
            pool.map(
                lambda _: publication.probe_download_folder(source, "", target, stage), range(3)
            )
        )
    assert all(report["hardlink"] and report["no_replace"] and report["copy"] for report in reports)
    assert list(source.iterdir()) == [source / "keep.bin"]
    assert (source / "keep.bin").stat() == before
    assert not list(target.iterdir()) and not list(stage.iterdir())


def test_failed_link_reports_copy_capability_without_claiming_a_hardlink(roots, monkeypatch):
    def cross_device(*args, **kwargs):
        raise OSError(errno.EXDEV, "different filesystem")

    monkeypatch.setattr(publication.os, "link", cross_device)
    source, target, stage = roots
    report = publication.probe_download_folder(source, "", target, stage)
    assert not report["hardlink"] and report["hardlink_error"] == "EXDEV"
    assert report["copy"] and report["no_replace"]
    assert all(not list(root.iterdir()) for root in roots)


def test_failed_probe_removes_owned_source_file(roots, monkeypatch):
    def fail(*args, **kwargs):
        raise publication.PublicationError("synthetic probe failure")

    monkeypatch.setattr(publication, "probe_destination", fail)
    source, target, stage = roots
    with pytest.raises(publication.PublicationError, match="synthetic probe failure"):
        publication.probe_download_folder(source, "", target, stage)
    assert all(not list(root.iterdir()) for root in roots)


def test_unrecognized_source_replacement_is_preserved(roots, monkeypatch):
    def replace(source, relative, *args, **kwargs):
        path = source / relative
        path.unlink()
        path.write_bytes(b"replacement must survive")
        return {"hardlink": True}

    monkeypatch.setattr(publication, "probe_destination", replace)
    source, target, stage = roots
    with pytest.raises(publication.PublicationError, match="replacement preserved"):
        publication.probe_download_folder(source, "", target, stage)
    remaining = list(source.iterdir())
    assert len(remaining) == 1 and remaining[0].read_bytes() == b"replacement must survive"


def test_overlap_rejected_before_a_temporary_source_is_created(roots):
    source, _, stage = roots
    with pytest.raises(publication.PublicationError, match="overlap"):
        publication.probe_download_folder(source, "", source, stage)
    assert not list(source.iterdir())
