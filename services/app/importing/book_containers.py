"""Bound ZIP allocation before opening EPUB and comic-book containers."""

import os
import struct

from app.importing.filesystem import InspectionError


def check_zip_directory(fd, label):
    size = os.fstat(fd).st_size
    tail_offset = max(0, size - 65557)
    tail = os.pread(fd, min(size, 65557), tail_offset)
    end = tail.rfind(b"PK\x05\x06")
    if end < 0 or len(tail) - end < 22:
        raise InspectionError(f"{label} has no complete ZIP directory")
    _, disk, start_disk, count, total, directory_size, offset, comment = struct.unpack(
        "<4s4H2LH", tail[end : end + 22]
    )
    if (
        disk
        or start_disk
        or count != total
        or total > 10000
        or directory_size > 8 * 1024 * 1024
        or offset + directory_size > tail_offset + end
        or end + 22 + comment != len(tail)
        or (end >= 20 and tail[end - 20 : end - 16] == b"PK\x06\x07")
    ):
        raise InspectionError(
            f"{label} directory exceeds supported limits or uses multipart/ZIP64 storage"
        )
