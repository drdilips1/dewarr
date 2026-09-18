"""Disposable libtorrent parser, with memory/CPU limits and no network session."""

import hashlib
import json
import sys

MAX_INPUT = 8 * 1024 * 1024
MAX_FILES = 10000


class InvalidTorrent(ValueError):
    pass


def component(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or any(c in value for c in "/\\:")
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or len(value.encode("utf-8")) > 255
    ):
        raise InvalidTorrent("Torrent contains unsupported or unsafe file names.")
    return value


def raw_files(info, name):
    """Check raw components before accepting libtorrent's sanitized file layout."""
    result = {}

    def add(parts, details):
        flags = details.get(b"attr", b"")
        if not isinstance(flags, bytes) or b"l" in flags or b"symlink path" in details:
            raise InvalidTorrent("Torrent symlinks are not supported.")
        path = "/".join(component(part) for part in parts)
        if len(path) > 2048:
            raise InvalidTorrent("Torrent file paths exceed supported limits.")
        if b"p" in flags:
            return
        if path in result:
            raise InvalidTorrent("Torrent contains duplicate file paths.")
        size = details[b"length"]
        if type(size) is not int or size < 0:
            raise InvalidTorrent("Torrent file size is invalid.")
        result[path] = size

    if b"files" in info:
        for file in info[b"files"]:
            add([name, *file.get(b"path.utf-8", file[b"path"])], file)
    elif b"length" in info:
        add([name], info)
    elif b"file tree" in info:
        tree = info[b"file tree"]
        # BEP 52 represents a single file by its own name in the tree, without
        # an additional root directory; multifile trees live under info.name.
        single = len(tree) == 1 and b"" in next(iter(tree.values()))
        stack = [(tree, [] if single else [name])]
        while stack:
            node, prefix = stack.pop()
            for key, child in node.items():
                if key == b"":
                    if len(node) != 1:
                        raise InvalidTorrent("Torrent file and directory paths conflict.")
                    add(prefix, child)
                else:
                    stack.append((child, [*prefix, component(key)]))
    if not result or len(result) > MAX_FILES:
        raise InvalidTorrent("Torrent file count exceeds supported limits or is empty.")
    return result


def describe(data):
    import libtorrent as lt

    params = lt.load_torrent_buffer(
        data,
        {
            "max_buffer_size": MAX_INPUT,
            "max_decode_depth": 40,
            "max_decode_tokens": 200000,
            "max_pieces": 400000,
            "max_duplicate_filenames": 0,
            "max_directory_depth": 30,
        },
    )
    torrent = params.ti
    decoded = lt.bdecode(data)
    info = decoded[b"info"]
    name = component(info.get(b"name.utf-8", info[b"name"]))
    original = raw_files(info, name)
    layout = torrent.layout()
    if layout.num_files() > MAX_FILES * 2:
        raise InvalidTorrent("Torrent file count exceeds supported limits.")
    files, observed, padding = [], {}, 0
    for index in range(layout.num_files()):
        flags = layout.file_flags(index)
        if flags & lt.file_storage.flag_symlink:
            raise InvalidTorrent("Torrent symlinks are not supported.")
        size = layout.file_size(index)
        if flags & lt.file_storage.flag_pad_file:
            padding += size
            continue
        path = layout.file_path(index)
        for part in path.split("/"):
            component(part)
        if path in observed:
            raise InvalidTorrent("Torrent contains duplicate file paths.")
        observed[path] = size
        files.append({"index": index, "path": path, "size_bytes": size})
    if observed != original or not 0 < sum(observed.values()) <= 2**63 - 1:
        raise InvalidTorrent("Torrent file layout is ambiguous or changed during validation.")
    # In a hybrid, validate the v2 tree independently of the v1 file list.
    if b"file tree" in info and (b"files" in info or b"length" in info):
        v2_info = {key: value for key, value in info.items() if key not in {b"files", b"length"}}
        if raw_files(v2_info, name) != original:
            raise InvalidTorrent("Hybrid torrent file layouts disagree.")
    hashes = torrent.info_hashes()
    if not hashes.has_v1() and not hashes.has_v2():
        raise InvalidTorrent("Torrent has no supported identity.")
    return {
        "name": name,
        "artifact_sha256": hashlib.sha256(data).hexdigest(),
        "infohash_v1": str(hashes.v1) if hashes.has_v1() else None,
        "infohash_v2": str(hashes.v2) if hashes.has_v2() else None,
        "private": torrent.priv(),
        "content_bytes": sum(observed.values()),
        "torrent_bytes": torrent.total_size(),
        "padding_bytes": padding,
        "files": files,
        "parser": f"libtorrent/{lt.__version__}",
    }


def main():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    try:
        data = sys.stdin.buffer.read(MAX_INPUT + 1)
        if not data or len(data) > MAX_INPUT:
            raise InvalidTorrent("Torrent metadata exceeds supported limits or is empty.")
        result = describe(data)
    except InvalidTorrent as error:
        result = {"error": str(error)}
    except Exception:
        result = {"error": "Torrent metadata could not be validated."}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
