"""Bounded raster normalization, run in a disposable child process by the worker."""

import io
import sys
import warnings

from PIL import Image, ImageOps

MAX_INPUT = 8 * 1024 * 1024
MAX_OUTPUT = 512 * 1024
MAX_PIXELS = 16_000_000


def normalize(data: bytes) -> bytes:
    if not data or len(data) > MAX_INPUT:
        raise ValueError("Cover input exceeds limits")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as source:
            width, height = source.size
            if min(width, height) < 64 or max(width, height) > 8192 or width * height > MAX_PIXELS:
                raise ValueError("Cover dimensions exceed limits or represent a placeholder")
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("Animated covers are unsupported")
            source.load()  # Require a complete raster, not just a readable header.
            oriented = ImageOps.exif_transpose(source)
            oriented.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            rgba = oriented.convert("RGBA")
            clean = Image.new("RGB", rgba.size, "white")
            clean.paste(rgba, mask=rgba.getchannel("A"))
            for quality in (88, 78, 65, 50):
                output = io.BytesIO()
                clean.save(output, format="JPEG", quality=quality, exif=b"", icc_profile=None)
                result = output.getvalue()
                if len(result) <= MAX_OUTPUT:
                    return result
    raise ValueError("Normalized cover exceeds limits")


def main():
    # Linux production workers get a separate process address-space budget. macOS
    # uses the same input/pixel/time bounds; RLIMIT_AS is not portable there.
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    try:
        result = normalize(sys.stdin.buffer.read(MAX_INPUT + 1))
    except Exception:
        sys.exit(1)  # Never echo source metadata or decoder errors into job logs.
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    main()
