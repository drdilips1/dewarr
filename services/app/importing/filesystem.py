"""Read-only descriptor-relative access to explicitly mounted download trees."""

import hashlib
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from app.importing.naming import PlannedSourceFile


class InspectionError(ValueError):
    pass


def relative_parts(value: str) -> list[str]:
    PlannedSourceFile(path=value)
    return value.split("/")


@contextmanager
def directory(path: Path):
    if not path.is_absolute() or str(path) == "/" or ".." in path.parts:
        raise InspectionError("Configure an absolute download root, not the filesystem root")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def beneath(root: int, relative: str, *, folder=False):
    fd = os.dup(root)
    try:
        parts = relative_parts(relative)
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if folder or index < len(parts) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if not (stat.S_ISDIR(info.st_mode) if folder else stat.S_ISREG(info.st_mode)):
            raise InspectionError("Only regular files and directories can be inspected")
        yield fd
    finally:
        os.close(fd)


@contextmanager
def source_scope(root: int, relative: str, kind: str):
    """Open the source directory without broadening a single-file selection."""
    parts = relative_parts(relative)
    if kind == "directory":
        with beneath(root, relative, folder=True) as fd:
            yield fd
    elif kind == "file":
        if len(parts) > 1:
            with beneath(root, "/".join(parts[:-1]), folder=True) as fd:
                yield fd
        else:
            fd = os.dup(root)
            try:
                yield fd
            finally:
                os.close(fd)
    else:
        raise InspectionError("Unknown source inspection scope")


def identity(info):
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def digest(fd, deadline):
    os.lseek(fd, 0, os.SEEK_SET)
    result = hashlib.sha256()
    while True:
        if time.monotonic() > deadline:
            raise InspectionError("Inspection exceeded its time budget; reduce the batch size")
        block = os.read(fd, 1024 * 1024)
        if not block:
            break
        result.update(block)
    os.lseek(fd, 0, os.SEEK_SET)
    return result.hexdigest()


def enumerate_files(root, *, max_entries=10000, max_depth=20):
    files = []
    visited = 0

    def walk(fd, parent, depth):
        nonlocal visited
        if depth > max_depth:
            raise InspectionError("Download directory exceeds the supported depth")
        before = identity(os.fstat(fd))
        with os.scandir(fd) as entries:
            for entry in entries:
                visited += 1
                if visited > max_entries:
                    raise InspectionError("Download exceeds the supported entry count")
                relative = f"{parent}/{entry.name}" if parent else entry.name
                relative_parts(relative)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    with beneath(fd, entry.name, folder=True) as child:
                        if identity(os.fstat(child)) != identity(info):
                            raise InspectionError("Directory changed during inspection")
                        walk(child, relative, depth + 1)
                elif stat.S_ISREG(info.st_mode):
                    files.append((relative, identity(info)))
                else:
                    raise InspectionError("Download contains a symlink or special file")
        if before != identity(os.fstat(fd)):
            raise InspectionError("Directory changed during inspection")

    walk(root, "", 0)
    return sorted(files)
