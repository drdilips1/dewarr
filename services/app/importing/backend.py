"""Read backend import settings and prove the configured shared folder route."""

import os
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.importing.filesystem import beneath, directory
from app.importing.publication import PublicationError, object_id, same_object, sync_directory


@contextmanager
def mapping_marker(root: Path, name: str):
    if not re.fullmatch(r"book-search-check-[a-f0-9]{32}", name):
        raise PublicationError("Invalid mapping challenge name")
    with directory(root) as parent:
        os.mkdir(name, mode=0o755, dir_fd=parent)
        with beneath(parent, name, folder=True) as marker:
            sync_directory(parent)
            try:
                yield
                with directory(root) as current:
                    if not same_object(current, object_id(parent)):
                        raise PublicationError("Library root changed during mapping verification")
            finally:
                try:
                    with beneath(parent, name, folder=True) as current:
                        if not same_object(current, object_id(marker)):
                            raise PublicationError("Mapping marker changed; replacement preserved")
                    # Only an empty directory with our held identity can be removed.
                    os.rmdir(name, dir_fd=parent)
                    sync_directory(parent)
                except FileNotFoundError:
                    pass


async def verify_backend(adapter, library_id, backend_root, worker_root, medium):
    version = await adapter.server_version()
    configuration = await adapter.import_configuration(library_id)
    capabilities, _ = await adapter.authorize()
    if backend_root not in configuration.folders:
        raise PublicationError("Selected path is not an exact folder root of this ABS library")
    if medium == "ebook" and configuration.audiobooks_only:
        raise PublicationError("Disable Audiobooks only for this ebook destination in ABS")
    precedence = configuration.metadata_precedence
    known_sources = {
        "folderStructure",
        "audioMetatags",
        "nfoFile",
        "txtFiles",
        "opfFile",
        "absMetadata",
    }
    if (
        "opfFile" not in precedence
        or set(precedence) - known_sources
        or any(
            precedence.index(source) > precedence.index("opfFile")
            for source in ("folderStructure", "audioMetatags")
            if source in precedence
        )
    ):
        raise PublicationError(
            "ABS must apply OPF metadata after folder and embedded audio metadata"
        )
    if "scan" not in capabilities.operations and not configuration.watcher_enabled:
        raise PublicationError("Enable the ABS watcher or provide a scan-capable connection")
    if version != "2.36.1":
        raise PublicationError("This ABS version has not passed the import compatibility checks")
    name = "book-search-check-" + uuid4().hex
    if await adapter.path_exists(backend_root, name):
        raise PublicationError("Unexpected existing mapping challenge; no directory was changed")
    with mapping_marker(worker_root, name):
        if not await adapter.path_exists(backend_root, name):
            raise PublicationError("Worker and ABS do not see the same library folder")
    if await adapter.path_exists(backend_root, name):
        raise PublicationError("ABS still sees the removed challenge; mapping is not reliable")
    if await adapter.import_configuration(library_id) != configuration:
        raise PublicationError("ABS library settings changed during mapping verification")
    return {
        "version": version,
        "library_id": library_id,
        "configuration": configuration.model_dump(),
        "root_mapping": True,
        "scan_capable": "scan" in capabilities.operations,
        "watcher_enabled": configuration.watcher_enabled,
        "layout": "conventional",  # Nested watcher/import workflow matrix is not complete.
    }
