"""Audiobook converters that run before a library import.

ffmpeg is already required for inspection, so the built-in merger encodes with it
instead of adding PHP m4b-tool or another runtime. Register another callable in
CONVERTERS to support more sources (FLAC, Opus, stream-copied M4A) or an external
encoder without changing publication.
"""

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

from app.importing.filesystem import InspectionError, beneath, digest, identity, relative_parts
from app.importing.naming import StrictModel, component
from app.importing.probe import probe_output

MAX_CHAPTERS = 2000
_GENERIC_TITLE = re.compile(
    r"^(?:(?:track|chapter|part|disc|disk|cd|ch)\s*)?\d+(?:\s*/\s*\d+)?$",
    re.I,
)
_FILENAME_PREFIX = re.compile(
    r"^(?:(?:cd|disc|disk)\s*\d+\s*[-._]*)?(?:(?:chapter|track|part|ch)\s*)?\d+\s*[-._:]+\s*",
    re.I,
)


class ConversionChapter(StrictModel):
    source: str
    title: str = Field(min_length=1, max_length=180)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    identity: dict[str, int]

    @model_validator(mode="after")
    def confined(self):
        relative_parts(self.source)
        return self


class AudioConversion(StrictModel):
    """Frozen recipe for one derived audiobook. Output bytes are journaled after encoding."""

    converter: Literal["ffmpeg-chapterized-m4b"]
    output_name: str = Field(min_length=5, max_length=200)
    chapters: list[ConversionChapter] = Field(min_length=2, max_length=MAX_CHAPTERS)
    title: str = Field(min_length=1, max_length=180)
    artist: str = Field(min_length=1, max_length=180)
    narrator: str | None = Field(default=None, max_length=180)
    year: int | None = Field(default=None, ge=0, le=9999)

    @model_validator(mode="after")
    def one_m4b(self):
        relative_parts(self.output_name)
        if len(relative_parts(self.output_name)) != 1 or not self.output_name.lower().endswith(
            ".m4b"
        ):
            raise ValueError("Converted audiobook must be a single .m4b filename")
        if len({chapter.source for chapter in self.chapters}) != len(self.chapters):
            raise ValueError("Conversion chapters repeat a source file")
        return self


def chapter_title(path, tags, book_title):
    """Prefer a specific embedded title, otherwise the filename without its track prefix."""
    raw = str((tags or {}).get("title") or "").strip()
    book = str(book_title or "").strip()
    if raw and not _GENERIC_TITLE.fullmatch(raw) and raw.casefold() != book.casefold():
        try:
            return component(raw)
        except ValueError:
            pass
    stem = PurePosixPath(path).stem
    cleaned = _FILENAME_PREFIX.sub("", stem).strip()
    try:
        return component(cleaned or stem)
    except ValueError:
        return "Chapter"


def mp3_chapter_merge(profile, media):
    return (
        profile.merge_mp3_chapters
        and len(media) > 1
        and {PurePosixPath(file.path).suffix.lower() for file in media} == {".mp3"}
    )


def descriptor_path(fd):
    if sys.platform == "linux":
        path = os.readlink(f"/proc/self/fd/{fd}")
    else:
        path = fcntl.fcntl(fd, 50, bytes(1024)).split(b"\x00", 1)[0].decode()
    if not path.startswith("/") or "\n" in path or "\x00" in path:
        raise InspectionError("Opened audio file has no stable local path")
    return path


def _bound_source(fd, chapter, deadline):
    current = identity(os.fstat(fd))
    expected = chapter.identity
    if any(current[key] != expected[key] for key in ("device", "inode", "size", "mtime_ns")):
        raise InspectionError("A chapter file changed before conversion")
    if digest(fd, deadline) != chapter.sha256:
        raise InspectionError("A chapter file's bytes changed before conversion")
    os.lseek(fd, 0, os.SEEK_SET)


def _probe_stream(fd, deadline, should_continue=None):
    os.lseek(fd, 0, os.SEEK_SET)
    output = probe_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-max_alloc",
            "67108864",
            "-protocol_whitelist",
            "file",
            "-show_entries",
            "format=duration,bit_rate:stream=codec_type,sample_rate,channels,duration",
            "-of",
            "json",
            f"/dev/fd/{fd}",
        ],
        fd,
        deadline,
        label="Audio",
        seconds=max(20.0, deadline - time.monotonic()),
        should_continue=should_continue,
    )
    data = json.loads(output)
    streams = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
    if len(streams) != 1:
        raise InspectionError("Expected one audio stream to merge")
    stream = streams[0]
    duration = float(data.get("format", {}).get("duration") or stream.get("duration") or 0)
    rate = int(stream.get("sample_rate") or 0)
    channels = int(stream.get("channels") or 0)
    if duration <= 0 or rate <= 0 or channels <= 0:
        raise InspectionError("Audio duration or layout could not be established")
    bitrate = int(float(data.get("format", {}).get("bit_rate") or 0))
    return {"duration": duration, "sample_rate": rate, "channels": channels, "bit_rate": bitrate}


def _bitrate(streams):
    """Duration-weighted average. Missing rates fall back to size and duration."""
    total_bits = 0.0
    total_duration = 0.0
    for stream in streams:
        duration = float(stream["duration"])
        if duration <= 0:
            continue
        rate = int(stream["bit_rate"])
        if rate <= 0:
            size = int(stream.get("size") or 0)
            rate = int(size * 8 / duration) if size > 0 else 0
        if rate <= 0:
            continue
        total_bits += rate * duration
        total_duration += duration
    if total_duration <= 0:
        return "64k"
    kbps = min(320, max(32, round(total_bits / total_duration / 1000)))
    return f"{kbps}k"


def _metadata(plan, streams):
    lines = [";FFMETADATA1", f"title={_escape(plan.title)}", f"artist={_escape(plan.artist)}"]
    lines.append(f"album={_escape(plan.title)}")
    lines.append(f"album_artist={_escape(plan.artist)}")
    if plan.narrator:
        lines.append(f"composer={_escape(plan.narrator)}")
    if plan.year is not None:
        lines.append(f"date={plan.year}")
    lines.append("genre=Audiobook")
    start = 0
    for chapter, stream in zip(plan.chapters, streams, strict=True):
        duration_ms = int(round(stream["duration"] * 1000))
        if duration_ms <= 0:
            raise InspectionError("A chapter is too short to merge")
        end = start + duration_ms
        lines.extend(
            [
                "",
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start}",
                f"END={end}",
                f"title={_escape(chapter.title)}",
            ]
        )
        start = end
    return "\n".join(lines) + "\n"


def _escape(value):
    return "".join(f"\\{char}" if char in "\\#;=\n" else char for char in value)


def _run(
    command, deadline, *, pass_fds=(), should_continue=None, on_progress=None, output_path=None
):
    if time.monotonic() > deadline:
        raise InspectionError("Audio conversion exceeded its time budget")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            pass_fds=pass_fds,
        )
    except FileNotFoundError as error:
        raise InspectionError(
            "Audio conversion requires ffmpeg and ffprobe on the worker"
        ) from error
    captured = []

    def _drain():
        captured.append(process.stderr.read())

    drainer = threading.Thread(target=_drain, daemon=True)
    drainer.start()
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InspectionError("Audio conversion exceeded its time budget")
            if should_continue is not None:
                should_continue()
            try:
                process.wait(timeout=min(2.0, remaining))
            except subprocess.TimeoutExpired:
                if on_progress is not None and output_path is not None:
                    try:
                        on_progress(os.path.getsize(output_path))
                    except OSError:
                        pass
        drainer.join(timeout=5)
        error = captured[0] if captured else b""
        if process.returncode:
            tail = error.decode("utf-8", "replace").strip().splitlines()
            detail = tail[-1][:180] if tail else "ffmpeg failed"
            raise InspectionError(f"Could not merge audiobook chapters ({detail})")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        drainer.join(timeout=5)


def _verify_output(fd, plan, deadline):
    os.lseek(fd, 0, os.SEEK_SET)
    output = probe_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-max_alloc",
            "67108864",
            "-protocol_whitelist",
            "file",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name:chapter_tags=title",
            "-show_chapters",
            "-of",
            "json",
            f"/dev/fd/{fd}",
        ],
        fd,
        deadline,
        label="Converted audio",
    )
    data = json.loads(output)
    audio = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
    chapters = data.get("chapters") or []
    if len(audio) != 1 or audio[0].get("codec_name") != "aac":
        raise InspectionError("Merged audiobook does not contain one AAC stream")
    if len(chapters) != len(plan.chapters):
        raise InspectionError("Merged audiobook is missing a chapter marker")
    titles = [str((chapter.get("tags") or {}).get("title") or "") for chapter in chapters]
    if titles != [chapter.title for chapter in plan.chapters]:
        raise InspectionError("Merged chapter titles do not match the frozen recipe")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise InspectionError("Merged audiobook duration could not be established")


def encode_chapterized_m4b(
    source, plan, output_path, deadline, should_continue=None, on_progress=None
):
    """Merge opened MP3 chapters into one AAC M4B. Downloads are only read."""
    with ExitStack() as opened, tempfile.TemporaryDirectory(prefix="dewarr-merge-") as temporary:
        streams, descriptors = [], []
        for chapter in plan.chapters:
            if should_continue is not None:
                should_continue()
            stream_fd = opened.enter_context(beneath(source, chapter.source))
            _bound_source(stream_fd, chapter, deadline)
            stream = _probe_stream(stream_fd, deadline, should_continue)
            stream["size"] = chapter.identity["size"]
            streams.append(stream)
            os.lseek(stream_fd, 0, os.SEEK_SET)
            descriptors.append(stream_fd)
        rate = max(stream["sample_rate"] for stream in streams)
        channels = min(2, max(stream["channels"] for stream in streams))
        layout = "mono" if channels == 1 else "stereo"
        filters = [
            f"[{index}:a:0]aformat=sample_fmts=fltp:sample_rates={rate}:"
            f"channel_layouts={layout}[a{index}]"
            for index in range(len(descriptors))
        ]
        filters.append(
            "".join(f"[a{index}]" for index in range(len(descriptors)))
            + f"concat=n={len(descriptors)}:v=0:a=1[out]"
        )
        script = Path(temporary) / "filter.txt"
        metadata = Path(temporary) / "chapters.txt"
        script.write_text(";\n".join(filters) + "\n", encoding="utf-8")
        metadata.write_text(_metadata(plan, streams), encoding="utf-8")
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-v",
            "error",
            "-max_alloc",
            "67108864",
            "-protocol_whitelist",
            "file",
        ]
        for fd in descriptors:
            command.extend(["-i", f"/dev/fd/{fd}"])
        command.extend(
            [
                "-i",
                str(metadata),
                "-filter_complex_script",
                str(script),
                "-map",
                "[out]",
                "-map_metadata",
                str(len(descriptors)),
                "-map_chapters",
                str(len(descriptors)),
                "-c:a",
                "aac",
                "-profile:a",
                "aac_low",
                "-b:a",
                _bitrate(streams),
                "-f",
                "mp4",
                "-y",
                output_path,
            ]
        )
        _run(
            command,
            deadline,
            pass_fds=tuple(descriptors),
            should_continue=should_continue,
            on_progress=on_progress,
            output_path=output_path,
        )
    with open(output_path, "rb") as encoded:
        _verify_output(encoded.fileno(), plan, deadline)


CONVERTERS = {"ffmpeg-chapterized-m4b": encode_chapterized_m4b}


def audio_conversion(item, inspected, metadata):
    planned = item.get("conversion")
    if not planned:
        return None
    chapters = []
    for path in planned["sources"]:
        file = inspected.get(path)
        if not file or "sha256" not in file or "identity" not in file:
            raise ValueError("A chapter file is missing from the inspection")
        chapters.append(
            ConversionChapter(
                source=path,
                title=chapter_title(
                    path, (file.get("technical") or {}).get("tags"), metadata.get("title")
                ),
                sha256=file["sha256"],
                identity=file["identity"],
            )
        )
    authors = [author for author in metadata.get("authors") or [] if str(author).strip()]
    narrators = [narrator for narrator in metadata.get("narrators") or [] if str(narrator).strip()]
    try:
        title = component(metadata["title"])
        artist = component(authors[0] if authors else "Unknown author")
        narrator = component(", ".join(narrators)) if narrators else None
    except (KeyError, ValueError) as error:
        raise ValueError("Audiobook metadata cannot be written into the merged file") from error
    return AudioConversion(
        converter=planned["converter"],
        output_name=planned["output_name"],
        chapters=chapters,
        title=title,
        artist=artist,
        narrator=narrator,
        year=metadata.get("recording_year"),
    )


def convert(source, plan, output_path, deadline, should_continue=None, on_progress=None):
    try:
        encoder = CONVERTERS[plan.converter]
    except KeyError as error:
        raise InspectionError("This audiobook conversion is not available") from error
    encoder(
        source,
        plan,
        output_path,
        deadline,
        should_continue=should_continue,
        on_progress=on_progress,
    )
