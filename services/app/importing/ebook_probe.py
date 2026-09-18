"""Structural PDF and decoded-page CBZ inspection in a disposable process.

This establishes readable content, not catalog identity or completeness of a work.
No document scripts, attachments, external resources or source paths are executed.
"""

import io
import json
import math
import os
import stat
import sys
import warnings
import zipfile
from pathlib import PurePosixPath

from app.importing.book_containers import check_zip_directory
from app.importing.filesystem import InspectionError, relative_parts

MAX_INPUT = 512 * 1024 * 1024
MAX_PAGES = 10000
MAX_PAGE_BYTES = 32 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_PIXELS = 32_000_000
IMAGE_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


def text(value):
    return value.strip()[:600] if isinstance(value, str) and value.strip() else None


def inspect_pdf(fd):
    from pypdf import Configuration, PdfReader, apply_configuration
    from pypdf.generic import ArrayObject, NullObject, StreamObject

    configuration = Configuration(
        maximum_declared_stream_length=MAX_PAGE_BYTES,
        array_based_stream_maximum_output_length=MAX_PAGE_BYTES,
        zlib_maximum_output_length=MAX_PAGE_BYTES,
        lzw_maximum_output_length=MAX_PAGE_BYTES,
        run_length_maximum_output_length=MAX_PAGE_BYTES,
        page_tree_maximum_entries=MAX_PAGES * 2,
        page_tree_maximum_depth=40,
    )
    if not os.pread(fd, 8, 0).startswith(b"%PDF-"):
        raise InspectionError("File does not declare a PDF document")
    with os.fdopen(os.dup(fd), "rb") as source, apply_configuration(configuration):
        source.seek(0)
        reader = PdfReader(source, strict=True)
        if reader.is_encrypted:
            raise InspectionError("Encrypted PDF requires review; automatic decryption is disabled")
        count = len(reader.pages)
        if not 0 < count <= MAX_PAGES:
            raise InspectionError("PDF page count exceeds supported limits or contains no pages")
        total, content_pages = 0, 0
        for page in reader.pages:
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            if not all(math.isfinite(value) and 0 < value <= 100000 for value in (width, height)):
                raise InspectionError("PDF page dimensions are invalid")
            contents = page.get("/Contents")
            if contents is None or isinstance(contents.get_object(), NullObject):
                continue  # Blank pages within a book are legitimate.
            contents = contents.get_object()
            streams = contents if isinstance(contents, ArrayObject) else [contents]
            if len(streams) > 1000:
                raise InspectionError("PDF page contains too many content streams")
            page_bytes = 0
            for stream in streams:
                resolved = stream.get_object()
                if not isinstance(resolved, StreamObject):
                    raise InspectionError("PDF page references missing or invalid content")
                page_bytes += len(resolved.get_data())
                if page_bytes > MAX_PAGE_BYTES:
                    raise InspectionError("PDF page content exceeds supported limits")
            total += page_bytes
            content_pages += bool(page_bytes)
            if total > MAX_EXPANDED:
                raise InspectionError("PDF content exceeds the inspection budget")
        if not content_pages:
            raise InspectionError("PDF contains no readable page content")
        metadata = reader.metadata or {}
        author, language = text(metadata.get("/Author")), text(reader.root_object.get("/Lang"))
        return {
            "title": text(metadata.get("/Title")),
            "authors": [author] if author else [],
            "languages": [language] if language else [],
            "identifiers": [],
            "pages": count,
            "content_pages": content_pages,
            "validation": "page-structure-and-content-streams",
        }


def inspect_cbz(fd):
    from defusedxml import ElementTree
    from PIL import Image

    check_zip_directory(fd, "CBZ")
    with os.fdopen(os.dup(fd), "rb") as source, zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len({entry.filename for entry in entries}) != len(entries):
            raise InspectionError("CBZ contains conflicting duplicate entries")
        pages, expanded, comic_info = [], 0, None
        for entry in entries:
            relative_parts(entry.filename.rstrip("/"))
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                raise InspectionError("CBZ contains encrypted or special-file entries")
            if entry.is_dir():
                continue
            expanded += entry.file_size
            if expanded > MAX_EXPANDED or entry.file_size > MAX_PAGE_BYTES:
                raise InspectionError("CBZ expanded content exceeds supported limits")
            extension = PurePosixPath(entry.filename).suffix.lower().lstrip(".")
            if extension in IMAGE_FORMATS:
                pages.append((entry, IMAGE_FORMATS[extension]))
            elif PurePosixPath(entry.filename).name.casefold() == "comicinfo.xml":
                if comic_info is not None or entry.file_size > 1024 * 1024:
                    raise InspectionError("CBZ metadata is ambiguous or exceeds supported limits")
                comic_info = entry
            elif extension not in {"txt", "nfo", "xml"}:
                raise InspectionError("CBZ contains unsupported page or embedded file types")
        if not 0 < len(pages) <= MAX_PAGES:
            raise InspectionError("CBZ needs readable image pages within supported limits")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            for entry, image_format in pages:
                with archive.open(entry) as page:
                    data = page.read(MAX_PAGE_BYTES + 1)
                if len(data) > MAX_PAGE_BYTES:
                    raise InspectionError("CBZ page exceeds supported limits")
                with Image.open(io.BytesIO(data), formats=(image_format,)) as image:
                    width, height = image.size
                    if (
                        min(width, height) < 1
                        or max(width, height) > 16384
                        or width * height > MAX_PIXELS
                        or getattr(image, "n_frames", 1) != 1
                    ):
                        raise InspectionError("CBZ page dimensions or animation exceed limits")
                    image.load()
        metadata = {
            "title": None,
            "authors": [],
            "languages": [],
            "identifiers": [],
            "pages": len(pages),
            "validation": "decoded-image-pages",
        }
        if comic_info:
            info = ElementTree.fromstring(archive.read(comic_info))
            if info.tag != "ComicInfo":
                raise InspectionError("CBZ metadata is not a ComicInfo document")
            author, language = text(info.findtext("Writer")), text(info.findtext("LanguageISO"))
            metadata.update(
                title=text(info.findtext("Title")),
                authors=[author] if author else [],
                languages=[language] if language else [],
                series=text(info.findtext("Series")),
                sequence=text(info.findtext("Number")),
            )
        return metadata


def main():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    try:
        fd, extension = int(sys.argv[1]), sys.argv[2]
        if os.fstat(fd).st_size > MAX_INPUT:
            raise InspectionError("Ebook exceeds the supported inspection size")
        metadata = {"pdf": inspect_pdf, "cbz": inspect_cbz}[extension](fd)
        result = {"metadata": metadata}
    except InspectionError as error:
        result = {"error": str(error)}
    except Exception:
        sys.exit(1)  # Do not expose parser diagnostics or embedded private metadata.
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
