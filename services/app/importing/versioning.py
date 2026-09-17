from app.importing.naming import fingerprint


def version_revision(version):
    return fingerprint(
        {
            name: str(value) if name in {"id", "work_id"} else value
            for name in (
                "id",
                "work_id",
                "medium",
                "title",
                "language",
                "narrators",
                "abridged",
                "publication_year",
                "identifiers",
            )
            if (value := getattr(version, name)) is not None
        }
    )
