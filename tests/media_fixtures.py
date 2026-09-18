"""Small original synthetic book content, generated in disposable test directories."""

import io
import shutil
import subprocess
import zipfile
from xml.sax.saxutils import escape

import pytest


def cover_bytes(*, color="navy", size=(240, 360), format="PNG", **save_options):
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=format, **save_options)
    return output.getvalue()


def epub(path, title="First Harbor", author="Alex Morgan", *, chapter=True, metadata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("mimetype", "application/epub+zip")
        book.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
        )
        book.writestr(
            "OEBPS/book.opf",
            metadata
            or (
                '<package xmlns="http://www.idpf.org/2007/opf"><metadata '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f"<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>"
                "<dc:language>en</dc:language><dc:identifier>synthetic-fixture</dc:identifier>"
                '</metadata><manifest><item id="chapter" href="chapter.xhtml" '
                'media-type="application/xhtml+xml"/></manifest>'
                '<spine><itemref idref="chapter"/></spine></package>'
            ),
        )
        if chapter:
            book.writestr(
                "OEBPS/chapter.xhtml",
                '<html xmlns="http://www.w3.org/1999/xhtml">'
                "<body><p>This is original synthetic fixture content.</p></body></html>",
            )


def audio(path, title="First Harbor", author="Alex Morgan", narrator="Jordan Lee", track=1):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Actual audio inspection requires ffmpeg/ffprobe")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "0.2",
            "-metadata",
            f"album={title}",
            "-metadata",
            f"artist={author}",
            "-metadata",
            f"composer={narrator}",
            "-metadata",
            f"track={track}",
            str(path),
        ],
        check=True,
        timeout=15,
        capture_output=True,
    )
