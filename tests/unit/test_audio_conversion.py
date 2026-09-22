import json
import subprocess
from uuid import uuid4

import pytest

from app.importing.converters import AudioConversion, ConversionChapter, chapter_title
from app.importing.inspection import inspect_download
from app.importing.naming import fingerprint
from app.importing.publication import PublicationSpec, publish_item
from tests.media_fixtures import audio


def test_chapter_titles_prefer_specific_tags_then_filenames():
    assert chapter_title("01 - Opening.mp3", {"title": "Opening"}, "Harbor") == "Opening"
    assert chapter_title("01 - Opening.mp3", {"title": "Harbor"}, "Harbor") == "Opening"
    assert chapter_title("01 - Opening.mp3", {"title": "1"}, "Harbor") == "Opening"
    assert chapter_title("Chapter 02 - Roads.mp3", {}, "Harbor") == "Roads"
    assert chapter_title("track01.mp3", {}, "Harbor") == "track01"


def _spec(tmp_path, mode):
    base = tmp_path.resolve()
    source, library, staging = (base / name for name in ("downloads", "library", "staging"))
    audio(source / "pack/01 - Opening.mp3", track=1)
    audio(source / "pack/02 - Roads.mp3", track=2)
    library.mkdir()
    staging.mkdir(mode=0o700)
    snapshot = inspect_download(source, "pack")
    inspected = {file["path"]: file for file in snapshot["files"]}

    def chapter(name, title):
        file = inspected[name]
        return ConversionChapter(
            source=name, title=title, sha256=file["sha256"], identity=file["identity"]
        )

    return PublicationSpec(
        entry_id=uuid4(),
        plan_revision=fingerprint({"merge": True}),
        source_root=source,
        source_relative="pack",
        source_directory=snapshot["directory_identity"],
        destination_root=library,
        staging_root=staging,
        folder="Alex Morgan/Harbor",
        mode=mode,
        conversion=AudioConversion(
            converter="ffmpeg-chapterized-m4b",
            output_name="Harbor.m4b",
            title="Harbor",
            artist="Alex Morgan",
            narrator="Jordan Lee",
            chapters=[chapter("01 - Opening.mp3", "Opening"), chapter("02 - Roads.mp3", "Roads")],
        ),
    )


@pytest.mark.parametrize("mode", ["hardlink", "copy"])
def test_multi_file_mp3_publishes_one_chapterized_m4b_without_touching_the_download(tmp_path, mode):
    spec = _spec(tmp_path, mode)
    originals = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in spec.source_root.rglob("*.mp3")
    }
    receipt = publish_item(spec)
    published = spec.destination_root / spec.folder / "Harbor.m4b"
    assert receipt["state"] == "published"
    assert receipt["derived"]["Harbor.m4b"]["sha256"]
    assert sorted(path.name for path in (spec.destination_root / spec.folder).iterdir()) == [
        "Harbor.m4b"
    ]
    assert published.stat().st_size == receipt["derived"]["Harbor.m4b"]["size"]
    for path, (content, mtime) in originals.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == mtime
        assert path.stat().st_ino != published.stat().st_ino
    probed = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_chapters",
                "-show_entries",
                "format_tags=title,artist,composer",
                "-of",
                "json",
                str(published),
            ],
            timeout=20,
        )
    )
    assert [chapter["tags"]["title"] for chapter in probed["chapters"]] == ["Opening", "Roads"]
    assert probed["format"]["tags"]["title"] == "Harbor"
    assert probed["format"]["tags"]["artist"] == "Alex Morgan"
    assert publish_item(spec) == receipt


def test_interrupted_chapter_merge_resumes_onto_one_m4b(tmp_path):
    spec = _spec(tmp_path, "copy")

    def crash(phase):
        if phase == "convert-created":
            raise RuntimeError("simulated process interruption")

    with pytest.raises(RuntimeError, match="interruption"):
        publish_item(spec, checkpoint=crash)
    assert not (spec.destination_root / spec.folder).exists()
    receipt = publish_item(spec)
    assert receipt["state"] == "published"
    assert (spec.destination_root / spec.folder / "Harbor.m4b").is_file()
    assert not list(spec.destination_root.rglob("*.mp3"))


def test_journaled_m4b_is_not_reserved_twice(tmp_path):
    spec = _spec(tmp_path, "copy").model_copy(update={"sidecars": {"desc.txt": "Notes"}})

    def crash(phase):
        if phase == "converted":
            raise RuntimeError("simulated process interruption")

    with pytest.raises(RuntimeError, match="interruption"):
        publish_item(spec, checkpoint=crash)
    from app.importing.publication import remaining_import_bytes

    assert remaining_import_bytes(spec) == len(b"Notes")


def test_partial_m4b_reduces_the_next_reservation(tmp_path):
    from app.importing.publication import (
        conversion_reservation,
        private_staging,
        read_receipt,
        remaining_import_bytes,
    )

    spec = _spec(tmp_path, "copy")

    def crash(phase):
        if phase == "convert-created":
            raise RuntimeError("simulated process interruption")

    with pytest.raises(RuntimeError, match="interruption"):
        publish_item(spec, checkpoint=crash)
    with private_staging(spec.staging_root) as staging:
        receipt = read_receipt(staging, str(spec.entry_id) + ".json")
    staged = spec.staging_root / receipt["stage_name"] / "Harbor.m4b"
    with staged.open("r+b") as partial:
        partial.write(b"x" * 200)
    assert remaining_import_bytes(spec) == conversion_reservation(spec) - 200


def test_encoder_reads_the_hashed_descriptor(tmp_path, monkeypatch):
    import time

    from app.importing.converters import encode_chapterized_m4b
    from app.importing.filesystem import InspectionError, directory, source_scope

    spec = _spec(tmp_path, "copy")
    seen = {}

    def stop(command, deadline, **kwargs):
        seen["command"] = command
        seen["pass_fds"] = kwargs.get("pass_fds")
        raise InspectionError("stopped")

    monkeypatch.setattr("app.importing.converters._run", stop)
    with (
        directory(spec.source_root) as root,
        source_scope(root, spec.source_relative, spec.source_kind) as source,
    ):
        with pytest.raises(InspectionError, match="stopped"):
            encode_chapterized_m4b(
                source, spec.conversion, str(tmp_path / "out.m4b"), time.monotonic() + 30
            )
    inputs = [arg for arg in seen["command"] if arg.startswith("/dev/fd/")]
    assert len(inputs) == 2
    joined = " ".join(seen["command"])
    assert "Opening.mp3" not in joined and "Roads.mp3" not in joined
    assert seen["pass_fds"]


def test_encoder_rejects_a_descriptor_whose_bytes_changed(tmp_path):
    import time

    from app.importing.converters import encode_chapterized_m4b
    from app.importing.filesystem import InspectionError, directory, source_scope

    spec = _spec(tmp_path, "copy")
    plan = spec.conversion.model_copy(deep=True)
    plan.chapters[0].sha256 = "ab" * 32
    with (
        directory(spec.source_root) as root,
        source_scope(root, spec.source_relative, spec.source_kind) as source,
    ):
        with pytest.raises(InspectionError, match="bytes changed"):
            encode_chapterized_m4b(source, plan, str(tmp_path / "out.m4b"), time.monotonic() + 30)


def test_bitrate_follows_duration_and_file_size():
    from app.importing.converters import _bitrate

    assert (
        _bitrate([{"bit_rate": 320000, "duration": 1}, {"bit_rate": 64000, "duration": 100}])
        == "67k"
    )
    assert _bitrate([{"bit_rate": 0, "duration": 10, "size": 80000}]) == "64k"


def test_finished_encode_waits_for_the_library_lock(tmp_path, monkeypatch):
    import json
    import threading
    import time

    from app.importing.converters import _run as real_run
    from app.importing.filesystem import directory
    from app.importing.publication import object_id, private_staging, publication_lock

    spec = _spec(tmp_path, "copy")
    started = threading.Event()
    release = threading.Event()
    outcome = []

    def spy(command, deadline, **kwargs):
        started.set()
        assert release.wait(timeout=30)
        return real_run(command, deadline, **kwargs)

    monkeypatch.setattr("app.importing.converters._run", spy)

    def other():
        assert started.wait(timeout=30)
        with (
            private_staging(spec.staging_root) as staging,
            directory(spec.destination_root) as destination,
        ):
            key = json.dumps(object_id(destination), sort_keys=True)
            with publication_lock(staging, key):
                outcome.append("acquired")
                release.set()
                time.sleep(1)

    thread = threading.Thread(target=other)
    thread.start()
    receipt = publish_item(spec)
    thread.join(timeout=60)
    assert receipt["state"] == "published"
    assert outcome == ["acquired"]


def test_landed_bytes_shrink_the_capacity_reservation():
    from app.domain.capacity import MIB, remaining_after_landing

    assert remaining_after_landing(10_000_000, 3_000_000) == 7_000_000
    assert remaining_after_landing(1000, 5000) == MIB
