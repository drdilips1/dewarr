"""Source claims that corroborate a requested version, never owned media."""

from app.domain.narrators import name_key
from app.domain.release_profiles import normalized
from app.importing.match_evidence import identifier, isbn_key


def abridgment_claims(release):
    labels = {normalized(tag) for tag in getattr(release, "tags", [])}
    value = getattr(release, "abridged", None)
    if value is not None:
        labels.add("abridged" if value else "unabridged")
    return labels & {"abridged", "unabridged"}


def abridgment(release):
    claims = abridgment_claims(release)
    return next(iter(claims)) == "abridged" if len(claims) == 1 else None


def version_reasons(release, version):
    """An exact source ISBN corroborates a candidate; file inspection still decides import.

    Only the adapter's explicit ISBN field is used. Description prose, filenames,
    narrator overlap and tracker IDs cannot establish recording/edition identity.
    """
    expected = {
        found[1]
        for key, values in version.identifiers.items()
        for value in (values if isinstance(values, list) else [values])
        if (found := identifier(key, value)) and found[0] == "isbn"
    }
    observed = isbn_key(getattr(release, "isbn", None))
    reasons = []
    if not observed or observed not in expected:
        reasons.append(
            "Exact recording identity requires a corroborated catalog ISBN; "
            "narrator names alone are insufficient"
            if version.medium == "audio"
            else "The source does not corroborate the selected edition's ISBN"
        )
    if version.medium == "audio":
        expected_names = {name_key(name) for name in version.narrators}
        observed_names = {name_key(name) for name in release.narrators}
        if not expected_names or expected_names != observed_names:
            reasons.append(
                "The source must confirm the selected recording's complete narrator credits"
            )
        # A known contradictory claim is disqualifying even when identifiers match.
        # Missing source abridgment may rely on the version identifier, unless the
        # request separately requires an explicit abridgment claim.
        claimed = abridgment(release)
        if len(abridgment_claims(release)) > 1:
            reasons.append("The source has contradictory abridgment labels")
        elif claimed is not None and version.abridged is not None and claimed != version.abridged:
            reasons.append("The source abridgment conflicts with the selected recording")
    return reasons
