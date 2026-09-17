"""Synthetic examples for the naming editor; never library inventory."""

from uuid import UUID

from app.importing.naming import ImportGroup, NamingMetadata, PlannedSourceFile


def naming_examples():
    def group(number, medium, title, paths, **metadata):
        return ImportGroup(
            id=UUID(int=number),
            work_id=UUID(int=number // 10 or number),
            version_id=UUID(int=number + 1000),
            medium=medium,
            metadata=NamingMetadata(title=title, authors=["Alex Morgan"], **metadata),
            files=[
                PlannedSourceFile(path=path, track=index + 1 if len(paths) > 1 else None)
                for index, path in enumerate(paths)
            ],
        )

    return [
        group(
            11,
            "ebook",
            "The First Harbor",
            ["Harbor.Complete/Book_01/First.epub"],
            series="Harbor Trilogy",
            sequence="1",
            edition_year=2017,
            edition="First edition",
        ),
        group(
            12,
            "audio",
            "The First Harbor",
            ["Harbor.Complete/Book_01/Jordan/First.m4b"],
            series="Harbor Trilogy",
            sequence="1",
            recording_year=2018,
            narrators=["Jordan Lee"],
        ),
        group(
            13,
            "audio",
            "The First Harbor",
            ["Alternate.Recording/First.m4b"],
            series="Harbor Trilogy",
            sequence="1",
            recording_year=2024,
            narrators=["Casey Reed"],
        ),
        group(
            20,
            "audio",
            "Beyond the Harbor",
            ["Harbor.Complete/Book_02/track01.mp3", "Harbor.Complete/Book_02/track02.mp3"],
            series="Harbor Trilogy",
            sequence="2",
            recording_year=2020,
            narrators=["Jordan Lee"],
        ),
        group(30, "ebook", "A Standalone Story", ["Standalone/Story.epub"]),
    ]
